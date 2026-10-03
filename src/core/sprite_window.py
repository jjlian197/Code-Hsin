"""Hsin 桌面窗口；置顶、透明、托盘和拖动行为适配自 aemeath-spirit。"""
import json
import time
from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QPixmap
from PyQt6.QtWidgets import QApplication, QFrame, QInputDialog, QMainWindow, QMenu, QStackedLayout, QSystemTrayIcon

from src.core.app_config import project_path
from src.core.sprite_view import SpriteView
from src.core.pmx_view import PmxView
from src.core.voice_player import LocalVoicePlayer
from src.core.tts_manager import TTSManager
from src.core.stt_manager import STTManager
from src.core.voice_phrases import TOUCH_REPLIES, PREVIEW_PHRASES, TRUSTED_TOUCH_REPLIES, FOND_TOUCH_REPLIES
from src.core.chat_manager import ChatManager
from src.core.pomodoro import PomodoroManager
from src.core.mood import MoodManager
from src.core.chat_backends import PROVIDERS
from src.ui.app_icon import create_icon
from src.ui.background_frame import BackgroundFrame
from src.ui.bubble_widget import BubbleWidget
from src.ui.pomodoro_overlay import PomodoroOverlay
from src.ui.fonts import ensure_fonts

EXPRESSION_LABELS = {"normal": "平常", "happy": "开心", "sad": "难过", "angry": "生气", "surprised": "惊讶",
                     "wink": "眨单眼", "sleepy": "困倦", "relaxed": "放松", "blush": "脸红",
                     "content": "笑眯眯", "star_eyes": "星星眼", "heart_eyes": "爱心眼"}


