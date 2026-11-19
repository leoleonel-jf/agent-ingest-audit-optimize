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
import os
import sys
import tempfile
import webbrowser
from pathlib import Path

from ledgerlib import drift, rollback
from ledgerlib.chain import canonical_text, chain_head, verify_chain
from ledgerlib.constants import TOOL_VERSION
from ledgerlib.errors import LedgerError
from ledgerlib.paths import _path_key, file_digest, load_json
from ledgerlib.validate import validate_collection, validate_ledger


PAYLOAD_SCHEMA = 1

# The bundle's only shell. Design spec section 3 gives `build` no
# `--template` flag, so the layout `assets/scripts/ledgerlib/` ->
# `assets/templates/` is written down exactly once, here, and both the
# command and the shell's own test suite read the same constant: a template
# that moves breaks one import rather than two silent path expressions.
TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "templates" / "dashboard.html"
)

# The data island's id attribute, exactly as it appears in the template
# (design spec section 1.1): `inject_payload` counts and locates it, and
# `write_dashboard`'s overwrite guard tests an existing file for the same
# string to decide whether that file is itself a generated dashboard.
_ISLAND_MARKER = 'id="aio-payload"'

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
    # `canonical_text` is the one canonicalization in the repository -- sorted
    # keys, compact separators, surrogate-safe -- and this function is that
    # plus the three HTML-embedding escapes it owns. Two canonicalizations
    # would eventually disagree, and a payload disagreeing with a record
    # digest about the same object is worse than either being wrong alone.
    text = canonical_text(payload)
    return (
        text.replace("<", "\\u003c")
        .replace(_LINE_SEPARATOR, "\\u2028")
        .replace(_PARAGRAPH_SEPARATOR, "\\u2029")
    )


def _chain_summary(ledger: dict) -> dict:
    """The chain verdict for the payload: verdict, head, and broken rows only.

    Sound rows are omitted deliberately. A page that listed every intact link
    would bury the two or three that are not, and the verdict already carries
    the "everything is fine" case in one word.
    """
    rows, verdict = verify_chain(ledger)
    return {
        "verdict": verdict,
        "head": chain_head(ledger),
        "broken": [row for row in rows if row["reason"] is not None],
    }


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
            # The chain verdict plus the records that broke it. `head` rides
            # along so a reader can compare it against the digest they
            # recorded outside the ledger without leaving the page -- the page
            # itself cannot do that comparison, because everything it can see
            # came out of the same file.
            "chain": _chain_summary(ledger),
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


def inject_payload(template_text: str, serialized: str) -> str:
    """Splice `serialized` into the template's one `aio-payload` island.

    The replacement is two string searches, never a regex over the whole
    document (design spec section 3): find the marker `id="aio-payload"`,
    then that opening tag's own `>`, then the following `</script`. Only the
    text between those two points changes; the tag itself, and everything
    before and after it, is copied through byte-for-byte. A template with
    zero or more than one island is a template this function refuses to
    guess about -- `LedgerError`, naming the count, rather than splicing the
    first or the last of several candidates.
    """
    count = template_text.count(_ISLAND_MARKER)
    if count != 1:
        raise LedgerError(
            f"the dashboard template must contain exactly one {_ISLAND_MARKER!r} "
            f"island, found {count}"
        )
    marker_at = template_text.index(_ISLAND_MARKER)
    try:
        # `id="aio-payload"` must remain the tag's LAST attribute before this
        # `>`: this scan takes the first `>` after the marker as the tag's
        # close, so a later attribute containing a literal `>` (in a quoted
        # value, say) would end the tag early and corrupt the splice. The
        # mirror of this comment lives on the island tag itself in
        # `assets/templates/dashboard.html`, and `test_shell.py` pins the
        # ordering statically.
        tag_end = template_text.index(">", marker_at) + 1
        content_end = template_text.index("</script", tag_end)
    except ValueError as exc:
        raise LedgerError(
            "the dashboard template's aio-payload island is malformed: no "
            "closing </script found after the marker"
        ) from exc
    if "<" in serialized:
        # Belt and braces: `serialize_payload` is the sole control that keeps
        # a literal `<` out of `serialized` (module docstring, design spec
        # section 1.1), but this function does the actual splicing, so it
        # refuses to trust that upstream guarantee blindly and checks again
        # immediately before it matters.
        raise LedgerError(
            "payload serialization produced a literal '<'; refusing to inject"
        )
    return template_text[:tag_end] + serialized + template_text[content_end:]


