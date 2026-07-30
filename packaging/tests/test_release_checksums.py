from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASES_DIR = REPO_ROOT / "docs" / "releases"
PACKAGER = Path("packaging") / "scripts" / "package_plugin.py"

CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  (\S+)$", re.MULTILINE)
RELEASE_DOC = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def parse_checksums(text: str) -> dict[str, str]:
    """Map archive filename -> checksum, exactly as the document pairs them.

    Keyed by filename rather than by line position, so a document that lists the
    right two hashes against swapped filenames is caught rather than shrugged off
    as "the same two values, different order".
    """
    return {filename: digest for digest, filename in CHECKSUM_LINE.findall(text)}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def export_tag(tag: str, destination: Path) -> None:
    """Materialise the tree recorded at `tag` under `destination`.

    `git archive --format=zip` plus `zipfile` rather than a tar pipeline: the
    extraction side is then the standard library on every host, instead of
    depending on which `tar` a Windows machine happens to resolve.
    """
    bundle = destination.parent / f"{tag}.zip"
    result = git("archive", "--format=zip", "--output", str(bundle), tag)
    if result.returncode != 0:
        raise AssertionError(f"git archive {tag} failed: {result.stderr.strip()}")
    with zipfile.ZipFile(bundle) as archive:
        archive.extractall(destination)
    bundle.unlink()


def packages_python_sources(tree: Path) -> bool:
    skills = tree / "skills"
    assets = tree / "assets"
    return any(
        root.is_dir() and any(root.rglob("*.py")) for root in (skills, assets)
    )


def excludes_compiled_bytecode(packager: Path) -> bool:
    return "__pycache__" in packager.read_text(encoding="utf-8")


class ReleaseChecksumTests(unittest.TestCase):
    """Every release document's checksums must match a build of that release's own tag.

    v0.2.3 shipped with checksums computed before a same-commit edit to a file that
    ships inside the archives, so the published values described an archive that was
    never actually built. The build itself was fine; nothing checked the document
    against it. That missing check, not the wrong value, was the defect.

    The first attempt at that check compared the release document for the version
    pinned in `.claude-plugin/plugin.json` against a build of the CURRENT WORKING
    TREE. That was wrong here, because it assumed the version is bumped at the start
    of a development cycle -- so a document for the pinned version implies the tree
    still matches it. This repository bumps the version at the END, in the release
    task: the pin names the version already released, its document already exists,
    and the tree legitimately moves on. The check therefore went red on the first
    commit after every release and stayed red for the whole cycle, masking any real
    packaging regression behind an expected failure.

    What is true at every moment, and never depends on where in a cycle the tree
    sits, is that a published release document describes a build of that release's
    own tagged tree. So each `docs/releases/vX.Y.Z.md` is checked against archives
    rebuilt from the export of tag `vX.Y.Z`, using the packager committed at that
    tag -- the packager is part of what produced those checksums, so the current one
    must not be substituted for it. A document written but not yet tagged is the
    release-in-progress state and skips; it is covered the moment its tag exists.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("git") is None:
            raise unittest.SkipTest(
                "git is not on PATH, so no tagged tree can be exported; this check "
                "compares release documents against builds of their own git tags."
            )
        inside = git("rev-parse", "--is-inside-work-tree")
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            raise unittest.SkipTest(
                f"{REPO_ROOT} is not a git work tree (git rev-parse said: "
                f"{(inside.stderr or inside.stdout).strip()!r}), so release tags "
                "cannot be exported and rebuilt."
            )
        listed = git("tag", "--list")
        if listed.returncode != 0:
            raise unittest.SkipTest(
                f"git tag --list failed ({listed.stderr.strip()}), so the set of "
                "released tags is unknown."
            )
        cls.tags = set(listed.stdout.split())

    def release_documents(self) -> list[Path]:
        return sorted(
            path
            for path in RELEASES_DIR.glob("v*.md")
            if RELEASE_DOC.fullmatch(path.stem)
        )

    def test_release_document_checksums_match_a_build_of_their_tag(self) -> None:
        documents = self.release_documents()
        self.assertTrue(documents, f"No release documents found under {RELEASES_DIR}")

        for release_doc in documents:
            tag = release_doc.stem
            with self.subTest(release=tag):
                if tag not in self.tags:
                    self.skipTest(
                        f"{release_doc.name} has no {tag} tag yet -- the release "
                        "document is written before the tag is pushed, so this is "
                        "the release-in-progress state; it is checked as soon as "
                        f"{tag} exists."
                    )

                documented = parse_checksums(release_doc.read_text(encoding="utf-8"))
                self.assertTrue(
                    documented,
                    f"{release_doc.name} contains no 'sha256  filename' checksum lines",
                )

                with tempfile.TemporaryDirectory(
                    ignore_cleanup_errors=True
                ) as scratch:
                    root = Path(scratch)
                    tree = root / "tree"
                    # Build into scratch, never the repository's dist/, so running
                    # this suite can never mutate or race real release artifacts.
                    output = root / "dist"
                    tree.mkdir()
                    output.mkdir()
                    export_tag(tag, tree)

                    packager = tree / PACKAGER
                    self.assertTrue(
                        packager.is_file(),
                        f"{tag} has no {PACKAGER.as_posix()}, so the archives it "
                        "published cannot be rebuilt from it",
                    )

                    if packages_python_sources(tree) and not excludes_compiled_bytecode(
                        packager
                    ):
                        self.skipTest(
                            f"{tag} ships Python sources but its packager predates "
                            "the __pycache__/.pyc exclusion, so its archives absorbed "
                            "whatever bytecode happened to sit in the release "
                            "builder's working tree -- untracked, interpreter- and "
                            "mtime-dependent state that is absent from the tag. This "
                            "release is not reproducible from its tree by "
                            "construction; the packager fix that made it so landed "
                            "in the following release."
                        )

                    built = self.build(packager, output, tag)

                for filename, real_digest in sorted(built.items()):
                    self.assertIn(
                        filename,
                        documented,
                        f"{release_doc.name} has no checksum line for {filename}",
                    )
                    self.assertEqual(
                        documented[filename],
                        real_digest,
                        f"{release_doc.name} checksum for {filename} does not match "
                        f"a build of tag {tag}",
                    )

    def build(self, packager: Path, output: Path, tag: str) -> dict[str, str]:
        result = subprocess.run(
            [sys.executable, str(packager), "build", "--output-dir", str(output)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"packaging {tag} from its own tree failed:\n"
            f"{result.stdout.strip()}\n{result.stderr.strip()}",
        )
        archives = sorted(output.glob("*.zip"))
        self.assertTrue(
            archives, f"packaging {tag} produced no .zip archives in {output}"
        )
        return {archive.name: sha256(archive) for archive in archives}


if __name__ == "__main__":
    unittest.main()
