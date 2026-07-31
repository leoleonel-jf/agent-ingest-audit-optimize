"""Adapter loading, validation, and anchor-root resolution.

An adapter is data: which anchors a client keeps its configuration under,
which files to probe beneath them, and which key names carry secrets. Spec
`docs/specs/2026-07-30-adapters-and-scan.md` section 3.2 owns the format;
`assets/schemas/adapter.schema.json` documents it for humans and external
tools, and `validate_adapter` below is what actually runs -- the bundle has
no JSON Schema library and never grows one. The two are held together by
`SchemaAgreementTests`, which compares them in both directions.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

from ledgerlib.constants import (
    ANCHOR_NAME,
    BASELINE_ITEM_KINDS,
    DATE,
    ORDERED_RESOLUTION_MODES,
    RESOLUTION_MODES,
)
from ledgerlib.errors import (
    LedgerError,
    PathSafetyError,
)
from ledgerlib.paths import check_glob, load_json


CLIENT_NAME = re.compile(r"^[a-z0-9-]+$")

REQUIRED_ADAPTER_FIELDS = {
    "adapter_version",
    "client",
    "expires_on",
    "anchors",
    "probes",
    "sensitive_key_patterns",
}
# The known set is the required set plus `resolution`, the one optional
# top-level field: an adapter written before the field existed stays valid,
# and its absence means every kind is undeclared, which `drift` reports
# rather than guessing. The two sets stay separate because the schema states
# them separately (`required` and `properties`), and the agreement test
# compares each against its own counterpart.
ADAPTER_FIELDS = REQUIRED_ADAPTER_FIELDS | {"resolution"}

REQUIRED_PROBE_FIELDS = {"kind"}
PROBE_FIELDS = {"kind", "scope", "glob", "path", "parse", "pointer", "lockable"}
PARSE_FORMATS = {"json", "toml"}

REQUIRED_RESOLUTION_FIELDS = {"mode"}
RESOLUTION_FIELDS = {"mode", "order"}

ENV_CANDIDATE_PREFIX = "$env:"

# `$platform:<sys>:<path>` -- a candidate that applies only where
# `sys.platform` starts with `<sys>`. The prefix match is what makes `linux`
# cover WSL and the historical `linux2` without enumerating either.
#
# This exists because managed policy lives at a different absolute path on
# every platform, and because an anchor with no applicable candidate is a
# different answer from one that resolved to nothing: `/etc/codex` on Windows
# is not an absence anybody verified, it is a concept the platform does not
# have. `platform_excluded_anchors` is what turns that distinction into data.
PLATFORM_CANDIDATE_PREFIX = "$platform:"

# The client selected when detection finds no single answer. Looked up in the
# candidate index by this name rather than opened as `generic.json` directly,
# so a user adapter declaring `generic` overrides the bundled one the same way
# every other client does.
GENERIC_CLIENT = "generic"

# The anchor detection reads. Bare, because that is the key space
# `resolve_anchor_roots` returns.
USER_CONFIG_ANCHOR = "USER_CONFIG"

# Where a user adapter lives beneath the directory `--user-config` names.
# Design spec section 9 fixes this path and `SKILL.md` writes `local.json`
# into it; the tuple is joined rather than written as a string so it is one
# path on every platform.
USER_ADAPTER_DIRECTORY = ("agent-ingest-audit-optimize", "adapters")

USER_ADAPTERS_SKIPPED_NOTE = (
    "user adapters were not read: no --user-config was given"
)

# Why an adapter was chosen, as data. The notes below stay the human-readable
# record and are what reaches stderr; these are what a caller branches on.
# `docs/validation/scan-dogfood-0.2.5.md` finding 1 is the reason they exist:
# `scan` has to tell "generic because the operator asked for generic" from
# "generic because detection gave up", the first being an answer and the second
# being a scan that covered nothing, and no amount of string-matching on a note
# is a safe way to do that.
SELECTED_BY_ADAPTER_FILE = "adapter_file"
SELECTED_BY_CLIENT_NAME = "client_name"
SELECTED_BY_DETECTION = "detected"
SELECTED_BY_AMBIGUOUS_FALLBACK = "ambiguous_detection_fallback"
SELECTED_BY_NO_DETECTION_FALLBACK = "no_detection_fallback"

SELECTION_REASONS = frozenset(
    {
        SELECTED_BY_ADAPTER_FILE,
        SELECTED_BY_CLIENT_NAME,
        SELECTED_BY_DETECTION,
        SELECTED_BY_AMBIGUOUS_FALLBACK,
        SELECTED_BY_NO_DETECTION_FALLBACK,
    }
)

# The two reasons that mean nothing chose this adapter: detection declined to
# answer and `generic` was the floor. Grouped here rather than tested for one
# at a time so a sixth fallback added later is covered by every caller that
# already asks this question.
FALLBACK_SELECTION_REASONS = frozenset(
    {SELECTED_BY_AMBIGUOUS_FALLBACK, SELECTED_BY_NO_DETECTION_FALLBACK}
)

# Which directory the chosen adapter came from. Deliberately NOT a sixth
# reason: a user adapter can be reached by any of the five above, and folding
# "the user overrode this one" into `reason` would make a fallback invisible
# the moment a user adapter was in the index -- which is exactly the case the
# fallback finding exists to catch.
ORIGIN_ADAPTER_FILE = "file"
ORIGIN_BUNDLED = "bundled"
ORIGIN_USER = "user"


def validate_adapter(data: dict, *, source: str) -> list[str]:
    """Collect every finding an adapter document produces.

    Follows `validate_ledger`'s shape exactly: findings are collected and
    returned, nothing is raised for bad content, and every message that
    interpolates adapter content uses `!r`. `load_adapter` is the one place
    that turns findings into an exception, because a caller holding a broken
    adapter has nothing to proceed with.
    """
    if not isinstance(data, dict):
        return [f"{source}: adapter must be a JSON object"]

    findings: list[str] = []
    missing = REQUIRED_ADAPTER_FIELDS - set(data)
    unknown = set(data) - ADAPTER_FIELDS
    if missing:
        findings.append(f"{source}: missing fields: {sorted(missing)}")
    if unknown:
        findings.append(f"{source}: unknown fields: {sorted(unknown)}")
    if missing:
        return findings

    # `type(x) is not int` rather than isinstance, for the same reason
    # `validate_ledger` does it: bool is a subclass of int, and `True` would
    # otherwise pass as a valid version number.
    if type(data["adapter_version"]) is not int or data["adapter_version"] < 1:
        findings.append(f"{source}: adapter_version must be an integer of at least 1")

    client = data["client"]
    if not isinstance(client, str) or not client:
        findings.append(f"{source}: client must be a non-empty string")
    elif not CLIENT_NAME.fullmatch(client):
        # A separate message from the empty case on purpose: an uppercase or
        # spaced name is a naming mistake, not a missing value, and the two
        # are fixed differently.
        findings.append(f"{source}: client must match [a-z0-9-]+: {client!r}")

    expires_on = data["expires_on"]
    if not isinstance(expires_on, str) or not DATE.fullmatch(expires_on):
        findings.append(f"{source}: expires_on must match YYYY-MM-DD")

    findings.extend(_validate_anchors(data["anchors"], source=source))

    probes = data["probes"]
    if not isinstance(probes, list):
        findings.append(f"{source}: probes must be an array")
    else:
        for index, probe in enumerate(probes):
            findings.extend(_validate_probe(probe, index, source=source))

    patterns = data["sensitive_key_patterns"]
    if not isinstance(patterns, list):
        findings.append(f"{source}: sensitive_key_patterns must be an array")
    else:
        for index, pattern in enumerate(patterns):
            if not isinstance(pattern, str) or not pattern:
                findings.append(
                    f"{source}: sensitive_key_patterns[{index}] must be a "
                    f"non-empty string: {pattern!r}"
                )

    # `in` rather than `.get`, so an explicit `"resolution": null` is refused
    # as a non-object instead of passing as an absence.
    if "resolution" in data:
        findings.extend(
            _validate_resolution(
                data["resolution"],
                probes if isinstance(probes, list) else [],
                source=source,
            )
        )

    return findings


def _validate_anchors(anchors: object, *, source: str) -> list[str]:
    if not isinstance(anchors, dict):
        return [f"{source}: anchors must be an object"]

    findings: list[str] = []
    for name, candidates in anchors.items():
        # The stored form is `$NAME`; `ANCHOR_NAME` owns the grammar of what
        # follows the `$`, and is imported rather than restated so an anchor
        # name this file accepts is one `resolve_anchored` can parse back.
        if (
            not isinstance(name, str)
            or not name.startswith("$")
            or not ANCHOR_NAME.fullmatch(name[1:])
        ):
            findings.append(f"{source}: anchors has an invalid anchor name: {name!r}")
            continue
        if not isinstance(candidates, list) or not candidates:
            findings.append(
                f"{source}: anchors.{name} must be a non-empty array of candidates"
            )
            continue
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, str) or not candidate:
                findings.append(
                    f"{source}: anchors.{name}[{index}] must be a "
                    f"non-empty string: {candidate!r}"
                )
            elif (
                candidate.startswith(PLATFORM_CANDIDATE_PREFIX)
                and _split_platform_candidate(candidate) is None
            ):
                # Refused rather than skipped: a typo in a guard would
                # otherwise make its anchor quietly non-applicable, and the
                # whole layer beneath it quietly missing from the baseline --
                # which reads exactly like a clean layer.
                findings.append(
                    f"{source}: anchors.{name}[{index}] is a malformed "
                    f"$platform: candidate, expected "
                    f"$platform:<system>:<path>: {candidate!r}"
                )
    return findings


def _validate_probe(probe: object, index: int, *, source: str) -> list[str]:
    label = f"{source}: probes[{index}]"
    if not isinstance(probe, dict):
        return [f"{label} must be an object"]
    # `lockable` (0.7.0) marks a probe whose items belong in `agent.lock`.
    # Optional and false by omission, so every adapter written before it stays
    # valid; strictly boolean, because a truthy string here would silently
    # pin a kind nobody meant to pin.
    if "lockable" in probe and not isinstance(probe["lockable"], bool):
        return [f"{label} lockable must be a boolean: {probe['lockable']!r}"]

    missing = REQUIRED_PROBE_FIELDS - set(probe)
    if missing:
        return [f"{label} missing fields: {sorted(missing)}"]
    unknown = set(probe) - PROBE_FIELDS
    if unknown:
        return [f"{label} has unknown fields: {sorted(unknown)}"]

    findings: list[str] = []
    kind = probe["kind"]
    if not isinstance(kind, str) or kind not in BASELINE_ITEM_KINDS:
        findings.append(f"{label} has an invalid kind: {kind!r}")

    has_glob = "glob" in probe
    has_path = "path" in probe
    if has_glob and has_path:
        findings.append(f"{label} must have exactly one of glob or path: it has both")
    elif not has_glob and not has_path:
        findings.append(f"{label} must have exactly one of glob or path: it has neither")

    # Both fields go through `check_glob`, at LOAD time. A `..` segment or an
    # absolute form is refused here, before any anchor has been resolved and
    # long before anything is expanded, so a hostile adapter cannot get one
    # directory walk out of the tool. This says nothing about what the
    # filesystem holds at scan time -- `resolve_anchored` per opened path is
    # the other half, and neither replaces the other.
    for field in ("glob", "path"):
        if field in probe:
            try:
                check_glob(probe[field])
            except PathSafetyError as exc:
                findings.append(
                    f"{label} {field} is refused by check_glob [{exc.reason}]: {exc}"
                )

    if "scope" in probe:
        scope = probe["scope"]
        if not isinstance(scope, str) or not scope.strip():
            findings.append(f"{label} scope must be a non-empty string: {scope!r}")

    if "parse" in probe:
        parse = probe["parse"]
        if not isinstance(parse, str) or parse not in PARSE_FORMATS:
            findings.append(f"{label} has an invalid parse: {parse!r}")
        if has_glob and not has_path:
            # Parsing is per-document. A glob yields many documents and the
            # probe names one pointer, so the pairing has no meaning to honour.
            findings.append(f"{label} parse requires path, not glob")

    if "pointer" in probe:
        pointer = probe["pointer"]
        if "parse" not in probe:
            findings.append(f"{label} pointer requires parse")
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            findings.append(f"{label} pointer must start with '/': {pointer!r}")

    return findings


def _validate_resolution(
    resolution: object, probes: list, *, source: str
) -> list[str]:
    """Spec `docs/specs/2026-07-30-drift-and-rollback-preview.md` section 3.1.

    An `order` must name exactly the scopes the probes of its kind declare:
    an ordering that cannot rank every item it will meet is refused here,
    when the author can still fix it, not at drift time.
    """
    if not isinstance(resolution, dict):
        return [f"{source}: resolution must be an object"]

    findings: list[str] = []
    for kind, rule in resolution.items():
        if not isinstance(kind, str) or kind not in BASELINE_ITEM_KINDS:
            findings.append(f"{source}: resolution has an invalid kind: {kind!r}")
            continue
        label = f"{source}: resolution[{kind!r}]"
        if not isinstance(rule, dict):
            findings.append(f"{label} must be an object")
            continue
        missing = REQUIRED_RESOLUTION_FIELDS - set(rule)
        if missing:
            findings.append(f"{label} missing fields: {sorted(missing)}")
            continue
        unknown = set(rule) - RESOLUTION_FIELDS
        if unknown:
            findings.append(f"{label} has unknown fields: {sorted(unknown)}")
            continue
        mode = rule["mode"]
        if not isinstance(mode, str) or mode not in RESOLUTION_MODES:
            # A refusal, not a skip: a mode nobody recognises would otherwise
            # ship a declaration `drift` silently ignores.
            findings.append(f"{label} has an invalid mode: {mode!r}")
            continue
        if mode in ORDERED_RESOLUTION_MODES:
            if "order" not in rule:
                findings.append(f"{label} mode {mode!r} requires order")
                continue
            findings.extend(
                _validate_resolution_order(rule["order"], kind, probes, label=label)
            )
        elif "order" in rule:
            # `merge` and `concatenate` deny that a ranking exists; an order
            # carried anyway would claim a precedence the mode itself denies.
            findings.append(f"{label} mode {mode!r} forbids order")
    return findings


def _validate_resolution_order(
    order: object, kind: str, probes: list, *, label: str
) -> list[str]:
    if (
        not isinstance(order, list)
        or not order
        or not all(isinstance(scope, str) and scope for scope in order)
    ):
        return [f"{label} order must be a non-empty array of scope names: {order!r}"]

    findings: list[str] = []
    seen: set[str] = set()
    for scope in order:
        if scope in seen:
            findings.append(f"{label} order repeats a scope: {scope!r}")
        seen.add(scope)

    declared = _declared_scopes(kind, probes)
    for scope in order:
        if scope not in declared:
            findings.append(
                f"{label} order names a scope no {kind} probe declares: {scope!r}"
            )
    for scope in sorted(declared - seen):
        findings.append(
            f"{label} order omits a scope {kind} probes declare: {scope!r}"
        )
    return findings


def _declared_scopes(kind: str, probes: list) -> set[str]:
    """The scopes probes of `kind` declare.

    A probe too malformed to read is `_validate_probe`'s finding already;
    counting it here would report the same defect twice.
    """
    return {
        probe["scope"]
        for probe in probes
        if isinstance(probe, dict)
        and probe.get("kind") == kind
        and isinstance(probe.get("scope"), str)
        and probe["scope"].strip()
    }


def load_adapter(path: Path) -> dict:
    """Read and validate an adapter, raising on any finding.

    Unlike a ledger, whose findings are reported and counted, an adapter with
    a finding is unusable: every probe under it is suspect, and continuing
    would produce a baseline that looks clean because it scanned nothing.
    """
    data = load_json(path)
    findings = validate_adapter(data, source=str(path))
    if findings:
        raise LedgerError("\n".join(findings))
    return data


def _split_platform_candidate(candidate: str) -> tuple[str, str] | None:
    """`$platform:win32:C:/x` -> `("win32", "C:/x")`, or None if malformed.

    Split on the FIRST colon after the prefix and nowhere else: a Windows
    candidate carries a drive colon of its own, and a greedy split would take
    the drive letter off every path it parses.
    """
    rest = candidate[len(PLATFORM_CANDIDATE_PREFIX) :]
    system, separator, path = rest.partition(":")
    if not separator or not system or not path:
        return None
    return system, path


def platform_excluded_anchors(
    adapter: dict, *, platform: str | None = None
) -> frozenset[str]:
    """The bare names of anchors this platform has no candidate for.

    An anchor is excluded when it has candidates and EVERY one of them is
    guarded by a platform that does not match. One unguarded candidate -- or
    one guard that matches -- keeps the anchor applicable, even if nothing
    resolves: applicable-and-absent is a verified absence, and a probe beneath
    it is honestly `not_present`. Only the fully excluded case is skipped.

    Pure: no filesystem, no environment. It answers a question about the
    adapter and `sys.platform`, which is why it is separate from
    `resolve_anchor_roots` rather than another return value from it.
    """
    system = sys.platform if platform is None else platform
    anchors = adapter.get("anchors")
    if not isinstance(anchors, dict):
        return frozenset()

    excluded: set[str] = set()
    for name, candidates in anchors.items():
        if not isinstance(name, str) or not name.startswith("$"):
            continue
        if not isinstance(candidates, list) or not candidates:
            continue
        applicable = False
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate:
                continue
            if not candidate.startswith(PLATFORM_CANDIDATE_PREFIX):
                applicable = True
                break
            split = _split_platform_candidate(candidate)
            # A malformed guard is refused by `validate_adapter`, so reaching
            # one here means an unvalidated document. Treat it as applicable:
            # a typo must not silently empty a whole layer of the baseline.
            if split is None or system.startswith(split[0]):
                applicable = True
                break
        if not applicable:
            excluded.add(name[1:])
    return frozenset(excluded)


def resolve_anchor_roots(
    adapter: dict, *, project: Path, environ: Mapping[str, str],
    platform: str | None = None
) -> tuple[dict[str, Path], list[str]]:
    """Resolve each anchor to the first candidate that is an existing directory.

    Returns the resolved roots and the names of the anchors that resolved to
    nothing. Both use the anchor's BARE name -- `USER_CONFIG`, not
    `$USER_CONFIG` -- because that is the key space `anchor_path` and
    `resolve_anchored` require: `_validate_anchor_names` refuses a key that
    is not `[A-Z_]+`, and `ANCHOR_REFERENCE` parses `$USER_CONFIG/x` back to
    exactly that bare name. One key space, used by both directions.

    `environ` is a parameter rather than a read of `os.environ` so a caller --
    and every test -- can supply an environment without mutating the process.

    An unresolved anchor is absent from the mapping rather than mapped to a
    guess. `scan` records every probe beneath it as `not_present`; the
    alternative, defaulting to the vendor's documented root, is precisely the
    failure `docs/research/2026-07-30-client-configuration-paths.md` section 1
    warns about -- `CLAUDE_CONFIG_DIR` and `CODEX_HOME` relocate everything,
    and an adapter that scans the default tree anyway reports a clean baseline
    for a configuration it never looked at.

    Roots are returned absolute and resolved because that is what the path
    layer expects: `anchor_path` matches a resolved path against them with
    `relative_to`, which compares components literally.
    """
    anchors = adapter.get("anchors")
    if not isinstance(anchors, dict):
        return {}, []

    base = _safe_resolve(project)
    roots: dict[str, Path] = {}
    unresolved: list[str] = []
    for name, candidates in anchors.items():
        bare = name[1:] if isinstance(name, str) and name.startswith("$") else name
        root = _first_existing_directory(
            candidates, project=base, environ=environ, platform=platform
        )
        if root is None:
            unresolved.append(bare)
        else:
            roots[bare] = root
    return roots, unresolved


def _first_existing_directory(
    candidates: object, *, project: Path | None, environ: Mapping[str, str],
    platform: str | None = None
) -> Path | None:
    if not isinstance(candidates, list):
        return None
    system = sys.platform if platform is None else platform
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            continue
        if candidate.startswith(PLATFORM_CANDIDATE_PREFIX):
            split = _split_platform_candidate(candidate)
            if split is None:
                continue
            guard, path = split
            # Textual, and before any filesystem call: statting a path that
            # belongs to another platform is at best wasted and at worst
            # blocking, and the answer is already known from the string.
            if not system.startswith(guard):
                continue
            resolved = _candidate_path(path, project=project)
        elif candidate.startswith(ENV_CANDIDATE_PREFIX):
            # Unset and empty are the same thing here. An empty variable is
            # what a shell leaves behind after `export CLAUDE_CONFIG_DIR=`,
            # and treating it as a root would resolve to the process's
            # working directory.
            value = environ.get(candidate[len(ENV_CANDIDATE_PREFIX) :], "")
            if not value:
                continue
            resolved = _candidate_path(value, project=project)
        else:
            resolved = _candidate_path(candidate, project=project)
        if resolved is None:
            continue
        try:
            # A candidate that exists but is a file does not qualify: an
            # anchor root is a directory, and joining a probe's tail onto a
            # file would produce paths that can never resolve.
            if resolved.is_dir():
                return resolved
        except (OSError, ValueError):
            continue
    return None


def _candidate_path(candidate: str, *, project: Path | None) -> Path | None:
    """Expand `~`, anchor a relative candidate at `project`, and resolve."""
    try:
        path = Path(candidate).expanduser()
    except (OSError, ValueError, RuntimeError):
        # `expanduser` raises RuntimeError when `~` cannot be resolved to a
        # home directory at all. A candidate that cannot be expanded is a
        # candidate that does not qualify, not a reason to abandon the anchor.
        return None
    if not path.is_absolute() and project is not None:
        # `.` -- and any other relative candidate -- resolves against the
        # `project` argument, never the process working directory. `scan` may
        # be invoked from anywhere; the tree it reports on is the one the
        # caller named.
        path = project / path
    return _safe_resolve(path)


def _safe_resolve(path: Path) -> Path | None:
    try:
        return path.resolve()
    except (OSError, ValueError, RuntimeError):
        # Same failure set `paths._resolve_or_raise` converts: a NUL byte, a
        # trailing-dot segment on Windows, a POSIX symlink loop. Here it means
        # "this candidate does not qualify", so it is swallowed rather than
        # raised -- resolving an anchor root is a survey, not an access.
        return None


class _Candidate(NamedTuple):
    """One adapter the selector may choose, and where it came from."""

    client: str
    path: Path
    data: dict
    origin: str  # ORIGIN_BUNDLED or ORIGIN_USER


def select_adapter(
    *,
    client: str | None,
    adapter: Path | None,
    user_config: Path | None,
    bundled: Path,
    environ: Mapping[str, str],
    project: Path,
) -> tuple[dict, list[str]]:
    """The chosen adapter document and the notes explaining the choice.

    The original two-value shape, kept because it is what a caller that only
    wants to run the adapter needs and because every existing caller and test
    speaks it. It is `select_adapter_detail`'s `document` and `notes`; a
    caller that has to *branch* on why the choice was made -- `scan` does --
    calls that function instead, so the two can never disagree.
    """
    selection = select_adapter_detail(
        client=client,
        adapter=adapter,
        user_config=user_config,
        bundled=bundled,
        environ=environ,
        project=project,
    )
    return selection["document"], selection["notes"]


def select_adapter_detail(
    *,
    client: str | None,
    adapter: Path | None,
    user_config: Path | None,
    bundled: Path,
    environ: Mapping[str, str],
    project: Path,
) -> dict:
    """Choose an adapter and explain the choice, in prose and as data.

    Returns a mapping:

    - `document` -- the chosen adapter.
    - `notes` -- plain-string notes, in order. The caller prints these: a
      scan whose coverage depends on which adapter ran must say which one ran
      and why, or a baseline of nothing is indistinguishable from a baseline
      of a clean machine.
    - `client` -- the chosen document's `client`.
    - `path` -- the file it was read from.
    - `reason` -- one of `SELECTION_REASONS`.
    - `origin` -- one of `ORIGIN_ADAPTER_FILE`, `ORIGIN_BUNDLED`,
      `ORIGIN_USER`.
    - `candidates` -- the client names detection weighed, sorted: the ones
      that matched when it detected or tied, the ones it considered when
      nothing matched, and empty when detection never ran. This is what lets
      a caller's message name the clients that tied rather than telling the
      operator only that something did.

    A mapping rather than a `NamedTuple` because it is read by key at three
    call sites and never unpacked positionally, and because a field added
    later must not renumber anything.

    Precedence, highest first:

    1. `adapter` -- an explicit `--adapter FILE`. It wins over everything,
       and neither adapter directory is read at all.
    2. `client` -- an explicit `--client NAME`, resolved against the
       candidate index. A name that is not in the index raises: an explicit
       wrong name is a typo, and answering a typo with `generic.json` scans
       nothing under a name the user never sees.
    3. Detection -- an adapter matches when its `$USER_CONFIG` anchor
       resolves. Exactly one match selects it; two or more, or none, selects
       `generic.json` with a note naming the candidates and the reason.
       Detection never guesses between two plausible clients silently.

    The index is keyed by each document's `client` value, not by its file
    name, and a user adapter beats a bundled one with the same key. `client`
    is the identity the ledger, the notes, and `--client` all use; a file
    name is a place the document happens to sit.

    `user_config=None` means the user-adapter directory is never read -- not
    defaulted to the home directory. The tool cannot know which client's
    configuration root is meant on a machine that may have several, and
    reading a directory the user did not name is exactly what design spec
    section 13.6 exists to prevent.
    """
    if adapter is not None:
        data = load_adapter(adapter)
        return _selection(
            document=data,
            notes=[_selected(adapter, data["client"], "named by --adapter")],
            client=data["client"],
            path=adapter,
            reason=SELECTED_BY_ADAPTER_FILE,
            origin=ORIGIN_ADAPTER_FILE,
        )

    notes: list[str] = []
    index = _index_adapters(bundled=bundled, user_config=user_config, notes=notes)

    if client is not None:
        chosen = index.get(client)
        if chosen is None:
            raise LedgerError(
                f"unknown client {client!r}: the clients available are "
                f"{sorted(index)}; a client that is not one of them needs a "
                "user adapter at <user-config>/"
                + "/".join(USER_ADAPTER_DIRECTORY)
                + "/local.json"
            )
        notes.append(_selected(chosen.path, chosen.client, "named by --client"))
        return _selection(
            document=chosen.data,
            notes=notes,
            client=chosen.client,
            path=chosen.path,
            reason=SELECTED_BY_CLIENT_NAME,
            origin=chosen.origin,
        )

    detectable = sorted(
        candidate.client
        for candidate in index.values()
        if USER_CONFIG_ANCHOR in _anchor_names(candidate.data)
    )
    matched = sorted(
        name
        for name in detectable
        if _user_config_resolves(index[name].data, project=project, environ=environ)
    )
    if len(matched) == 1:
        chosen = index[matched[0]]
        notes.append(
            _selected(chosen.path, chosen.client, "detected: its $USER_CONFIG resolved")
        )
        return _selection(
            document=chosen.data,
            notes=notes,
            client=chosen.client,
            path=chosen.path,
            reason=SELECTED_BY_DETECTION,
            origin=chosen.origin,
            candidates=matched,
        )

    generic = index.get(GENERIC_CLIENT)
    if generic is None:
        raise LedgerError(
            f"no adapter for client {GENERIC_CLIENT!r} in {bundled}: it is what "
            "detection falls back to, so the bundle cannot run without it"
        )
    if matched:
        reason = SELECTED_BY_AMBIGUOUS_FALLBACK
        candidates = matched
        why = (
            f"detection is ambiguous: $USER_CONFIG resolved for {matched}, and "
            "detection never guesses between two plausible clients"
        )
    else:
        reason = SELECTED_BY_NO_DETECTION_FALLBACK
        candidates = detectable
        why = f"no client detected: $USER_CONFIG resolved for none of {detectable}"
    notes.append(_selected(generic.path, generic.client, why))
    return _selection(
        document=generic.data,
        notes=notes,
        client=generic.client,
        path=generic.path,
        reason=reason,
        origin=generic.origin,
        candidates=candidates,
    )


def _selection(
    *,
    document: dict,
    notes: list[str],
    client: str,
    path: Path,
    reason: str,
    origin: str,
    candidates: list[str] | None = None,
) -> dict:
    """Assemble one selection result, so every exit shares one shape.

    Built here rather than written out at each `return` for the reason
    `_item` exists in `scan`: five literals drift, and a caller reading
    `selection["candidates"]` must never have to ask whether this particular
    branch happened to set it.
    """
    return {
        "document": document,
        "notes": notes,
        "client": client,
        "path": path,
        "reason": reason,
        "origin": origin,
        "candidates": list(candidates) if candidates else [],
    }


def _selected(path: Path, client: str, why: str) -> str:
    return f"selected adapter {path} for client {client!r}: {why}"


def _index_adapters(
    *, bundled: Path, user_config: Path | None, notes: list[str]
) -> dict[str, _Candidate]:
    """Key every available adapter by its `client`, user beating bundled.

    Every candidate is loaded and validated here, not lazily when it is
    chosen. A file in either directory that cannot be read, cannot be parsed,
    or does not validate is a refusal, because the alternative is to skip it
    -- and a user adapter that is silently skipped is precisely the broken
    override the user wrote to fix something, routed around instead of
    reported.
    """
    index: dict[str, _Candidate] = {}

    files = _adapter_files(bundled)
    if not files:
        raise LedgerError(f"no adapters found in {bundled}")
    for path in files:
        _add_candidate(index, _read_candidate(path, origin="bundled"), notes=notes)

    if user_config is None:
        notes.append(USER_ADAPTERS_SKIPPED_NOTE)
        return index

    # A `--user-config` that has no adapters directory is the ordinary case
    # on a machine where the user has never written one, so an absent
    # directory yields nothing rather than raising.
    for path in _adapter_files(user_config.joinpath(*USER_ADAPTER_DIRECTORY)):
        _add_candidate(index, _read_candidate(path, origin="user"), notes=notes)
    return index


def _add_candidate(
    index: dict[str, _Candidate], candidate: _Candidate, *, notes: list[str]
) -> None:
    existing = index.get(candidate.client)
    if existing is not None:
        if existing.origin == candidate.origin:
            # Two files in one directory claiming one client. Whichever won
            # would be decided by sort order, and the loser would be invisible
            # -- including to the user who edited it and saw no change.
            raise LedgerError(
                f"two adapters declare client {candidate.client!r}: "
                f"{existing.path} and {candidate.path}"
            )
        notes.append(
            f"user adapter {candidate.path} overrides the bundled adapter for "
            f"client {candidate.client!r} ({existing.path})"
        )
    index[candidate.client] = candidate


def _read_candidate(path: Path, *, origin: str) -> _Candidate:
    data = load_adapter(path)
    # `load_adapter` has already refused anything whose `client` is not a
    # non-empty `[a-z0-9-]+` string, so the key below is always usable.
    return _Candidate(client=data["client"], path=path, data=data, origin=origin)


def _adapter_files(directory: Path) -> list[Path]:
    try:
        return sorted(path for path in directory.glob("*.json") if path.is_file())
    except OSError:
        return []


def _anchor_names(adapter: dict) -> set[str]:
    """The bare anchor names an adapter declares, `$` stripped."""
    anchors = adapter.get("anchors")
    if not isinstance(anchors, dict):
        return set()
    return {
        name[1:] if isinstance(name, str) and name.startswith("$") else name
        for name in anchors
    }


def _user_config_resolves(
    adapter: dict, *, project: Path, environ: Mapping[str, str]
) -> bool:
    """Whether at least one `$USER_CONFIG` candidate is an existing directory.

    Detection reuses `resolve_anchor_roots` rather than re-implementing the
    candidate rules, so an adapter is detected under exactly the conditions
    its probes would later run under -- `$env:` first, `~` expanded, the first
    existing directory wins.
    """
    roots, _ = resolve_anchor_roots(adapter, project=project, environ=environ)
    return USER_CONFIG_ANCHOR in roots
