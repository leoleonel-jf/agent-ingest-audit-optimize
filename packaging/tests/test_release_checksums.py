from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "package_plugin.py"
SPEC = importlib.util.spec_from_file_location("package_plugin", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
package_plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_plugin)

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
RELEASES_DIR = REPO_ROOT / "docs" / "releases"

CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  (\S+)$", re.MULTILINE)


def parse_checksums(text: str) -> dict[str, str]:
    """Map archive filename -> checksum, exactly as the document pairs them.

    Keyed by filename rather than by line position, so a document that lists the
    right two hashes against swapped filenames is caught rather than shrugged off
    as "the same two values, different order".
    """
    return {filename: digest for digest, filename in CHECKSUM_LINE.findall(text)}


class ReleaseChecksumTests(unittest.TestCase):
    """A release document's checksums must describe a real build of the committed tree.

    v0.2.3 shipped with checksums computed before a same-commit edit to a file that
    ships inside the archives, so the published values described an archive that was
    never actually built. The build itself was fine; nothing checked the document
    against it. That missing check, not the wrong value, was the defect -- so this
    test builds the CURRENT version fresh and compares, rather than trusting either
    the document or a previously recorded digest.
    """

    def test_release_document_checksums_match_a_real_build(self) -> None:
        version = package_plugin.load_json(CLAUDE_MANIFEST)["version"]
        release_doc = RELEASES_DIR / f"v{version}.md"
        if not release_doc.is_file():
            raise AssertionError(
                f"Missing release document for current version {version}: {release_doc}"
            )

        with tempfile.TemporaryDirectory() as temp:
            # Build into a scratch directory -- never the repo's dist/ -- so running
            # this suite can never mutate or race real release artifacts.
            plugin_archive, skill_archive, _ = package_plugin.build(Path(temp))
            expected = {
                plugin_archive.name: package_plugin.sha256(plugin_archive),
                skill_archive.name: package_plugin.sha256(skill_archive),
            }

        documented = parse_checksums(release_doc.read_text(encoding="utf-8"))

        for filename, real_digest in expected.items():
            if filename not in documented:
                raise AssertionError(
                    f"{release_doc.name} has no checksum line for {filename}"
                )
            self.assertEqual(
                documented[filename],
                real_digest,
                f"{release_doc.name} checksum for {filename} does not match a real build",
            )


if __name__ == "__main__":
    unittest.main()
