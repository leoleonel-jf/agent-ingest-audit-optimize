"""Assembling and escaping the payload `dashboard.py build` embeds.

`build_payload` is the seam between the read-only ledger commands and the
generated dashboard: it validates a ledger once, then asks `drift_report` and
`rollback_preview` -- the exact functions `drift` and `rollback-preview`
already call -- to classify it, and folds their answers into one JSON-safe
document (design spec `docs/specs/2026-07-31-dashboard-build.md` section 2
owns the shape). `serialize_payload` is the one function that turns that
document into text a browser can embed without ever containing a literal
`<`: the whole stored-XSS control depends on every byte reaching the page
having passed through it (spec section 1.1). Neither function writes
anything -- injecting the result into a template and writing the file is
`dashboard.py build`'s job, not this module's.

Reuse here is the same structural rule `rollback.py` documents for
`classify_target`: `drift_report` and `rollback_preview` are called
directly, never reimplemented, so a payload's `computed.drift` and each
`computed.previews` entry are the exact report the 0.3.0 commands print --
same code, not similar code, and a single patch on either name changes both
the command and the dashboard together.

A sub-computation that fails -- an unknown client, an unreadable adapter, a
run whose backup cannot be classified -- becomes `{"error": "<message>"}` in
its own key rather than aborting the whole build (design spec section 14):
the dashboard is meant to degrade one panel at a time, never all at once. A
ledger that fails schema validation is the one failure that aborts before
anything is computed, because a document `validate_ledger` refuses is not a
record of anything a report could describe.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from ledgerlib import drift, rollback
from ledgerlib.constants import TOOL_VERSION
from ledgerlib.errors import LedgerError
from ledgerlib.validate import validate_ledger


PAYLOAD_SCHEMA = 1

# Design spec section 5: exactly the two dictionaries the shell embeds. A
# `lang` naming anything else cannot select a dictionary the shell actually
# has, so it degrades to English here rather than reaching the template as a
# promise the shell cannot keep.
SUPPORTED_LANGUAGES = frozenset({"en", "pt-BR"})

# The two characters spec section 1.1 requires escaped beside `<`, named by
# `chr()` rather than as a literal escape sequence in this source file:
# U+2028/U+2029 are themselves invisible line/paragraph separators, and
# spelling one as a raw byte in a diff is exactly the kind of thing a later
# edit silently corrupts without a test noticing.
_LINE_SEPARATOR = chr(0x2028)
_PARAGRAPH_SEPARATOR = chr(0x2029)


def serialize_payload(payload: dict) -> str:
    """Render `payload` as the exact text the dashboard's data island holds.

    Design spec section 1.1, verbatim: compact, deterministic JSON, then
    three textual replacements -- every `<` becomes the six characters
    `\\u003c`, and every U+2028/U+2029 becomes its own `\\u` escape.
    `\\u003c` is a JSON string escape, so `JSON.parse` restores the original
    character on the browser side, but the *document* text this function
    returns never contains a literal `<`: `</script>`, `<script>`, and
    `<!--` are unrepresentable regardless of what the ledger contains. This
    is the primary stored-XSS control, and it is deliberately global rather
    than pattern-matched -- `assertNotIn("<", serialized)` is the whole
    property, not a search for particular tag names.

    `sort_keys=True` and compact separators make two calls on the same
    payload byte-identical, which is what lets `dashboard.py build`'s
    overwrite guard -- and any future diffing -- trust the output at all.
    """
    text = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    text = (
        text.replace("<", "\\u003c")
        .replace(_LINE_SEPARATOR, "\\u2028")
        .replace(_PARAGRAPH_SEPARATOR, "\\u2029")
    )
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def _generated_at(today: str | None) -> str:
    """An ISO-8601 UTC timestamp, its date pinned to `today` when supplied.

    `today` mirrors `drift_report`'s parameter of the same name, for the
    same reason: expiry-style comparisons need a value a test can fix, and a
    generated timestamp is exactly that kind of comparison's other side.
    Only the date component is pinned -- the time-of-day is always the
    clock's, because `generated_at` is a real timestamp the shell reports
    verbatim, not a second `today` parameter wearing a timestamp's shape.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    if today is not None:
        try:
            pinned = datetime.date.fromisoformat(today)
        except ValueError as exc:
            raise LedgerError(f"--today must be YYYY-MM-DD: {today!r}") from exc
        now = now.replace(year=pinned.year, month=pinned.month, day=pinned.day)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_lang(lang: str | None, ledger: dict, messages: list[str]) -> str:
    """`lang`, or `ledger["language"]`, or `"en"` -- design spec section 5.

    A code naming neither embedded dictionary cannot be rendered, so it
    falls back to `"en"` and the fallback is recorded in `messages`, the
    same stream `--lang`'s stderr warning (design spec section 12.4)
    eventually reads from -- one fallback, stated once, regardless of
    whether it was `--lang` or the ledger's own `language` field that named
    the unknown code.
    """
    candidate = lang if lang is not None else ledger.get("language")
    if candidate in SUPPORTED_LANGUAGES:
        return candidate
    messages.append(
        f"unsupported language {candidate!r}: the dashboard falls back to 'en'"
    )
    return "en"


