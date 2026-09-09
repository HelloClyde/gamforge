"""Full-bundle dependency resolution without relying on a developer profile."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from a9288 import paths


class PortableTest(unittest.TestCase):
    def test_frozen_bundle_moves_and_explicit_override_wins(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "中文 folder"
            (folder / "dependencies").mkdir(parents=True)
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(folder / "A9288-CLI.exe")),
                patch.dict(os.environ, {}, clear=True),
            ):
                self.assertEqual(paths.dependency_root(), (folder / "dependencies").resolve())
                with patch.dict(os.environ, {"A9288_DEPENDENCIES": "explicit"}):
                    self.assertEqual(paths.dependency_root(), Path("explicit"))
            with (
                patch.object(sys, "frozen", False, create=True),
                patch.dict(os.environ, {}, clear=True),
            ):
                self.assertEqual(paths.dependency_root(), paths.USER_DATA / "dependencies")

    def test_stale_saved_settings_fall_back_without_overwriting_valid_custom_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            self.assertEqual(paths.dependency_setting(str(folder / "gone"), folder), str(folder))
            self.assertEqual(paths.dependency_setting(None, folder), str(folder))
            self.assertEqual(paths.dependency_setting(str(folder), folder / "default"), str(folder))