def write_dashboard(html: str, out: Path, *, force: bool) -> None:
    """Write `html` to `out`, atomically, refusing to clobber a stray file.

    The overwrite guard (design spec section 3): an existing `out` is left
    alone unless it already looks like a generated dashboard -- it contains
    the `aio-payload` marker -- or the caller passed `force=True`. This is
    the first ledger-adjacent write command in the bundle, so the guard is
    the only thing standing between a typo'd `--out` and a file that had
    nothing to do with this tool.

    The write itself goes through a temporary file created in `out`'s own
    directory, then `os.replace`. `os.replace` is what this guarantees: a
    reader never observes a partially written dashboard, because the rename
    is the one step that makes the new content visible and it either
    happens wholly or not at all. Whether that rename itself survives a
    concurrent crash or power loss is the filesystem's affair, not a promise
    this function makes. `out`'s directory is never created -- a missing
    parent is a caller error, not something this function silently repairs
    -- and on any failure the temporary file is removed on a best-effort
    basis before the exception propagates, so a failed build leaves no
    stray `.tmp` file behind.
    """
    if out.exists() and not force:
        try:
            # Bytes, not text: an existing `out` that happens to hold
            # non-UTF-8 content (a stray binary file at that path, say) must
            # not crash the overwrite guard with a `UnicodeDecodeError` --
            # it is exactly the kind of file this guard exists to protect.
            existing = out.read_bytes()
        except OSError as exc:
            raise LedgerError(
                f"cannot read existing file {str(out)!r} to check the "
                f"overwrite guard: {exc}"
            ) from exc
        if _ISLAND_MARKER.encode("utf-8") not in existing:
            raise LedgerError(
                f"refusing to overwrite {str(out)!r}: it does not look like a "
                "generated dashboard (no aio-payload marker); pass --force to "
                "overwrite it anyway"
            )

    fd, tmp_name = tempfile.mkstemp(
        dir=str(out.parent), prefix=out.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(html)
        os.replace(tmp_path, out)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _open_url(url: str) -> bool:
    """Hand `url` to the platform's default browser.

    A one-line wrapper so that `_open_after_write` has a module attribute to
    reach through rather than a name bound at import time: a test replaces
    `build._open_url` exactly the way `rollback` replaces `classify_target`,
    and no test opens a browser.
    """
    return webbrowser.open(url)


def _open_after_write(out: Path) -> None:
    """Show the dashboard just written, and never fail the build for it.

    `--open` is a courtesy, not a deliverable: by the time this runs the file
    is on disk, which was the command's job. Turning a written dashboard into
    a failing exit code because no browser answered would make the flag
    unusable in exactly the environments this bundle is shaped for -- a CI
    runner has no display, and `webbrowser.open` there returns `False` at
    best and raises at worst.

    So both outcomes become one note on stderr, never stdout: `scan_command`
    fixed that contract for the bundle -- stdout carries the answer and
    nothing else. `BaseException` is deliberately not caught; a
    `KeyboardInterrupt` during the launch is still the operator's word.
    """
    try:
        opened = _open_url(out.resolve().as_uri())
    except Exception as exc:
        # Deliberately broad. `webbrowser` raises `webbrowser.Error` when it
        # knows it failed, but the launchers underneath it are platform code
        # that can surface an `OSError` instead, and the whole point of this
        # function is that no failure here reaches the exit code.
        print(f"could not open {str(out)!r} in a browser: {exc}", file=sys.stderr)
        return
    if not opened:
        print(
            f"could not open {str(out)!r}: no browser is available here",
            file=sys.stderr,
        )


def build_command(
    ledger: Path,
    out: Path | None,
    lang: str | None,
    force: bool,
    adapter: Path | None = None,
    user_config: Path | None = None,
    project: Path | None = None,
    open_after: bool = False,
) -> int:
    """`build` as a command: assemble the payload, inject it, write the file.

    Exit codes (design spec section 3, mirroring `verify`'s split between a
    tool error and a finding): `0` once the file is written -- even when
    `computed.drift` or a preview reports problems, because the dashboard's
    job is to render those problems, not to refuse them; `1` for an
    unreadable ledger or a write refusal (the overwrite guard, or any other
    I/O failure); `2` for a ledger `verify` would reject, in which case
    nothing is written.

    The adjudicated reading of design spec section 2 governs the `2` case:
    there is no `computed.verify` key, so `build_command` itself runs
    `verify`'s two checks -- `validate_ledger` and the single-document
    `validate_collection(..., complete=True)`, exactly as `verify()` in
    `ledgerlib/verify.py` does for a list of one -- before calling
    `build_payload` at all. Any finding from either check is printed to
    stderr and the build stops there. `build_payload` also calls
    `validate_ledger` internally (its own docstring explains why: it must
    never compute anything for a ledger nothing vouched for), but by the
    time it runs here the document has already passed both checks, so that
    second call finds nothing and prints nothing -- one set of findings
    reaches stderr, never two.
    """
    try:
        document = load_json(ledger)
        digest = file_digest(ledger)
    except LedgerError as exc:
        print(exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Unreadable ledger: {ledger}: {exc}", file=sys.stderr)
        return 1

    source = str(ledger)
    findings = validate_ledger(document, source=source)
    digests = {
        _path_key(source): digest,
        _path_key(str(ledger.resolve())): digest,
    }
    findings.extend(
        validate_collection([(source, document)], complete=True, digests=digests)
    )
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        return 2

    out_path = out if out is not None else ledger.parent / "dashboard.html"

    try:
        payload, messages = build_payload(
            document,
            ledger_source=source,
            lang=lang,
            adapter=adapter,
            user_config=user_config,
            project=project,
        )
    except LedgerError as exc:
        # Not reachable through the checks above for any ledger this
        # function already validated whole; kept as a tool error rather than
        # an assertion because a second, differently worded validator living
        # inside `build_payload` is exactly the kind of drift design spec
        # section 2 rules out.
        print(exc, file=sys.stderr)
        return 2

    for message in messages:
        print(message, file=sys.stderr)

    serialized = serialize_payload(payload)
    try:
        template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
        html = inject_payload(template_text, serialized)
    except LedgerError as exc:
        print(exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print(
            f"cannot read the dashboard template {str(TEMPLATE_PATH)!r}: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        write_dashboard(html, out_path, force=force)
    except LedgerError as exc:
        print(exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"cannot write {str(out_path)!r}: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {out_path}")
    # After the write and only after it: every `return` above this line left
    # nothing on disk to show.
    if open_after:
        _open_after_write(out_path)
    return 0
