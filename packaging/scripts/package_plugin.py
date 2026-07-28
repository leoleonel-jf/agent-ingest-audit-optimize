#!/usr/bin/env python3
"""Build and verify deterministic plugin and portable Skill archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_MANIFEST = REPO_ROOT / ".codex-plugin" / "plugin.json"
CLAUDE_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
SKILLS_ROOT = REPO_ROOT / "skills"
LICENSE = REPO_ROOT / "LICENSE"
PUBLIC_FILES = tuple(
    REPO_ROOT / name
    for name in (
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        "PRIVACY.md",
        "TERMS.md",
        "SUPPORT.md",
        "SECURITY.md",
    )
)
ASSETS_ROOT = REPO_ROOT / "assets"
DEFAULT_OUTPUT = REPO_ROOT / "dist"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
FRONTMATTER_NAME = re.compile(r"(?m)^name:\s*([A-Za-z0-9_-]+)\s*$")
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class PackagingError(RuntimeError):
    """Raised when the source or a generated archive violates the contract."""


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PackagingError(f"Missing required file: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackagingError(f"Invalid UTF-8 JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PackagingError(f"Expected a JSON object: {path}")
    return value


def validate_sources() -> tuple[str, str, Path]:
    codex = load_json(CODEX_MANIFEST)
    claude = load_json(CLAUDE_MANIFEST)

    names = {codex.get("name"), claude.get("name")}
    versions = {codex.get("version"), claude.get("version")}
    if len(names) != 1 or not all(isinstance(value, str) and value for value in names):
        raise PackagingError("Codex and Claude manifests must use the same non-empty name")
    if len(versions) != 1 or not all(isinstance(value, str) and value for value in versions):
        raise PackagingError("Codex and Claude manifests must use the same non-empty version")

    name = names.pop()
    version = versions.pop()
    if not SEMVER.fullmatch(version):
        raise PackagingError(f"Plugin version is not strict semver: {version}")

    skill_dir = SKILLS_ROOT / name
    skill_file = skill_dir / "SKILL.md"
    try:
        skill_text = skill_file.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PackagingError(f"Missing canonical Skill: {skill_file}") from exc
    except UnicodeDecodeError as exc:
        raise PackagingError(f"SKILL.md is not valid UTF-8: {skill_file}") from exc

    if not skill_text.startswith("---\n"):
        raise PackagingError("SKILL.md must start with YAML front matter")
    match = FRONTMATTER_NAME.search(skill_text)
    if match is None or match.group(1) != name:
        raise PackagingError("SKILL.md front matter name must match both plugin manifests")
    if codex.get("skills") != "./skills/":
        raise PackagingError("Codex manifest must point its skills field to ./skills/")
    for public_file in PUBLIC_FILES:
        if not public_file.is_file():
            raise PackagingError(f"Missing public distribution file: {public_file}")
    if not (ASSETS_ROOT / "logo.png").is_file():
        raise PackagingError(f"Missing plugin logo: {ASSETS_ROOT / 'logo.png'}")

    for path in (
        CODEX_MANIFEST,
        CLAUDE_MANIFEST,
        *PUBLIC_FILES,
        *ASSETS_ROOT.rglob("*"),
        *skill_dir.rglob("*"),
    ):
        if path.is_symlink():
            raise PackagingError(f"Symlinks are not permitted in packages: {path}")

    return name, version, skill_dir


def iter_files(root: Path) -> list[Path]:
    return sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(REPO_ROOT).as_posix(),
    )


def archive_name_is_safe(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def write_archive(destination: Path, entries: Iterable[tuple[Path, str]]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for source, archive_name in sorted(entries, key=lambda item: item[1]):
            if not archive_name_is_safe(archive_name):
                raise PackagingError(f"Unsafe archive path: {archive_name}")
            info = zipfile.ZipInfo(archive_name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644 & 0xFFFF) << 16
            info.create_system = 3
            archive.writestr(info, source.read_bytes())


def expected_entries(name: str, skill_dir: Path) -> tuple[list[tuple[Path, str]], list[tuple[Path, str]]]:
    skill_files = iter_files(skill_dir)
    plugin_entries = [
        (CODEX_MANIFEST, ".codex-plugin/plugin.json"),
        (CLAUDE_MANIFEST, ".claude-plugin/plugin.json"),
    ]
    plugin_entries.extend(
        (path, path.relative_to(REPO_ROOT).as_posix()) for path in PUBLIC_FILES
    )
    plugin_entries.extend(
        (path, path.relative_to(REPO_ROOT).as_posix())
        for path in iter_files(ASSETS_ROOT)
    )
    plugin_entries.extend(
        (path, path.relative_to(REPO_ROOT).as_posix()) for path in skill_files
    )
    skill_entries = [
        (path, f"{name}/{path.relative_to(skill_dir).as_posix()}")
        for path in skill_files
    ]
    skill_entries.append((LICENSE, f"{name}/LICENSE"))
    return plugin_entries, skill_entries


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_paths(output_dir: Path, name: str, version: str) -> tuple[Path, Path]:
    return (
        output_dir / f"{name}-{version}-plugin.zip",
        output_dir / f"{name}-{version}-skill.zip",
    )


def build(output_dir: Path) -> tuple[Path, Path, Path]:
    name, version, skill_dir = validate_sources()
    plugin_entries, skill_entries = expected_entries(name, skill_dir)
    plugin_archive, skill_archive = artifact_paths(output_dir, name, version)

    write_archive(plugin_archive, plugin_entries)
    write_archive(skill_archive, skill_entries)

    checksum_file = output_dir / "SHA256SUMS"
    checksum_text = "".join(
        f"{sha256(path)}  {path.name}\n"
        for path in sorted((plugin_archive, skill_archive), key=lambda item: item.name)
    )
    checksum_file.write_text(checksum_text, encoding="utf-8", newline="\n")
    verify(output_dir)
    return plugin_archive, skill_archive, checksum_file


def verify_archive(path: Path, expected_names: list[str]) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            actual_names = archive.namelist()
            if actual_names != sorted(actual_names):
                raise PackagingError(f"Archive entries are not sorted: {path.name}")
            if len(actual_names) != len(set(actual_names)):
                raise PackagingError(f"Archive contains duplicate paths: {path.name}")
            if any(not archive_name_is_safe(name) for name in actual_names):
                raise PackagingError(f"Archive contains an unsafe path: {path.name}")
            if actual_names != sorted(expected_names):
                raise PackagingError(f"Archive contents do not match the package contract: {path.name}")
            corrupt = archive.testzip()
            if corrupt is not None:
                raise PackagingError(f"Archive contains corrupt data at {corrupt}: {path.name}")
    except FileNotFoundError as exc:
        raise PackagingError(f"Missing generated artifact: {path}") from exc
    except zipfile.BadZipFile as exc:
        raise PackagingError(f"Invalid ZIP archive: {path}") from exc


def verify(output_dir: Path) -> None:
    name, version, skill_dir = validate_sources()
    plugin_entries, skill_entries = expected_entries(name, skill_dir)
    plugin_archive, skill_archive = artifact_paths(output_dir, name, version)

    verify_archive(plugin_archive, [archive_name for _, archive_name in plugin_entries])
    verify_archive(skill_archive, [archive_name for _, archive_name in skill_entries])

    with zipfile.ZipFile(skill_archive) as archive:
        roots = {PurePosixPath(entry).parts[0] for entry in archive.namelist()}
        if roots != {name}:
            raise PackagingError("Portable Skill archive must have exactly one top-level Skill directory")

    checksum_file = output_dir / "SHA256SUMS"
    try:
        checksum_lines = checksum_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise PackagingError(f"Missing checksum file: {checksum_file}") from exc
    expected_checksums = {
        path.name: sha256(path) for path in (plugin_archive, skill_archive)
    }
    actual_checksums: dict[str, str] = {}
    for line in checksum_lines:
        parts = line.split("  ", 1)
        if len(parts) != 2:
            raise PackagingError("Malformed SHA256SUMS entry")
        digest, filename = parts
        actual_checksums[filename] = digest
    if actual_checksums != expected_checksums:
        raise PackagingError("SHA256SUMS does not match generated artifacts")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Artifact directory (default: repository dist/)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    try:
        if args.command == "build":
            artifacts = build(output_dir)
            for artifact in artifacts:
                print(f"BUILT {artifact}")
        else:
            verify(output_dir)
            print(f"VALID {output_dir}")
    except PackagingError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