class HsinSpriteWindow(QMainWindow):
    touch_event = pyqtSignal(str, str)
    quit_requested = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        ensure_fonts()
        self.config = config
        self.drag_position = None
        self._press_point = None
        self._dragged = False
        self._standing_size = None
        self._current_background = "transparent"
        self.is_click_through = False
        self._always_on_top = config["sprite"]["window"]["always_on_top"]
        self._state_path = project_path(config["runtime"]["directory"]) / "window.json"
        self._click_through_action = QAction("鼠标穿透（可在托盘取消）", self)
        self._click_through_action.setCheckable(True)
        self._click_through_action.triggered.connect(self.set_click_through)
        self._top_action = QAction("保持置顶", self)
        self._top_action.setCheckable(True)
        self._top_action.setChecked(self._always_on_top)
        self._top_action.triggered.connect(self.set_always_on_top)
        self._setup_window()
        self._setup_ui()
        self.mood = MoodManager(self._state_path.with_name("mood.json"), self)
        self.mood_dialog = None
        self._mood_chat_generation = -1
        self._mood_focus_count = 0
        self.mood.changed.connect(self._sync_mood)
        self.touch_event.connect(self._mood_touch)
        self.pomodoro = PomodoroManager(self._state_path.with_name("pomodoro.json"), self)
        self.pomodoro_dialog = None
        self.pomodoro_overlay = PomodoroOverlay(self)
        self.pomodoro.finished.connect(self._pomodoro_finished)
        self.voice_player = LocalVoicePlayer(self)
        self.tts = TTSManager(config, self.voice_player, self)
        self.chat = ChatManager(config, self)
        self.stt = STTManager(config, self)
        self.stt.transcript.connect(self._microphone_transcript)
        self.stt.failed.connect(lambda error: self.show_message(error[:500], 8000))
        self.chat.changed.connect(self._sync_microphone)
        self.tts.changed.connect(self._sync_microphone)
        self.voice_player.player.playbackStateChanged.connect(self._sync_microphone)
        self.chat_dialog = None
        self._speech_chat_generation = self.chat.generation
        self._speech_token = None
        self.chat.changed.connect(self._sync_chat_speech)
        self.chat.sentence_ready.connect(self._chat_sentence)
        self.chat.speech_finished.connect(self._chat_speech_finished)
        self.chat.reply_ready.connect(self._chat_reply)
        self._chat_language = self.tts.language
        self.tts.changed.connect(self._sync_chat_language)
        self.tts.speech_started.connect(self._show_spoken_text)
        self.tts.failed.connect(lambda error: self.show_message(error[:500], 8000))
        self._last_spoken_touch = 0
        if self.sprite_view.renderer_name == "pmx":
            self.voice_player.level_changed.connect(self.sprite_view.audio_level)
            self.chat.changed.connect(self._sync_companion)
            self.tts.changed.connect(self._sync_companion)
            self.stt.changed.connect(self._sync_companion)
            self.voice_player.player.playbackStateChanged.connect(self._sync_companion)
            self.sprite_view.load_finished.connect(self._model_actions_ready)
            self.sprite_view.pose_changed.connect(self._fit_pose_window)
        self._setup_tray()
        self.tts.changed.connect(self._refresh_voice_menu)
        self.chat.changed.connect(self._refresh_chat_menu)
        self._refresh_chat_menu()
        self._refresh_voice_menu()
        self.stt.changed.connect(self._refresh_microphone_menu)
        self._refresh_microphone_menu()
        self.mood.timer.timeout.connect(self._tick_mood)
        self.mood.timer.start()
        self._sync_mood()
        self._restore_state()
        self.setWindowOpacity(float(config["sprite"]["window"]["opacity"]))
        self.set_click_through(config["sprite"]["window"]["click_through"])

    def _setup_window(self):
        # 复用参考窗口标志：透明、无边框、工具窗口，不抢输入焦点。
        flags = (Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint |
                 Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.Tool)
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("心 · Hsin 桌面精灵")
        self.setWindowIcon(create_icon())
        window = self.config["sprite"]["window"]
        self.setFixedSize(window["width"], window["height"])

    def _setup_ui(self):
        self.central_widget = QFrame()
        self.central_widget.setFrameShape(QFrame.Shape.NoFrame)
        self.central_widget.setStyleSheet("background: transparent;")
        self.setCentralWidget(self.central_widget)
        layout = QStackedLayout(self.central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        path = self.config["sprite"]["model"]["path"]
        view_type = PmxView if self.config["sprite"]["renderer"] == "pmx" else SpriteView
        options = {}
        if view_type is PmxView:
            model = self.config["sprite"]["model"]
            options["texture_overrides"] = {str(project_path(model["forms"][form])): mapping
                for form, mapping in model.get("texture_overrides", {}).items() if form in model["forms"]}
            options["animation_config"] = self.config["sprite"].get("animation", {})
        self.sprite_view = view_type(project_path(path) if path else None, self.central_widget, **options)
        layout.addWidget(self.sprite_view)
        self.background_frame = BackgroundFrame(self.central_widget)
        layout.addWidget(self.background_frame)
        layout.setCurrentWidget(self.sprite_view)
        self.background_frame.stackUnder(self.sprite_view)
        self.bubble_widget = BubbleWidget(self)
        self.bubble_widget.hide()
        # 渲染画板收到的鼠标事件也必须能拖动主窗口。
        self.central_widget.installEventFilter(self)
        self.sprite_view.installEventFilter(self)

    def _setup_tray(self):
        self.tray_icon = None
        self._tray_menu = self._build_menu()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = QSystemTrayIcon(create_icon(), self)
            self.tray_icon.setToolTip("心 · Hsin 桌面精灵")
            self.tray_icon.setContextMenu(self._tray_menu)
            self.tray_icon.activated.connect(self._tray_activated)
            self.tray_icon.show()

    def _build_menu(self):
        # 独立顶层菜单，即使精灵穿透鼠标，托盘仍可恢复操作。
        menu = QMenu()
        menu.addAction("显示心", self.show_sprite)
        menu.addAction("隐藏心", self.hide_sprite)
        menu.addAction("回到屏幕右下角", self.position_bottom_right)
        menu.addAction("和心聊天…", self.open_chat)
        menu.addAction("番茄钟…", self.open_pomodoro)
        mood_menu = menu.addMenu("心情与好感度")
        self._mood_status_action = mood_menu.addAction("")
        self._mood_status_action.setEnabled(False)
        mood_menu.addAction("查看陪伴状态…", self.open_mood)
        self._mood_auto_action = mood_menu.addAction("让心情自然影响表情")
        self._mood_auto_action.setCheckable(True)
        self._mood_auto_action.triggered.connect(self.configure_mood)
        backend_menu = menu.addMenu("对话后端")
        backend_group = QActionGroup(backend_menu)
        backend_group.setExclusive(True)
        self._backend_actions = {}
        for provider, label in PROVIDERS.items():
            action = backend_menu.addAction(label)
            action.setCheckable(True)
            backend_group.addAction(action)
            action.triggered.connect(lambda checked, key=provider: self.set_chat_provider(key))
            self._backend_actions[provider] = action
        backend_menu.addSeparator()
        backend_menu.addAction("连接设置…", self.configure_chat)
        backend_menu.addAction("停止回复", self.stop_chat)
        self._chat_status_action = backend_menu.addAction("准备对话")
        self._chat_status_action.setEnabled(False)
        menu.addSeparator()
        menu.addAction(self._top_action)
        menu.addAction(self._click_through_action)
        size_menu = menu.addMenu("大小")
        for label, scale in (("80%", 0.8), ("100%", 1.0), ("125%", 1.25)):
            size_menu.addAction(label, lambda checked=False, s=scale: self._resize_scale(s))
        if self.sprite_view.renderer_name == "pmx":
            motions_menu = menu.addMenu("动作")
            self._motion_actions = {}
            for key, label in (("idle", "待机"), ("nod", "点头"), ("wave", "挥手"),
                               ("peace", "V 手势"), ("finger_heart", "指尖比心"), ("crossed_arms", "交叉手臂"), ("side_lying", "侧躺（保持；选择待机恢复站立）")):
                action = motions_menu.addAction(label, lambda checked=False, group=key: self._play_motion(group))
                action.setEnabled(False)
                self._motion_actions[key] = action
            expressions_menu = menu.addMenu("表情")
            expression_group = QActionGroup(expressions_menu)
            expression_group.setExclusive(True)
            self._expression_actions = {}
            for key, label in EXPRESSION_LABELS.items():
                action = expressions_menu.addAction(label)
                action.setCheckable(True)
                action.setEnabled(False)
                expression_group.addAction(action)
                action.triggered.connect(lambda checked, name=key: self.set_expression(name))
                self._expression_actions[key] = action
            companion_menu = menu.addMenu("陪伴动作")
            self._companion_actions = {}
            for key, label in (("conversation_actions", "对话时思考、倾听和说话手势"), ("random_idle", "随机环顾和轻微伸展")):
                action = companion_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(self.sprite_view._behavior_settings[key])
                action.triggered.connect(lambda enabled, setting=key: self.set_behavior({setting: enabled}))
                self._companion_actions[key] = action
            self._physics_action = QAction("头发与衣摆物理", self)
            self._physics_action.setCheckable(True)
            self._physics_action.setChecked(self.sprite_view._physics_enabled)
            self._physics_action.triggered.connect(self.set_physics)
            menu.addAction(self._physics_action)
            menu.addAction("重置物理", self._reset_physics)
            self._follow_action = QAction("眼神跟随鼠标", self)
            self._follow_action.setCheckable(True)
            self._follow_action.setChecked(self.sprite_view._behavior_settings["mouse_follow"])
            self._follow_action.triggered.connect(lambda enabled: self.set_behavior({"mouse_follow": enabled}))
            menu.addAction(self._follow_action)
            menu.addAction("眨眼", lambda: self.sprite_view.blink() if self.sprite_view.model_loaded else None)
            forms_menu = menu.addMenu("形态")
            for key, label in (("first", "一阶段"), ("second", "二阶段")):
                if key in self.config["sprite"]["model"]["forms"]:
                    forms_menu.addAction(label, lambda checked=False, form=key: self.set_model_form(form))
        voice_menu = menu.addMenu("语音")
        self._voice_enabled_action = voice_menu.addAction("开启语音")
        self._voice_enabled_action.setCheckable(True)
        self._voice_enabled_action.triggered.connect(lambda enabled: self.tts.configure(enabled=enabled))
        group = QActionGroup(voice_menu)
        group.setExclusive(True)
        self._voice_language_actions = {}
        for language, label in (("zh", "中文"), ("ja", "日本語")):
            action = voice_menu.addAction(label)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda checked, lang=language: self.tts.configure(language=lang))
            self._voice_language_actions[language] = action
        engines = voice_menu.addMenu("语音引擎")
        engine_group = QActionGroup(engines)
        engine_group.setExclusive(True)
        self._voice_engine_actions = {}
        for engine, label in (("gptsovits", "心 · GPT-SoVITS"), ("edge", "Edge · 通用女声（联网）")):
            action = engines.addAction(label)
            action.setCheckable(True)
            engine_group.addAction(action)
            action.triggered.connect(lambda checked, name=engine: self.tts.configure(provider=name))
            self._voice_engine_actions[engine] = action
        self._voice_translate_action = voice_menu.addAction("自动翻译文本")
        self._voice_translate_action.setCheckable(True)
        self._voice_translate_action.setToolTip("复用 DeepSeek 连接设置，把直接朗读的文本翻译为所选语言")
        self._voice_translate_action.triggered.connect(lambda enabled: self.tts.configure(auto_translate=enabled))
        self._voice_fallback_action = voice_menu.addAction("合成失败使用备用音色")
        self._voice_fallback_action.setCheckable(True)
        self._voice_fallback_action.setToolTip("心的音色失败时使用 Edge；Edge 失败时尝试心的音色。备用音色会在状态中标明")
        self._voice_fallback_action.triggered.connect(lambda enabled: self.tts.configure(fallback=enabled))
        voice_menu.addAction("朗读文本…", self.read_text)
        voice_menu.addAction("试听当前语言", self.preview_voice)
        voice_menu.addAction("停止语音", self.tts.stop)
        self._voice_status_action = voice_menu.addAction("准备语音")
        self._voice_status_action.setEnabled(False)
        microphone_menu = menu.addMenu("麦克风识别")
        self._microphone_action = microphone_menu.addAction("开启麦克风对话")
        self._microphone_action.setCheckable(True)
        self._microphone_action.triggered.connect(self.toggle_microphone)
        microphone_menu.addAction("麦克风设置…", self.configure_microphone)
        self._microphone_status_action = microphone_menu.addAction("麦克风已关闭")
        self._microphone_status_action.setEnabled(False)
        menu.addAction("气泡示例", lambda: self.show_message("御者，我在这里。", 4000))
        menu.addSeparator()
        menu.addAction("退出", self.quit_requested.emit)
        return menu

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_sprite()

    def _refresh_chat_menu(self):
        for provider, action in self._backend_actions.items():
            action.setChecked(provider == self.chat.provider)
        self._chat_status_action.setText("正在回复…" if self.chat.busy else (self.chat.error or "可以开始对话"))

    def _sync_chat_language(self):
        if self.tts.language != self._chat_language:
            self._chat_language = self.tts.language
            self.chat.stop()

    def _sync_chat_speech(self):
        if self._speech_chat_generation == self.chat.generation:
            return
        self._speech_chat_generation = self.chat.generation
        self._speech_token = None
        self.tts.stop()
        if self.chat.busy and self.tts.enabled and self.tts.snapshot()["configured"]:
            self._speech_token = self.tts.begin_stream(self.chat.last_request["language"])

    def _chat_sentence(self, generation, text, language):
        if generation == self._speech_chat_generation and self._speech_token is not None:
            self.tts.enqueue_sentence(self._speech_token, text, language)

    def _chat_speech_finished(self, generation, success):
        if generation != self._speech_chat_generation or self._speech_token is None:
            return
        if success:
            self.tts.finish_stream(self._speech_token)
        else:
            self.tts.stop()
        self._speech_token = None

    def _show_spoken_text(self, text):
        if self.tts.last_request and self.tts.last_request.get("stream"):
            full = self.chat.partial or (self.chat.snapshot()["reply"] or text)
            self.show_message(full[:2000], 12000)
        else:
            self.show_message(text, 8000)

    def _sync_companion(self, *_):
        if self.sprite_view.renderer_name != "pmx":
            return
        from PyQt6.QtMultimedia import QMediaPlayer
        playing = self.voice_player.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        stt = self.stt.snapshot()
        if playing:
            state = "speaking"
        elif self.chat.busy or self.tts.snapshot()["synthesizing"] or stt["recognizing"]:
            state = "thinking"
        elif stt["listening"] and stt["enabled"] and not stt["blocked"]:
            state = "listening"
        else:
            state = "idle"
        self.sprite_view.set_activity(state, self.drag_position is not None)

    def _model_actions_ready(self, success):
        if self.sprite_view.renderer_name != "pmx":
            return
        for name, action in self._motion_actions.items():
            action.setEnabled(success and name in self.sprite_view.get_available_motions())
        for name, action in self._expression_actions.items():
            action.setEnabled(success and name in self.sprite_view.get_available_expressions())
            action.setChecked(name == self.sprite_view.current_expression)
        self._sync_companion()
        self._sync_mood(force=True)

    def set_expression(self, name):
        self.sprite_view.set_expression(name)
        if hasattr(self, "_expression_actions"):
            for key, action in self._expression_actions.items():
                action.setChecked(key == name)

    def _sync_microphone(self, *_):
        from PyQt6.QtMultimedia import QMediaPlayer
        speaking = self.voice_player.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState
        self.stt.set_blocked(self.chat.busy or self.tts.snapshot()["active"] or speaking)

    def toggle_microphone(self, enabled):
        self._sync_microphone()
        self.stt.configure(enabled=enabled)
        if enabled and self.stt.enabled:
            self.show_message("麦克风已开启，说完停顿后我会回复。", 5000)

    def configure_microphone(self):
        from src.ui.microphone_dialog import MicrophoneDialog
        MicrophoneDialog(self).exec()

    def _refresh_microphone_menu(self):
        state = self.stt.snapshot()
        self._microphone_action.setChecked(state["enabled"])
        label = "麦克风已关闭"
        if state["enabled"]:
            label = "识别中…" if state["recognizing"] else ("回复期间暂停收音" if state["blocked"] else "正在听你说话")
        self._microphone_status_action.setText(state["error"] or label)
        self._microphone_status_action.setToolTip(state["warning"] or state["last_text"])
        if self.tray_icon:
            self.tray_icon.setToolTip("心 · Hsin · " + label)

    def _microphone_transcript(self, text):
        if self.chat.busy:
            return
        self.show_message("听到：" + text[:450], 6000)
        try:
            self.send_chat(text)
        except ValueError as exc:
            self.show_message(str(exc), 6000)

    def set_chat_provider(self, provider):
        if provider != self.chat.provider:
            self.tts.stop()
        return self.chat.configure(provider)

    def configure_chat(self):
        from src.ui.connection_dialog import ConnectionDialog
        ConnectionDialog(self).exec()

    def open_chat(self):
        from src.ui.chat_dialog import ChatDialog
        if self.chat_dialog is None:
            self.chat_dialog = ChatDialog(self)
        self.chat_dialog.open_near(self)

    def send_chat(self, text, language=None):
        return self.chat.send(text, self.tts.language if language is None else language)

    def stop_chat(self):
        self.chat.stop()
        self.tts.stop()

    def _chat_reply(self, text, language):
        if self.chat.last_request and self.chat.last_request["id"] == self.chat.generation and self.chat.generation != self._mood_chat_generation:
            self._mood_chat_generation = self.chat.generation
            self.mood.interact("chat")
        self.show_message(text[:2000], 12000)

    def show_sprite(self):
        self.show()
        self.raise_()

    def hide_sprite(self):
        self.bubble_widget.hide()
        self.hide()

    def set_click_through(self, enabled):
        visible = self.isVisible()
        self.is_click_through = bool(enabled)
        self._click_through_action.setChecked(enabled)
        for widget in (self, self.central_widget, self.sprite_view):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enabled)
        self.drag_position = None
        self._sync_companion()
        # 修改原生标志会隐藏窗口，仅恢复原本可见的窗口。
        if visible:
            self.show()

    def set_always_on_top(self, enabled):
        visible = self.isVisible()
        self._always_on_top = bool(enabled)
        self._top_action.setChecked(enabled)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if visible:
            self.show()

    def set_position(self, x, y):
        self.move(x, y)

    def set_opacity(self, opacity):
        self.setWindowOpacity(opacity)

    def set_size(self, width, height):
        self.setFixedSize(width, height)
        self.bubble_widget.reposition()

    def _resize_scale(self, scale):
        window = self.config["sprite"]["window"]
        width, height = int(window["width"] * scale), int(window["height"] * scale)
        if self._standing_size is not None:
            self._standing_size = (width, height)
            width, height = self._side_window_size(width, height)
        self.set_size(width, height)
        self._keep_on_screen()

    def _side_window_size(self, width, height):
        area = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        scale = min(width / 400, height / 600)
        factor = min(scale, area.width() / 900, area.height() / 420)
        return max(1, round(900 * factor)), max(1, round(420 * factor))

    def _keep_on_screen(self):
        area = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        self.move(max(area.left(), min(self.x(), area.right() + 1 - self.width())),
                  max(area.top(), min(self.y(), area.bottom() + 1 - self.height())))

    def _fit_pose_window(self, motion):
        if motion == "side_lying" and self._standing_size is None:
            self._standing_size = (self.width(), self.height())
            self.set_size(*self._side_window_size(*self._standing_size))
            self._keep_on_screen()
        elif motion != "side_lying" and self._standing_size is not None:
            size, self._standing_size = self._standing_size, None
            self.set_size(*size)
            self._keep_on_screen()

    def position_bottom_right(self):
        screen = self.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(max(area.left(), area.right() - self.width() - 19),
                  max(area.top(), area.bottom() - self.height() - 19))

    def set_background(self, bg_type):
        if bg_type.startswith("image:"):
            path = project_path(bg_type[6:])
            if not path.is_file() or QPixmap(str(path)).isNull():
                raise ValueError("背景图片不存在或无法读取")
            bg_type = "image:" + str(path)
        elif bg_type not in ("transparent", "purple") and not QColor(bg_type).isValid():
            raise ValueError("背景需要 transparent、purple、有效颜色或本地图片")
        self.background_frame.set_background(bg_type)
        self._current_background = bg_type

    def show_message(self, text, duration=5000):
        self.bubble_widget.show_message(text, duration)

    def set_model_form(self, form):
        forms = self.config["sprite"]["model"]["forms"]
        if form not in forms:
            raise ValueError("未知形态，需要 first 或 second")
        self._model_actions_ready(False)
        self.sprite_view.load_model(project_path(forms[form]))

    def _play_motion(self, group):
        if self.sprite_view.model_loaded:
            self.sprite_view.trigger_motion(group)

    def set_physics(self, enabled):
        self._physics_action.setChecked(enabled)
        self.sprite_view.set_physics(enabled)

    def _reset_physics(self):
        if self.sprite_view.model_loaded:
            self.sprite_view.reset_physics()

    def set_behavior(self, settings):
        self.sprite_view.set_behavior(settings)
        for key, action in getattr(self, "_companion_actions", {}).items():
            action.setChecked(self.sprite_view._behavior_settings[key])
        if "mouse_follow" in settings:
            self._follow_action.setChecked(settings["mouse_follow"])

    def _touch_reaction(self, part):
        names = {"head": "头部", "body": "身体", "hand": "手", "tail": "尾巴"}
        self.touch_event.emit("tap", names.get(part, "身体"))
        if self.sprite_view._behavior_settings["touch_reactions"]:
            # 触摸不会替换正在回复的文字，或取消已经排队的对话语音。
            if self.chat.busy or self.tts.snapshot()["active"] or self.voice_player.snapshot()["state"] != "StoppedState":
                return
            tier = self.mood.snapshot()["tier_index"]
            responses = FOND_TOUCH_REPLIES if tier >= 3 else TRUSTED_TOUCH_REPLIES if tier >= 2 else TOUCH_REPLIES
            replies = responses[self.tts.language]
            text = replies.get(part, replies["body"])
            self.show_message(text, 3000)
            if self.tts.enabled and self.tts.snapshot()["configured"] and time.monotonic() - self._last_spoken_touch >= 3:
                self._last_spoken_touch = time.monotonic()
                self.tts.speak(text)

    def _refresh_voice_menu(self):
        self._voice_enabled_action.setChecked(self.tts.enabled)
        for language, action in self._voice_language_actions.items():
            action.setChecked(language == self.tts.language)
        for engine, action in self._voice_engine_actions.items():
            action.setChecked(engine == self.tts.engine)
        self._voice_translate_action.setChecked(self.tts.auto_translate)
        self._voice_fallback_action.setChecked(self.tts.fallback)
        state = self.tts.snapshot()
        phases = {"queued": "准备语音…", "translating": "文本翻译中…", "synthesizing": "语音合成中…", "fallback": "备用音色合成中…"}
        ready = "心的音色已就绪" if self.tts.engine == "gptsovits" else "Edge 通用音色已就绪"
        self._voice_status_action.setText(phases.get(state["stage"], "语音合成中…") if state["synthesizing"] else
            ("语音出错，请查看日志" if state["error"] else state["warning"] or (ready if state["configured"] else "所选语音引擎尚未就绪")))
        self._voice_status_action.setToolTip(state["error"] or state["warning"] or "")

    def preview_voice(self):
        text = PREVIEW_PHRASES[self.tts.language]
        try:
            self.tts.speak(text)
        except ValueError as exc:
            self.show_message(str(exc), 4000)

    def read_text(self):
        text, accepted = QInputDialog.getMultiLineText(self, "让心朗读", "输入要朗读的文本（最多 500 字）：")
        if accepted and text.strip():
            try:
                self.tts.speak(text)
            except ValueError as exc:
                self.show_message(str(exc), 6000)

    def eventFilter(self, watched, event):
        if watched in (self.central_widget, self.sprite_view) and self._pointer_event(event):
            return True
        return super().eventFilter(watched, event)

    def _pointer_event(self, event):
        if self.is_click_through:
            return False
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._press_point = event.globalPosition().toPoint()
                self.drag_position = self._press_point - self.frameGeometry().topLeft()
                self._dragged = False
                self._sync_companion()
                return True
            if event.button() == Qt.MouseButton.RightButton:
                self._tray_menu.exec(event.globalPosition().toPoint())
                return True
        elif kind == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
            if self.drag_position is not None:
                point = event.globalPosition().toPoint()
                if (point - self._press_point).manhattanLength() >= QApplication.startDragDistance():
                    self._dragged = True
                if self._dragged:
                    self.move(point - self.drag_position)
                return True
        elif kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if self.drag_position is not None:
                if not self._dragged:
                    if self.sprite_view.renderer_name == "pmx":
                        point = self.sprite_view.mapFromGlobal(event.globalPosition().toPoint())
                        self.sprite_view.touch_at(point, self._touch_reaction)
                    else:
                        self.touch_event.emit("tap", "身体")
                self.drag_position = None
                self._sync_companion()
                return True
        return False

    def mousePressEvent(self, event):
        if not self._pointer_event(event):
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._pointer_event(event):
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self._pointer_event(event):
            super().mouseReleaseEvent(event)

    def open_pomodoro(self):
        if self.pomodoro_dialog is None:
            from src.ui.pomodoro_dialog import PomodoroDialog
            self.pomodoro_dialog = PomodoroDialog(self)
        self.pomodoro_dialog.open_near(self)

    def _pomodoro_finished(self, message):
        if self.pomodoro.phase == "focus" and self.pomodoro.completed_focus > self._mood_focus_count:
            self._mood_focus_count = self.pomodoro.completed_focus
            self.mood.interact("focus")
        if self.isVisible():
            self.show_message(message, 10000)
        if self.tray_icon:
            self.tray_icon.showMessage("心 · 番茄钟", message, QSystemTrayIcon.MessageIcon.Information, 10000)
        if self.pomodoro.settings["sound"]:
            QApplication.beep()

    def _mood_touch(self, action, part):
        if action == "tap" and getattr(self.sprite_view, "_behavior_settings", {}).get("touch_reactions", True):
            key = {"头部": "head", "身体": "body", "手": "hand", "尾巴": "tail"}.get(part)
            if key:
                self.mood.interact("touch", key)

    def _tick_mood(self):
        self.mood.tick(engaged=self.chat.busy or self.tts.snapshot()["active"] or
                       (self.pomodoro.state == "running" and self.pomodoro.phase == "focus"))

    def _sync_mood(self, *, force=False):
        value = self.mood.snapshot()
        if self.sprite_view.renderer_name == "pmx":
            self.sprite_view.set_mood(value["expression"], value["auto_expression"], force=force)
        if hasattr(self, "_mood_status_action"):
            self._mood_status_action.setText(f"{value['label']} · {value['tier']} · 好感度 {value['affection']}/100")
            self._mood_status_action.setToolTip(value["error"] or "")
            self._mood_auto_action.setChecked(value["auto_expression"])

    def configure_mood(self, enabled):
        try:
            self.mood.configure(enabled)
        except ValueError as exc:
            self._sync_mood()
            self.show_message(str(exc), 8000)

    def open_mood(self):
        if self.mood_dialog is None:
            from src.ui.mood_dialog import MoodDialog
            self.mood_dialog = MoodDialog(self)
        self.mood_dialog.open_near(self)

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "bubble_widget") and self.bubble_widget.isVisible():
            self.bubble_widget.reposition()

    def _restore_state(self):
        self.position_bottom_right()
        if not self._state_path.is_file():
            return
        try:
            state = json.loads(self._state_path.read_text(encoding="utf-8"))
            point = QPoint(int(state["x"]), int(state["y"]))
            if any(screen.availableGeometry().contains(point + QPoint(40, 40)) for screen in QApplication.screens()):
                self.move(point)
        except (OSError, ValueError, TypeError, KeyError):
            pass

    def save_state(self):
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {"x": self.x(), "y": self.y()}
        temp = self._state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(state), encoding="utf-8")
        temp.replace(self._state_path)

    def cleanup(self):
        self.save_state()
        self.mood.close()
        if self.mood_dialog:
            self.mood_dialog.close()
            self.mood_dialog.deleteLater()
        self.pomodoro.close()
        self.pomodoro_overlay.cleanup()
        if self.pomodoro_dialog:
            self.pomodoro_dialog.close()
            self.pomodoro_dialog.deleteLater()
        self.bubble_widget.hide_timer.stop()
        self.bubble_widget.close()
        self.stt.close()
        self.chat.close()
        if self.chat_dialog:
            self.chat_dialog.close()
        self.tts.close()
        self.voice_player.cleanup()
        self.sprite_view.cleanup()
        if self.tray_icon:
            self.tray_icon.hide()
        self._tray_menu.close()
        self._tray_menu.deleteLater()

    def closeEvent(self, event):
        self.quit_requested.emit()
        event.accept()
