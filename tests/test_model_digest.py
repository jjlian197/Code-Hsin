"""文件授权等待、取消和读取错误不能阻塞或污染当前模型。"""
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtCore import QCoreApplication, QTimer

from src.core.model_digest import ModelDigestLoader
# Qt WebEngine must load before this fixture creates QCoreApplication, as in app startup.
from src.core.pmx_view import PmxView


class ModelDigestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self.loader = ModelDigestLoader()
        self.completions: list[tuple[int, str, str]] = []
        self.loader.finished.connect(lambda *values: self.completions.append(values))

    def tearDown(self) -> None:
        self.loader.close()

    def pump_until(self, predicate, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate(), "Qt completion did not arrive")

    def test_digest_and_read_failure(self) -> None:
        with TemporaryDirectory() as directory:
            model_path = Path(directory) / "中文模型.pmx"
            model_bytes = b"PMX test" * 200000
            model_path.write_bytes(model_bytes)
            self.loader.request(1, model_path)
            self.pump_until(lambda: len(self.completions) == 1)
            self.assertEqual(self.completions[0], (1, hashlib.sha256(model_bytes).hexdigest(), ""))
            self.loader.request(2, model_path.with_name("missing.pmx"))
            self.pump_until(lambda: len(self.completions) == 2)
            self.assertEqual(self.completions[1][:2], (2, ""))
            self.assertIn("模型无法读取", self.completions[1][2])

    def test_blocked_read_keeps_event_loop_live_and_cancels_old_request(self) -> None:
        entered = Event()
        release = Event()
        returned = Event()
        timer_fired = Event()

        def delayed_digest(model_path: Path, cancelled: Event) -> str:
            if model_path.name == "old.pmx":
                entered.set()
                release.wait(2)
                returned.set()
                return "old hash"
            return "new hash"

        with patch("src.core.model_digest.read_model_digest", side_effect=delayed_digest):
            try:
                self.loader.request(1, Path("old.pmx"))
                self.assertTrue(entered.wait(1))
                QTimer.singleShot(0, timer_fired.set)
                self.pump_until(timer_fired.is_set)
                self.loader.request(2, Path("new.pmx"))
                self.pump_until(lambda: bool(self.completions))
                release.set()
                self.assertTrue(returned.wait(1))
                self.application.processEvents()
                self.assertEqual(self.completions, [(2, "new hash", "")])
            finally:
                release.set()

    def test_close_discards_pending_result(self) -> None:
        release = Event()
        returned = Event()

        def delayed_digest(model_path: Path, cancelled: Event) -> str:
            release.wait(2)
            returned.set()
            return "closed hash"

        with patch("src.core.model_digest.read_model_digest", side_effect=delayed_digest):
            try:
                self.loader.request(1, Path("closed.pmx"))
                self.loader.close()
                release.set()
                self.assertTrue(returned.wait(1))
                self.application.processEvents()
                self.assertEqual(self.completions, [])
            finally:
                release.set()

    def test_view_rejects_stale_closed_and_timed_out_completions(self) -> None:
        viewer = SimpleNamespace(_closed=False, _request_id=2, load_error=None,
                                 model_path=Path("current.pmx"),
                                 _load_verified_model=Mock(), _model_result=Mock())
        PmxView._digest_ready(viewer, 1, "stale hash", "")
        viewer._closed = True
        PmxView._digest_ready(viewer, 2, "closed hash", "")
        viewer._closed = False
        viewer.load_error = "timeout"
        PmxView._digest_ready(viewer, 2, "late hash", "")
        viewer._load_verified_model.assert_not_called()
        viewer._model_result.assert_not_called()
        viewer.load_error = None
        PmxView._digest_ready(viewer, 2, "current hash", "")
        viewer._load_verified_model.assert_called_once_with(viewer.model_path, "current hash")


if __name__ == "__main__":
    unittest.main()
