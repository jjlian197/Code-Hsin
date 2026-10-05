"""验证真实 Qt 窗口、跨线程控制、本机 HTTP/WS 和退出清理。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import threading
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from aiohttp import ClientSession
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QFontMetrics
from PyQt6.QtWidgets import QApplication
import websockets

from src.core.app_config import load_config
from src.core.control_bridge import ControlBridge
from src.core.control_services import ControlServices
from src.core.sprite_window import HsinSpriteWindow


class QtWindowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = load_config()
        self.config["sprite"]["renderer"] = "placeholder"
        # 窗口测试只使用占位渲染器；仓库不分发 PMX，测试也不依赖私有模型。
        model_fixture = Path(self.temp.name) / "model.pmx"
        model_fixture.write_bytes(b"placeholder")
        self.config["sprite"]["model"]["path"] = str(model_fixture)
        self.config["runtime"]["directory"] = self.temp.name
        self.config["voice"]["profiles"] = str(Path(self.temp.name) / "untrained.json")
        self.window = HsinSpriteWindow(self.config)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.cleanup()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.003)

class DesktopTest(QtWindowTestCase):
    def test_view_selection_api_persistence_and_invalid_mode(self):
        from unittest.mock import Mock
        view = self.window.sprite_view
        view.renderer_name = "pmx"
        view.set_view_mode = Mock()
        self.window._view_actions = {}
        bridge = ControlBridge(self.window)
        bridge.dispatch({"type": "window", "data": {"action": "view", "mode": "head_right"}})
        view.set_view_mode.assert_called_with("head_right")
        self.assertEqual(bridge.dispatch({"type": "get_status"})["data"]["window"]["view_mode"], "head_right")
        self.window.view_mode = "full"
        self.window._restore_state()
        self.assertEqual(self.window.view_mode, "head_right")
        self.window._fit_pose_window("side_lying")
        self.window._fit_pose_window("idle")
        self.assertEqual(self.window.view_mode, "head_right")
        for bad in (None, [], "unknown"):
            with self.assertRaises(ValueError):
                self.window.set_view_mode(bad)
        self.assertEqual(self.window.view_mode, "head_right")

    def test_head_canvas_width_scaling_and_side_view_switch_restore(self):
        from unittest.mock import Mock
        self.window.sprite_view.renderer_name = "pmx"
        self.window.sprite_view.set_view_mode = Mock()
        self.window._view_actions = {}
        original = (self.window.width(), self.window.height())
        self.window.set_view_mode("head_left")
        wide = (self.window.width(), self.window.height())
        area = self.window.screen().availableGeometry()
        self.assertEqual(wide, (min(area.width(), round(original[0] * 2.5)), min(area.height(), original[1])))
        self.window.set_view_mode("head_right")
        position = self.window.pos()
        self.window.set_view_mode("head_right")
        self.assertEqual(self.window.pos(), position)
        self.assertEqual((self.window.width(), self.window.height()), wide)
        self.window._resize_scale(.8)
        self.assertEqual((self.window.width(), self.window.height()), (min(area.width(), round(original[0] * 2)), min(area.height(), round(original[1] * .8))))
        self.window._fit_pose_window("side_lying")
        lying = (self.window.width(), self.window.height())
        self.window.set_view_mode("full")
        self.assertEqual((self.window.width(), self.window.height()), lying)
        self.window._fit_pose_window("idle")
        self.assertEqual((self.window.width(), self.window.height()), (round(original[0] * .8), round(original[1] * .8)))
        self.window.set_view_mode("head_front")
        self.window._fit_pose_window("side_lying")
        self.window._resize_scale(1)
        self.window._fit_pose_window("idle")
        self.assertEqual((self.window.width(), self.window.height()), wide)
        self.window.set_view_mode("full")
        self.assertEqual((self.window.width(), self.window.height()), original)

    def test_side_pose_window_fits_screen_and_restores_size(self):
        original = (self.window.width(), self.window.height())
        self.window.position_bottom_right()
        self.window._fit_pose_window("side_lying")
        area = self.window.screen().availableGeometry()
        self.assertGreater(self.window.width(), self.window.height())
        self.assertTrue(area.contains(self.window.geometry()))
        self.window._fit_pose_window("side_lying")
        self.window._fit_pose_window("idle")
        self.assertEqual((self.window.width(), self.window.height()), original)
        self.window._fit_pose_window("side_lying")
        self.window._resize_scale(.5)
        self.window._fit_pose_window("wave")
        self.assertEqual((self.window.width(), self.window.height()), (200, 300))

    def test_mood_rewards_only_successful_chat_and_focus_completion(self):
        from unittest.mock import patch
        self.window.tts.enabled = False  # 只验情绪事件，不让模拟对话请求备用联网音色。
        class FailedBackend:
            async def chat(self, *_, **kwargs):
                raise RuntimeError("模拟失败")
        with patch("src.core.chat_manager.make_backend", return_value=FailedBackend()):
            self.window.send_chat("一次失败的对话")
            self.wait(.05)
        self.assertEqual(self.window.mood.snapshot()["affection"], 30)
        class SuccessfulBackend:
            async def chat(self, *_, **kwargs):
                return "收到成功回复"
        self.window.chat.backends.clear()
        with patch("src.core.chat_manager.make_backend", return_value=SuccessfulBackend()):
            self.window.send_chat("完成一轮对话")
            self.wait(.05)
        self.window.chat.reply_ready.emit("同一轮重复回调", "zh")
        self.assertEqual(self.window.mood.snapshot()["affection"], 32)
        clock = [100.0]
        self.window.pomodoro.clock = lambda: clock[0]
        self.window.pomodoro.configure(sound=False)
        self.window.pomodoro.start()
        clock[0] += 1500
        self.window.pomodoro.tick()
        self.window.pomodoro.tick()
        self.assertEqual(self.window.mood.snapshot()["affection"], 35)
        self.window.pomodoro.start()
        clock[0] += 300
        self.window.pomodoro.tick()
        self.assertEqual(self.window.mood.snapshot()["affection"], 35, "休息结束不重复奖励专注")
        self.window.open_mood()
        dialog = self.window.mood_dialog
        self.window.set_click_through(True)
        self.window.hide_sprite()
        self.assertTrue(dialog.isVisible())
        dialog.close()
        self.window.touch_event.emit("tap", "头部")
        self.window.open_mood()
        self.assertEqual(dialog.affection_bar.value(), 36)

    def test_touch_does_not_cancel_chat_speech_and_selects_unlocked_japanese_reply(self):
        from unittest.mock import patch
        from src.core.voice_phrases import FOND_TOUCH_REPLIES
        self.window.sprite_view._behavior_settings = {"touch_reactions": True}
        self.window.mood._save({**self.window.mood.data, "affection": 80})
        self.window.tts.language = "ja"
        self.window.chat.busy = True
        with patch.object(self.window.tts, "speak") as speak, patch.object(self.window, "show_message") as bubble:
            self.window._touch_reaction("hand")
            speak.assert_not_called()
            bubble.assert_not_called()
        self.window.chat.busy = False
        with patch.object(self.window.voice_player, "snapshot", return_value={"state": "PlayingState"}), patch.object(self.window.tts, "speak") as speak:
            self.window._touch_reaction("hand")
            speak.assert_not_called()
        with patch.object(self.window.tts, "snapshot", return_value={"active": False, "configured": True}), patch.object(self.window.tts, "speak") as speak:
            self.window.tts.enabled = True
            self.window._touch_reaction("hand")
            speak.assert_called_once_with(FOND_TOUCH_REPLIES["ja"]["hand"])

    def test_pomodoro_survives_panel_close_sprite_hide_and_click_through(self):
        from unittest.mock import patch
        now = [100.0]
        manager = self.window.pomodoro
        manager.clock = lambda: now[0]
        manager.configure(sound=False)
        self.window.open_pomodoro()
        dialog = self.window.pomodoro_dialog
        dialog.start_button.click()
        self.assertTrue(self.window.pomodoro_overlay.isVisible())
        self.window.set_click_through(True)
        self.assertFalse(dialog.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.window.hide_sprite()
        self.app.processEvents()
        self.assertFalse(self.window.pomodoro_overlay.isVisible())
        self.assertTrue(dialog.isVisible(), "独立面板不随隐藏角色消失")
        dialog.close()
        now[0] += 30
        manager.tick()
        self.assertEqual(manager.snapshot()["remaining_seconds"], 1470)
        self.window.show_sprite()
        self.app.processEvents()
        self.assertTrue(self.window.pomodoro_overlay.isVisible())
        self.window.open_pomodoro()
        dialog.pause_button.click()
        self.assertEqual(manager.state, "paused")
        self.assertIn("已暂停", self.window.pomodoro_overlay.text())
        self.window.hide_sprite()
        notifications = []
        manager.finished.connect(notifications.append)
        dialog.pause_button.click()
        now[0] += 1470
        with patch.object(self.window, "show_message") as bubble:
            manager.tick()
            manager.tick()
            bubble.assert_not_called()
        self.assertEqual(len(notifications), 1)
        self.assertEqual(dialog.start_button.text(), "开始短休息")
        self.assertFalse(self.window.pomodoro_overlay.isVisible())

    def test_stream_starts_before_final_and_dialog_can_stop_queued_speech(self):
        from unittest.mock import patch
        from PyQt6.QtMultimedia import QMediaPlayer
        from src.ui.chat_dialog import ChatDialog
        release = threading.Event()
        class Backend:
            async def chat(self, text, language, delta, **kwargs):
                await delta("第一句。")
                while not release.is_set():
                    await asyncio.sleep(.005)
                await delta("第二句。")
                return "第一句。第二句。末句"
        self.window.tts.profiles_path.write_text("{}")
        self.window.tts.provider.synthesize = lambda text, *_: Path(self.temp.name) / (text + ".wav")
        played = []
        with patch("src.core.chat_manager.make_backend", return_value=Backend()), patch.object(self.window.voice_player, "play", side_effect=lambda path, *_: played.append(path.stem)):
            self.window.send_chat("测试分句")
            for _ in range(100):
                self.wait(.01)
                if played:
                    break
            self.assertEqual(played, ["第一句。"])
            self.window.voice_player.player.playbackStateChanged.emit(QMediaPlayer.PlaybackState.PlayingState)
            self.assertEqual(self.window.bubble_widget.message_label.text(), "第一句。")
            self.assertTrue(self.window.chat.busy, "第一句必须在后端完整回复前播放")
            token = self.window.tts.generation
            with self.assertRaises(ValueError):
                self.window.send_chat("忙碌期间的请求")
            self.assertEqual(self.window.tts.generation, token, "被拒绝的新请求不能停止当前朗读")
            release.set()
            for _ in range(100):
                self.wait(.01)
                if not self.window.chat.busy and not self.window.tts.busy:
                    break
            self.assertFalse(self.window.chat.busy)
            self.assertEqual([r[1] for r in self.window.chat.messages if r[0] == "心"], ["第一句。第二句。末句"])
            self.assertEqual(len(self.window.tts._ready), 2)
            self.assertEqual(self.window.bubble_widget.message_label.text(), "第一句。", "全文结束不能覆盖正在播放的句子")
            self.window.voice_player.player.playbackStateChanged.emit(QMediaPlayer.PlaybackState.StoppedState)
            self.wait(.01)
            self.assertEqual(played, ["第一句。", "第二句。"])
            self.assertEqual(self.window.bubble_widget.message_label.text(), "第一句。", "音频尚未真正播放时不要提前换句")
            self.window.voice_player.player.playbackStateChanged.emit(QMediaPlayer.PlaybackState.PlayingState)
            self.assertEqual(self.window.bubble_widget.message_label.text(), "第二句。")
            dialog = ChatDialog(self.window)
            self.assertTrue(dialog.stop_button.isEnabled(), "全文收到后仍可停止剩余语音")
            dialog.stop_button.click()
            self.wait(.01)
            self.assertEqual(played, ["第一句。", "第二句。"])
            self.assertFalse(self.window.tts.snapshot()["active"])
            self.assertFalse(dialog.stop_button.isEnabled())
            dialog.deleteLater()

    def test_text_only_reply_bubble_shows_sentences_and_stop_cancels_timer(self):
        from unittest.mock import patch
        class Backend:
            async def chat(self, text, language, delta, **kwargs):
                await delta("第一句。第二句。")
                return "第一句。第二句。末句"
        self.window.tts.configure(enabled=False)
        with patch("src.core.chat_manager.make_backend", return_value=Backend()):
            self.window.send_chat("测试文字气泡")
            for _ in range(100):
                self.wait(.01)
                if not self.window.chat.busy:
                    break
            self.assertFalse(self.window.chat.busy)
            self.assertEqual(self.window.bubble_widget.message_label.text(), "第一句。")
            self.assertTrue(self.window.reply_bubble.timer.isActive())
            self.window.reply_bubble.timer.start(1)
            self.wait(.03)
            self.assertEqual(self.window.bubble_widget.message_label.text(), "第二句。")
            self.window.stop_chat()
            self.assertFalse(self.window.reply_bubble.timer.isActive())
            self.assertFalse(self.window.bubble_widget.isVisible())

    def test_transparency_and_independent_model_paths(self):
        self.assertTrue(self.window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(self.window.sprite_view.model_path.is_file())
        self.assertFalse(self.window.sprite_view.model_loaded)
        self.assertEqual(self.window.windowTitle(), "心 · Hsin 桌面精灵")
        self.assertTrue(QFontMetrics(self.app.font()).inFontUcs4(ord("心")))

    def test_drag_from_renderer_and_tap_are_distinct(self):
        touches = []
        self.window.touch_event.connect(lambda *args: touches.append(args))
        target = self.window.sprite_view
        self.window.move(20, 20)
        before = self.window.pos()
        start = target.mapToGlobal(QPoint(80, 80))
        self._mouse(target, QEvent.Type.MouseButtonPress, QPointF(start), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        self._mouse(target, QEvent.Type.MouseMove, QPointF(start + QPoint(70, 35)), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        self._mouse(target, QEvent.Type.MouseButtonRelease, QPointF(start + QPoint(70, 35)), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        self.assertEqual(self.window.pos(), before + QPoint(70, 35))
        self.assertEqual(touches, [])
        self._mouse(target, QEvent.Type.MouseButtonPress, QPointF(start), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        self._mouse(target, QEvent.Type.MouseButtonRelease, QPointF(start), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        self.assertEqual(touches, [("tap", "身体")])

    def _mouse(self, target, kind, global_pos, button, buttons):
        local = QPointF(target.mapFromGlobal(global_pos.toPoint()))
        event = QMouseEvent(kind, local, global_pos, button, buttons, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(target, event)

    def test_bubble_plain_text_follow_and_timer(self):
        self.window.show_message("<b>御者</b>", 0)
        self.assertEqual(self.window.bubble_widget.message_label.textFormat(), Qt.TextFormat.PlainText)
        self.assertTrue(self.window.bubble_widget.isVisible())
        self.window.move(200, 250)
        self.app.processEvents()
        bubble = self.window.bubble_widget
        self.assertTrue(self.window.screen().availableGeometry().contains(bubble.geometry().topLeft()))
        self.window.show_message("自动收起", 40)
        self.wait(0.08)
        self.assertFalse(bubble.isVisible())

    def test_click_through_and_tray_recovery_preserve_hidden_state(self):
        self.window._click_through_action.trigger()
        self.assertTrue(self.window.is_click_through)
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        self.window._click_through_action.trigger()
        self.assertFalse(self.window.is_click_through)
        self.window.hide_sprite()
        self.window.set_click_through(True)
        self.window.set_always_on_top(False)
        self.assertFalse(self.window.isVisible())
        self.window.set_click_through(False)
        self.window.show_sprite()
        self.assertTrue(self.window.isVisible())

    def test_saved_position_uses_own_runtime(self):
        self.window.move(100, 100)
        self.window.save_state()
        state = json.loads((Path(self.temp.name) / "window.json").read_text())
        self.assertEqual(state, {"x": 100, "y": 100, "view_mode": "full"})

    def test_companion_priority_and_drag_release(self):
        from unittest.mock import Mock, patch
        from PyQt6.QtMultimedia import QMediaPlayer
        view = self.window.sprite_view
        view.renderer_name = "pmx"
        view.set_activity = Mock()
        stt = {"enabled": True, "listening": True, "blocked": False, "recognizing": False}
        with patch.object(self.window.stt, "snapshot", return_value=stt), patch.object(self.window.tts, "snapshot", return_value={"synthesizing": False}):
            self.window._sync_companion()
            view.set_activity.assert_called_with("listening", False)
            self.window.chat.busy = True
            self.window._sync_companion()
            view.set_activity.assert_called_with("thinking", False)
            with patch.object(self.window.voice_player.player, "playbackState", return_value=QMediaPlayer.PlaybackState.PlayingState):
                self.window._sync_companion()
                view.set_activity.assert_called_with("speaking", False)
            self.window.chat.busy = False
            stt["recognizing"] = True
            self.window.drag_position = QPoint(10, 10)
            self.window._sync_companion()
            view.set_activity.assert_called_with("thinking", True)
            stt.update(recognizing=False, enabled=False, listening=False)
            self.window.set_click_through(True)
            view.set_activity.assert_called_with("idle", False)
        view.renderer_name = "placeholder"


class IdleRestTest(QtWindowTestCase):
    def setUp(self):
        super().setUp()
        from unittest.mock import Mock
        self.view = self.window.sprite_view
        self.view.renderer_name = "pmx"
        self.view.model_loaded = True
        self.view.model_info = {"runtime": {"motion": "idle"}}
        self.view.get_available_motions = Mock(return_value=["idle", "side_lying"])
        self.view.trigger_motion = Mock()
        self.view.set_activity = Mock()

    def tearDown(self):
        self.view.renderer_name = "placeholder"
        self.view.model_loaded = False
        super().tearDown()

    def elapse(self, seconds):
        self.window._last_interaction = time.monotonic() - seconds

    def test_ten_minutes_then_one_request_and_immediate_wake(self):
        self.elapse(599)
        self.window._tick_rest()
        self.view.trigger_motion.assert_not_called()
        self.elapse(600)
        self.window._tick_rest()
        self.window._tick_rest()
        self.view.trigger_motion.assert_called_once_with("side_lying")
        self.view.model_info["runtime"]["motion"] = "side_lying"
        self.window._record_interaction()
        self.view.trigger_motion.assert_called_with("idle")
        self.window._record_interaction()
        self.assertEqual(self.view.trigger_motion.call_count, 2)
        self.view.model_info["runtime"]["motion"] = "idle"
        self.window._rest_pose_changed("idle")
        self.window._tick_rest()
        self.assertEqual(self.view.trigger_motion.call_count, 2)
        self.assertFalse(self.window._rest_requested)

    def test_busy_loading_hidden_and_manual_motion_do_not_rest(self):
        from unittest.mock import patch
        for blocker in ("chat", "tts", "speech", "recognizing", "drag", "hidden", "loading", "motion", "missing"):
            self.elapse(601)
            stt = {**self.window.stt.snapshot(), "speech_active": blocker == "speech", "recognizing": blocker == "recognizing"}
            self.window.chat.busy = blocker == "chat"
            self.window.drag_position = QPoint(1, 1) if blocker == "drag" else None
            self.view.model_loaded = blocker != "loading"
            self.view.model_info["runtime"]["motion"] = "wave" if blocker == "motion" else "idle"
            self.view.get_available_motions.return_value = [] if blocker == "missing" else ["idle", "side_lying"]
            self.window.setVisible(blocker != "hidden")
            with patch.object(self.window.tts, "snapshot", return_value={"active": blocker == "tts"}), patch.object(self.window.stt, "snapshot", return_value=stt):
                self.window._tick_rest()
            self.view.trigger_motion.assert_not_called()
        self.window.chat.busy = False

    def test_typing_wakes_manual_rest_but_mouse_follow_does_not(self):
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtWidgets import QLineEdit
        editor = QLineEdit(self.window)
        self.elapse(601)
        before = self.window._last_interaction
        self.app.sendEvent(editor, QEvent(QEvent.Type.Enter))
        self.assertEqual(before, self.window._last_interaction)
        self.view.model_info["runtime"]["motion"] = "side_lying"
        self.app.sendEvent(editor, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, "a"))
        self.view.trigger_motion.assert_called_once_with("idle")
        self.assertLess(time.monotonic() - self.window._last_interaction, 1)
        editor.deleteLater()

    def test_chat_and_detected_speech_wake_even_during_lie_down(self):
        from unittest.mock import patch
        self.view.model_info["runtime"]["motion"] = "lie_down"
        with patch.object(self.window.chat, "send", return_value={"id": 1}) as send:
            self.window.send_chat("御者来了")
            send.assert_called_once()
        self.view.trigger_motion.assert_called_once_with("idle")
        self.window._rest_pose_changed("idle")
        self.view.trigger_motion.reset_mock()
        self.view.model_info["runtime"]["motion"] = "side_lying"
        with patch.object(self.window.stt, "snapshot", return_value={**self.window.stt.snapshot(), "speech_active": True}):
            self.window._sync_rest_activity()
        self.view.trigger_motion.assert_called_once_with("idle")


class APITest(QtWindowTestCase):
    def setUp(self):
        super().setUp()
        self.bridge = ControlBridge(self.window)
        config = deepcopy(self.config)
        # 测试用临时端口，不占用真实 Hsin / 爱弥斯端口。
        config["websocket"]["port"] = 0
        config["http"]["port"] = 0
        self.services = ControlServices(self.bridge, config)
        self.services.start()
        self.window.touch_event.connect(lambda a, p: self.services.broadcast_sync("touch_event", {"action": a, "part": p}))
        self.pool = ThreadPoolExecutor(1)

    def tearDown(self):
        self.bridge.close()
        self.services.stop()
        self.pool.shutdown(wait=True)
        super().tearDown()

    def network(self, coroutine):
        future = self.pool.submit(asyncio.run, coroutine)
        deadline = time.monotonic() + 8
        while not future.done() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.003)
        return future.result(timeout=1)

    def test_websocket_status_message_move_and_bad_payloads(self):
        async def client():
            async with websockets.connect(self.services.endpoints()["websocket"]) as ws:
                await ws.send(json.dumps({"type": "window", "data": {"action": "move", "x": 123, "y": 145}, "id": "move-1"}))
                moved = json.loads(await ws.recv())
                await ws.send(json.dumps({"type": "message", "data": {"text": "心的气泡", "duration": 0}}))
                message = json.loads(await ws.recv())
                await ws.send('{"type":"get_status"}')
                status = json.loads(await ws.recv())
                await ws.send("broken JSON")
                bad = json.loads(await ws.recv())
                await ws.send('{"type":"window","data":{"action":"opacity","opacity":2}}')
                invalid = json.loads(await ws.recv())
                await ws.send('{"type":"get_status","id":NaN}')
                nonfinite = json.loads(await ws.recv())
                return moved, message, status, bad, invalid, nonfinite
        moved, message, status, bad, invalid, nonfinite = self.network(client())
        self.assertEqual(moved["id"], "move-1")
        self.assertTrue(message["success"])
        self.assertEqual(self.window.bubble_widget.message_label.text(), "心的气泡")
        self.assertEqual(status["data"]["position"], {"x": 123, "y": 145})
        self.assertEqual(status["data"]["connected_clients"], 1)
        self.assertEqual(status["data"]["state"], "model_pending")
        self.assertEqual(bad["data"]["code"], "invalid_json")
        self.assertFalse(invalid["success"])
        self.assertEqual(nonfinite["data"]["code"], "invalid_json")

    def test_http_alias_generic_health_and_unavailable_features(self):
        async def client():
            url = self.services.endpoints()["http"]
            async with ClientSession() as session:
                async with session.post(url + "/api/window", json={"action": "resize", "width": 320, "height": 480}) as r:
                    resized = await r.json()
                async with session.post(url + "/api/command", json={"type": "background", "data": {"type": "purple"}}) as r:
                    background = await r.json()
                async with session.get(url + "/health") as r:
                    status = await r.json()
                async with session.post(url + "/api/expression", json={"name": "happy"}) as r:
                    unavailable_status, unavailable = r.status, await r.json()
                async with session.post(url + "/api/command", json={"type": "window", "data": []}) as r:
                    invalid_status = r.status
                return resized, background, status, unavailable_status, unavailable, invalid_status
        resized, background, status, error_status, error, invalid = self.network(client())
        self.assertTrue(resized["success"])
        self.assertTrue(background["success"])
        self.assertEqual(status["data"]["window"]["width"], 320)
        self.assertEqual(status["data"]["window"]["background"], "purple")
        self.assertEqual(error_status, 501)
        self.assertEqual(error["data"]["code"], "renderer_unavailable")
        self.assertEqual(invalid, 400)

    def test_tts_language_alias_is_persistent_and_invalid_batch_is_atomic(self):
        async def client():
            url = self.services.endpoints()["http"]
            async with ClientSession() as session:
                async with session.post(url + "/api/tts_config", json={"language": "ja", "enabled": False}) as r:
                    changed = await r.json()
                async with session.post(url + "/api/tts_config", json={"language": "en", "enabled": True}) as r:
                    invalid = await r.json()
                async with session.get(url + "/api/status") as r:
                    status = await r.json()
                return changed, invalid, status
        changed, invalid, status = self.network(client())
        self.assertTrue(changed["success"])
        self.assertFalse(invalid["success"])
        self.assertEqual(status["data"]["tts"]["language"], "ja")
        self.assertFalse(status["data"]["tts"]["enabled"])
        self.assertEqual(json.loads(self.window.tts.state_path.read_text())["language"], "ja")
        self.assertTrue(self.window._voice_language_actions["ja"].isChecked())
        self.assertFalse(self.window._voice_language_actions["zh"].isChecked())
        self.assertFalse(self.window._voice_enabled_action.isChecked())

    def test_touch_broadcast(self):
        received = threading.Event()
        async def client():
            async with websockets.connect(self.services.endpoints()["websocket"]) as ws:
                received.set()
                return json.loads(await ws.recv())
        future = self.pool.submit(asyncio.run, client())
        self.assertTrue(received.wait(3))
        self.window.touch_event.emit("tap", "身体")
        result = future.result(timeout=3)
        self.assertEqual(result, {"type": "touch_event", "data": {"action": "tap", "part": "身体"}})

    def test_mood_http_settings_and_websocket_snapshot(self):
        async def client():
            async with ClientSession() as session:
                url = self.services.endpoints()["http"] + "/api/mood"
                async with session.post(url, json={"action": "configure", "auto_expression": False}) as r:
                    self.assertFalse((await r.json())["data"]["auto_expression"])
                for invalid in ({"action": "configure", "auto_expression": 1}, {"action": "configure", "auto_expression": True, "affection": 100}):
                    async with session.post(url, json=invalid) as r:
                        self.assertEqual(r.status, 400)
            async with websockets.connect(self.services.endpoints()["websocket"]) as ws:
                await ws.send(json.dumps({"type": "mood", "data": {"action": "status"}}))
                result = json.loads(await ws.recv())
                self.assertEqual(result["data"]["affection"], 30)
                self.assertFalse(result["data"]["auto_expression"])
        self.network(client())

    def test_pomodoro_http_settings_and_websocket_controls(self):
        async def client():
            url = self.services.endpoints()["http"]
            async with ClientSession() as session:
                async with session.post(url + "/api/pomodoro", json={"action": "configure", "focus_minutes": 1, "sound": False}) as r:
                    self.assertEqual(r.status, 200)
                async with session.post(url + "/api/pomodoro", json={"action": "configure", "focus_minutes": 10, "sound": 1}) as r:
                    self.assertEqual(r.status, 400)
                async with session.post(url + "/api/pomodoro", json={"action": "start"}) as r:
                    self.assertEqual((await r.json())["data"]["remaining_seconds"], 60)
            async with websockets.connect(self.services.endpoints()["websocket"]) as ws:
                for action, expected in (("pause", "paused"), ("resume", "running"), ("reset", "idle")):
                    await ws.send(json.dumps({"type": "pomodoro", "data": {"action": action}}))
                    result = json.loads(await ws.recv())
                    self.assertTrue(result["success"])
                    self.assertEqual(result["data"]["state"], expected)
                await ws.send(json.dumps({"type": "get_status"}))
                result = json.loads(await ws.recv())
                self.assertIn("pomodoro", result["data"]["capabilities"])
                self.assertEqual(result["data"]["pomodoro"]["settings"]["focus_minutes"], 1)
        self.network(client())

    def test_stt_http_settings_and_invalid_batch(self):
        from unittest.mock import patch
        async def client():
            url = self.services.endpoints()["http"]
            async with ClientSession() as session:
                async with session.post(url + "/api/stt_config", json={"enabled": True, "language": "ja", "provider": "qwen"}) as r:
                    changed = await r.json()
                async with session.post(url + "/api/stt_config", json={"language": "unknown", "enabled": False}) as r:
                    invalid = await r.json()
                async with session.post(url + "/api/stt_config", json={"action": "status"}) as r:
                    state = await r.json()
                async with session.post(url + "/api/stt_config", json={"action": "off"}) as r:
                    stopped = await r.json()
            return changed, invalid, state, stopped
        with patch.object(self.window.stt, "_start_capture"):
            changed, invalid, state, stopped = self.network(client())
        self.assertTrue(changed["success"])
        self.assertFalse(invalid["success"])
        self.assertTrue(state["data"]["enabled"])
        self.assertEqual(state["data"]["language"], "ja")
        self.assertFalse(stopped["data"]["enabled"])
        self.assertFalse(self.window._microphone_action.isChecked())

    def test_chat_and_playback_block_microphone(self):
        from PyQt6.QtMultimedia import QMediaPlayer
        from unittest.mock import patch
        self.window.chat.busy = True
        self.window.chat.changed.emit()
        self.assertTrue(self.window.stt.blocked)
        self.window.chat.busy = False
        self.window.chat.changed.emit()
        self.assertFalse(self.window.stt.blocked)
        with patch.object(self.window.voice_player.player, "playbackState", return_value=QMediaPlayer.PlaybackState.PlayingState):
            self.window._sync_microphone()
            self.assertTrue(self.window.stt.blocked)
        self.window._sync_microphone()
        self.assertFalse(self.window.stt.blocked)

    def test_hotwords_settings_are_persistent(self):
        from unittest.mock import patch
        import yaml
        from src.ui.microphone_dialog import MicrophoneDialog
        root = Path(self.temp.name)
        (root / "config.local.yaml").write_text("chat:\n  provider: hermes\n", encoding="utf-8")
        dialog = MicrophoneDialog(self.window)
        dialog.hotwords.setPlainText("心\n心月狐\n御者\n心")
        with patch("src.ui.microphone_dialog.PROJECT_ROOT", root):
            dialog.save()
        saved = yaml.safe_load((root / "config.local.yaml").read_text(encoding="utf-8"))
        self.assertEqual(saved["stt"]["hotwords"], ["心", "心月狐", "御者"])
        self.assertEqual(self.window.stt.config["hotwords"], ["心", "心月狐", "御者"])
        self.assertEqual(saved["chat"]["provider"], "hermes")

    def test_shutdown_releases_ports(self):
        ports = [self.services.ws.port, self.services.http.port]
        self.bridge.close()
        self.services.stop()
        self.assertFalse(self.services.thread.is_alive())
        for port in ports:
            with socket.socket() as sock:
                sock.settimeout(0.2)
                self.assertNotEqual(sock.connect_ex(("127.0.0.1", port)), 0)


class ConfigTest(unittest.TestCase):
    def test_default_ports_are_independent(self):
        config = load_config()
        self.assertEqual(config["websocket"]["port"], 18765)
        self.assertEqual(config["http"]["port"], 18766)

    def test_external_bind_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("websocket:\n  host: 0.0.0.0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "回环"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