def _expired_evidence(ledger: dict, today: str) -> list[dict]:
    """Every evidence entry, across every record, whose `expires_on` has passed.

    `today` is a parameter for the reason `drift_report`'s is: expiry is a
    comparison between two dates, and a test must be able to supply both
    sides. `expires_on` is `YYYY-MM-DD` like every other date this ledger
    stores, which sorts lexicographically in date order, so the comparison
    needs no parsing. An entry with no recorded `expires_on` -- or one that
    is not a string -- names nothing to compare and is silently not expired,
    never a crash.
    """
    expired: list[dict] = []
    records = ledger.get("records")
    records = records if isinstance(records, list) else []
    for record in records:
        if not isinstance(record, dict):
            continue
        evidence = record.get("evidence")
        if not isinstance(evidence, list):
            continue
        for item in evidence:
            if not isinstance(item, dict):
                continue
            expires_on = item.get("expires_on")
            if not isinstance(expires_on, str) or expires_on >= today:
                continue
            expired.append(
                {
                    "record": record.get("id"),
                    "source": item.get("source"),
                    "expires_on": expires_on,
                }
            )
    return expired


def _unreachable_projects(ledger: dict) -> list[str]:
    """Every `known_projects` entry whose recorded root no longer exists.

    This asks the filesystem a single question -- does the path exist -- and
    nothing else: it never opens the project's own ledger, never reads a
    byte of it, and never resolves it through the anchor-safety layer that
    governs a client's configuration files, because a known project's root
    is not an anchor any adapter declared; it is simply a path this ledger
    recorded. A root too malformed even to stat is honestly unreachable
    rather than a crash reaching the caller.
    """
    unreachable: list[str] = []
    projects = ledger.get("known_projects")
    projects = projects if isinstance(projects, list) else []
    for entry in projects:
        if not isinstance(entry, dict):
            continue
        root = entry.get("project_root")
        if not isinstance(root, str) or not root.strip():
            continue
        try:
            reachable = Path(root).exists()
        except (OSError, ValueError):
            reachable = False
        if not reachable:
            unreachable.append(root)
    return unreachable


def build_payload(
    ledger: dict,
    *,
    ledger_source: str,
    lang: str | None,
    adapter: Path | None = None,
    user_config: Path | None = None,
    project: Path | None = None,
    today: str | None = None,
) -> tuple[dict, list[str]]:
    """Assemble the payload design spec section 2 describes.

    Returns `(payload, messages)`. Validation happens exactly once, up
    front: `validate_ledger` is reused rather than reimplemented (drift.py's
    docstring states the same rule for the same reason), and a document it
    refuses raises `LedgerError` naming its first finding -- nothing is
    computed for a ledger nothing vouched for, mirroring `drift_command`'s
    and `rollback_preview_command`'s own refusal to classify an invalid
    document.

    Everything past that point degrades one panel at a time (design spec
    section 14) rather than aborting the whole build: `drift_report` and
    each call to `rollback_preview` run inside their own `try`/`except
    LedgerError`, and a failure lands as `{"error": "<message>"}` in the key
    it would otherwise have filled. `computed.previews` holds one entry per
    RUN record that names a backup (`backup` is not `None`), keyed by that
    run's own id -- a RUN with no backup has nothing rollback-preview could
    report, so it is simply absent from `previews` rather than an error.

    No file is opened here: `ledger` is already a loaded document, and
    `ledger_source` exists only to label a validation finding, the way a
    path read by `drift_command` labels one. The one filesystem question
    this function asks directly -- rather than through `drift_report` or
    `rollback_preview` -- is `unreachable_projects`' existence check.
    """
    if not isinstance(ledger, dict):
        raise LedgerError("ledger must be a JSON object")

    invalid = validate_ledger(ledger, source=ledger_source)
    if invalid:
        raise LedgerError(invalid[0])

    messages: list[str] = []
    today_value = today if today is not None else datetime.date.today().isoformat()
    resolved_lang = _resolve_lang(lang, ledger, messages)

    try:
        drift_result, drift_messages, _drift_code = drift.drift_report(
            ledger,
            adapter=adapter,
            user_config=user_config,
            project=project,
            today=today,
        )
        messages.extend(drift_messages)
    except LedgerError as exc:
        drift_result = {"error": str(exc)}

    previews: dict[str, object] = {}
    records = ledger.get("records")
    records = records if isinstance(records, list) else []
    for record in records:
        if not isinstance(record, dict) or record.get("type") != "RUN":
            continue
        if record.get("backup") is None:
            continue
        run_id = record.get("id")
        try:
            preview, preview_messages, _preview_code = rollback.rollback_preview(
                ledger,
                run_id,
                adapter=adapter,
                user_config=user_config,
                project=project,
            )
            messages.extend(preview_messages)
            previews[run_id] = preview
        except LedgerError as exc:
            previews[run_id] = {"error": str(exc)}

    payload = {
        "payload_schema": PAYLOAD_SCHEMA,
        "mode": "built",
        "generated_at": _generated_at(today),
        "tool_version": TOOL_VERSION,
        "lang": resolved_lang,
        "ledger": ledger,
        "computed": {
            "drift": drift_result,
            "previews": previews,
            "expired_evidence": _expired_evidence(ledger, today_value),
            "unreachable_projects": _unreachable_projects(ledger),
        },
    }

    seen: set[str] = set()
    deduped_messages = []
    for message in messages:
        if message in seen:
            continue
        seen.add(message)
        deduped_messages.append(message)

    return payload, deduped_messages
