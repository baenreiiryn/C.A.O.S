import re
import unittest
from pathlib import Path

from caos.version import __version__


class VersionConsistencyTests(unittest.TestCase):
    def test_project_runtime_and_installer_versions_match(self):
        root = Path(__file__).resolve().parents[1]
        pyproject = (
            root / "pyproject.toml"
        ).read_text(encoding="utf-8")
        installer = (
            root / "installer" / "caos.iss"
        ).read_text(encoding="utf-8")

        project_match = re.search(
            r'^version = "([^"]+)"',
            pyproject,
            flags=re.MULTILINE,
        )
        installer_match = re.search(
            r'^#define MyAppVersion "([^"]+)"',
            installer,
            flags=re.MULTILINE,
        )
        self.assertIsNotNone(project_match)
        self.assertIsNotNone(installer_match)
        self.assertEqual(
            project_match.group(1),
            __version__,
        )
        self.assertEqual(
            installer_match.group(1),
            __version__,
        )


if __name__ == "__main__":
    unittest.main()
