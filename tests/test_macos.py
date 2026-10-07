"""macOS 用户目录与隔离配置；可在非 macOS 平台执行。"""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.core import app_config
from src.core.user_settings import settings_path


class MacOSConfigTest(unittest.TestCase):
    def test_installed_bundle_keeps_settings_and_runtime_outside_program(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            test_root = Path(directory).resolve()
            program_root = test_root / "Hsin.app/Contents/MacOS"
            program_root.mkdir(parents=True)
            resource_root = test_root / "Hsin.app/Contents/Resources"
            resource_root.mkdir(parents=True)
            config_path = resource_root / "config.yaml"
            config_path.write_text("sprite:\n  renderer: placeholder\n", encoding="utf8")
            support_root = test_root / "Library/Application Support/Hsin"
            support_root.mkdir(parents=True)
            (support_root / "config.local.yaml").write_text("voice:\n  language: ja\n", encoding="utf8")
            with patch.object(app_config, "sys", SimpleNamespace(platform="darwin", frozen=True)), \
                 patch.object(app_config, "PROJECT_ROOT", program_root), \
                 patch.object(app_config, "RESOURCE_ROOT", resource_root), \
                 patch.object(Path, "home", return_value=test_root), \
                 patch.dict(os.environ, {}, clear=True):
                config = app_config.load_config()
                self.assertEqual(app_config.user_data_root(), support_root)
                self.assertEqual(settings_path(config), support_root / "config.local.yaml")
                self.assertEqual(config["runtime"]["directory"], str(support_root / ".runtime"))
                self.assertEqual(config["voice"]["language"], "ja")
                self.assertEqual(app_config.project_path("models/heart.pmx"), support_root / "models/heart.pmx")
                self.assertFalse((program_root / "config.local.yaml").exists())
                self.assertFalse((resource_root / "config.local.yaml").exists())

    def test_explicit_data_directory_wins_and_source_keeps_project_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(app_config, "sys", SimpleNamespace(platform="darwin", frozen=False)), \
             patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(app_config.user_data_root())
            with patch.dict(os.environ, {"HSIN_DATA_DIR": directory}):
                self.assertEqual(app_config.user_data_root(), Path(directory).resolve())
