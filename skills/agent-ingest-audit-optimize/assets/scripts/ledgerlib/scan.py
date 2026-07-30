"""Reading a client's configuration into baseline items, keeping no secrets.

`scan` is the read-only half of the ledger tools. Given an adapter's resolved
anchor roots it probes the files the adapter names, digests them, parses the
two formats the adapters use, and emits baseline items. It writes nothing --
no file, no directory -- and it never executes anything a configuration file
names; a key whose value is a shell command is recorded as a name like any
other value. Spec `docs/specs/2026-07-30-adapters-and-scan.md` section 3
owns the behaviour; design spec section 9 owns the rules below.

Redaction is deliberately the first thing this module grew, before any
probing or parsing existed, so that no function here can ever read a value
into an item before there is somewhere safe to put it. Design spec section 9
requires that a sensitive value never enters an item's attributes -- not even
briefly -- so redaction happens at the point a document is read, not on the
way out.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from collections.abc import Sequence


def _value_digest(value: object) -> str:
    """Digest a value over its canonical JSON encoding.

    Spec section 3.5: `sort_keys=True`, `separators=(",", ":")`, UTF-8. Two
    equal values therefore digest identically regardless of the key order the
    file happened to use, and two different values digest differently. That
    is the whole contract the digest owes `drift`, which uses it to tell "the
    token changed" from "the token is gone" without ever having held either.

    Nothing here can raise. A value the canonical encoder cannot handle is
    still a value that must be replaced by a marker, and raising would abort a
    scan over a file that is otherwise perfectly readable -- `tomllib` yields
    `datetime.datetime`, `datetime.date`, and `datetime.time` objects, and
    `json.dumps` refuses all three. Such a value is encoded through `repr`
    instead (`default=repr`, which reaches non-serialisable leaves nested
    inside an otherwise-encodable container), and if the encoder still fails
    -- a circular reference raises `ValueError`, a pathologically deep one
    `RecursionError` -- the whole value's `repr` is hashed instead.

    The fallback is weaker than the canonical encoding: two distinct objects
    sharing a `repr` collide. It is not weaker in the way that matters, since
    a digest is a change detector and never a value that can be read back.
    """
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=repr
        )
    except (TypeError, ValueError, RecursionError):
        encoded = repr(value)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_sensitive(key: object, patterns: Sequence[str]) -> bool:
    """Whether a key name matches any sensitive-key pattern.

    `fnmatchcase` against both sides lowered, rather than `fnmatch`, because
    `fnmatch` normalizes case through `os.path.normcase` -- which lowercases
    on Windows and does nothing on POSIX. That would make `API_TOKEN` match
    `*token*` on one platform and not the other, and a redaction rule that
    depends on the operating system is not a redaction rule.

    A non-string key cannot match: JSON and TOML both guarantee string keys,
    so this only arises for a caller passing a hand-built mapping, and
    inventing a string form for such a key would invent a match rule nothing
    documents. Recursion still descends into its value.
    """
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(
        isinstance(pattern, str) and fnmatch.fnmatchcase(lowered, pattern.lower())
        for pattern in patterns
    )


def redact(value: object, patterns: Sequence[str]) -> object:
    """Copy `value`, replacing every sensitive key's value with a marker.

    Design spec section 9: a value under a `sensitive_key_patterns` match is
    never copied -- the key name and a digest of the value are stored -- and
    the rule applies recursively into nested objects, including objects inside
    arrays. A matched key's value becomes
    `{"redacted": True, "digest": "sha256:..."}` whatever its type: a number,
    an array, and an object are as capable of carrying a secret as a string,
    and a rule that only covered strings would leave `{"env": {...}}`
    untouched -- exactly the shape the research names as secret-bearing in
    both clients.

    Recursion stops at a match. Nothing beneath a redacted subtree is walked,
    because walking it would put those values in memory and one bug away from
    output; the subtree is digested whole and its interior never becomes keys
    of the result. This is why the pattern `env` alone is enough to protect an
    entire MCP `env` block without enumerating what is inside it.

    A structure with no match passes through unchanged by equality. Containers
    are always rebuilt, so the caller's document is never mutated; leaves are
    shared, since they are not modified.

    `patterns` is a parameter rather than a module constant: the patterns come
    from the adapter, which is data, and a second client's secret-bearing key
    names are not this module's business to know.
    """
    if isinstance(value, dict):
        result: dict = {}
        for key, item in value.items():
            if _is_sensitive(key, patterns):
                result[key] = {"redacted": True, "digest": _value_digest(item)}
            else:
                result[key] = redact(item, patterns)
        return result
    if isinstance(value, list):
        return [redact(item, patterns) for item in value]
    return value
