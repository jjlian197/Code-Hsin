"""用本地 Three.js/MMDLoader 直接显示 PMX，Qt 保留窗口和拖动控制。"""
import json
import time

from loguru import logger
from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QCursor
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from src.core.app_config import project_path


class PmxBridge(QObject):
    ready = pyqtSignal()
    result = pyqtSignal(int, bool, str)
    runtime = pyqtSignal(str)
    motion_error = pyqtSignal(str)

    @pyqtSlot()
    def viewerReady(self):
        self.ready.emit()

    @pyqtSlot(int, bool, str)
    def modelResult(self, request_id, success, details):
        self.result.emit(request_id, success, details)

    @pyqtSlot(str)
    def runtimeStatus(self, details):
        self.runtime.emit(details)

    @pyqtSlot(str)
    def motionError(self, details):
        self.motion_error.emit(details)


class PmxPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        logger.warning("PMX [{}] {}:{} {}", level.name, source_id, line_number, message)


class PmxView(QWidget):
    renderer_name = "pmx"
    load_finished = pyqtSignal(bool)

    def __init__(self, model_path, parent=None, texture_overrides=None, animation_config=None):
        super().__init__(parent)
        self.model_path = model_path
        self.model_loaded = False
        self.current_expression = "normal"
        self.model_info = {}
        self.load_error = None
        self._ready = False
        self._closed = False
        self._request_id = 0
        self._texture_overrides = texture_overrides or {}
        self._animation_config = animation_config or {}
        self._physics_enabled = self._animation_config.get("physics", True)
        self._frame_pending = False
        self._behavior_settings = {"auto_blink": True, "breathing": True, "mouse_follow": True, "touch_reactions": True,
                                   **self._animation_config.get("behavior", {})}
        self._manual_gaze = None
        self._audio_input = {"value": 0.0, "active": False}
        self._audio_timestamp = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.web = QWebEngineView(self)
        page = PmxPage(self.web)
        self.web.setPage(page)
        page.setBackgroundColor(QColor(0, 0, 0, 0))
        self.web.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 鼠标留给外层 Qt 窗口，保证拖动、点击与右键菜单仍可用。
        self.web.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        settings = self.web.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.bridge = PmxBridge(self)
        self.bridge.ready.connect(self._viewer_ready)
        self.bridge.result.connect(self._model_result)
        self.bridge.runtime.connect(self._runtime_status)
        self.bridge.motion_error.connect(self._motion_error)
        self.channel = QWebChannel(page)
        self.channel.registerObject("pmxBridge", self.bridge)
        page.setWebChannel(self.channel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.web)
        self.label = QLabel("心正在准备…", self)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.label.setStyleSheet("color: #f6e9ce; background: #462535; border-radius: 12px; padding: 14px;")
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self._model_result(self._request_id, False, "加载超时，请查看 .runtime/hsin.log"))
        self.web.loadFinished.connect(self._page_loaded)
        self.web.renderProcessTerminated.connect(lambda *args: self._model_result(self._request_id, False, "渲染进程退出，请重新启动"))
        self.timer.start(45000)
        # 桌面工具窗口没有输入焦点，不能依赖网页的 requestAnimationFrame。
        self.frame_timer = QTimer(self)
        self.frame_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.frame_timer.setInterval(33)
        self.frame_timer.timeout.connect(self._advance_frame)
        self.web.load(QUrl.fromLocalFile(str(project_path("src/assets/pmx_viewer/index.html"))))

    def _advance_frame(self):
        if self._frame_pending or self._closed or not self.model_loaded or not self.isVisible():
            return
        self._frame_pending = True
        # 等前一帧完成再发送下一帧，避免物理较慢时堆积 JavaScript 命令。
        gaze = self._manual_gaze
        if gaze is None:
            point = self.mapFromGlobal(QCursor.pos())
            face = self.model_info.get("runtime", {}).get("interaction", {}).get("face", {"x": 0.5, "y": 0.22})
            gaze = {"x": max(-1.0, min(1.0, (point.x() / max(1, self.width()) - face["x"]) / 1.5)),
                    "y": max(-1.0, min(1.0, (face["y"] - point.y() / max(1, self.height())) / 0.9))}
        audio = dict(self._audio_input)
        if audio["active"] and time.monotonic() - self._audio_timestamp > 0.3:
            audio["value"] = 0.0
        inputs = {"pointer": {**gaze, "manual": self._manual_gaze is not None}, "audio": audio}
        self.web.page().runJavaScript(f"window.HsinPmx.tick(performance.now(), {json.dumps(inputs)});", self._frame_completed)

    def _frame_completed(self, result):
        self._frame_pending = False

    def _page_loaded(self, success):
        if not success:
            self._model_result(self._request_id, False, "本地渲染页面无法读取")

    def _viewer_ready(self):
        if self._closed:
            return
        self._ready = True
        try:
            self.load_model(self.model_path)
        except ValueError as exc:
            self._model_result(self._request_id, False, str(exc))

    def load_model(self, path):
        if not path or not path.is_file() or path.suffix.lower() != ".pmx":
            raise ValueError("需要存在的本地 PMX 模型")
        self.model_path = path
        self.model_loaded = False
        self.frame_timer.stop()
        self.model_info = {}
        self.load_error = None
        self.current_expression = "normal"
        self._request_id += 1
        self.label.setText("心正在准备…")
        self.label.show()
        self.timer.start(45000)
        if self._ready:
            url = QUrl.fromLocalFile(str(path)).toString(QUrl.ComponentFormattingOption.FullyEncoded)
            overrides = {}
            for source, target in self._texture_overrides.get(str(path), {}).items():
                target_path = project_path(target)
                if not target_path.is_file():
                    raise ValueError("贴图补全文件不存在：" + str(target_path))
                source_url = url[:url.rfind('/') + 1] + source.replace('\\', '/')
                overrides[source_url] = QUrl.fromLocalFile(str(target_path)).toString(QUrl.ComponentFormattingOption.FullyEncoded)
            options = {"physics": self._physics_enabled, "behavior": self._behavior_settings}
            self.web.page().runJavaScript(f"window.HsinPmx.loadModel({json.dumps(url)}, {self._request_id}, {json.dumps(overrides)}, {json.dumps(options)});")

    @pyqtSlot(int, bool, str)
    def _model_result(self, request_id, success, details):
        if self._closed or request_id != self._request_id:
            return
        self.timer.stop()
        self.model_loaded = success
        if success:
            self.model_info = json.loads(details)
            runtime = self.model_info.get("runtime", {})
            if runtime.get("physics_enabled") != self._physics_enabled:
                self.set_physics(self._physics_enabled)
            if runtime.get("behavior", {}).get("settings") != self._behavior_settings:
                self.set_behavior(self._behavior_settings)
            self.label.hide()
            self.web.page().runJavaScript(f"window.HsinPmx.setPaused({json.dumps(not self.isVisible())});")
            self.frame_timer.start()
            logger.info("PMX 已显示：{}，{}", self.model_path.name, self.model_info)
        else:
            self.frame_timer.stop()
            self.load_error = details
            self.label.setText("心暂时没能出现\n请重新启动，或查看运行日志。")
            self.label.show()
            logger.error("PMX 加载失败：{}", details)
        self.load_finished.emit(success)

    def get_available_expressions(self):
        return self.model_info.get("expressions", [])

    def set_expression(self, name):
        if name not in self.get_available_expressions():
            raise ValueError("此模型不支持该表情")
        self.web.page().runJavaScript(f"window.HsinPmx.setExpression({json.dumps(name)});")
        self.current_expression = name

    def get_available_motions(self):
        if not self.model_loaded:
            return []
        return self.model_info.get("motions", []) + list(self._animation_config.get("vmd", {}))

    def trigger_motion(self, group, index=0):
        if group == "tap":
            group = "wave"
        if group not in self.get_available_motions():
            raise ValueError("未知动作")
        url = None
        files = self._animation_config.get("vmd", {}).get(group)
        if files is not None:
            if not isinstance(files, list) or not 0 <= index < len(files):
                raise ValueError("动作 index 超出范围")
            path = project_path(files[index])
            if not path.is_file() or path.suffix.lower() != ".vmd":
                raise ValueError("需要配置存在的本地 VMD 文件")
            url = QUrl.fromLocalFile(str(path)).toString(QUrl.ComponentFormattingOption.FullyEncoded)
        elif index != 0:
            raise ValueError("基础动作只支持 index=0")
        self.model_info.pop("motion_error", None)
        self.web.page().runJavaScript(f"window.HsinPmx.playMotion({json.dumps(group)}, {json.dumps(url)});")
        return url is not None

    def set_physics(self, enabled):
        self._physics_enabled = enabled
        self.web.page().runJavaScript(f"window.HsinPmx.setPhysics({json.dumps(enabled)});")

    def reset_physics(self):
        self.web.page().runJavaScript("window.HsinPmx.resetPhysics();")

    def set_parameters(self, params):
        self.web.page().runJavaScript(f"window.HsinPmx.setParameters({json.dumps(params)});")

    def look_at(self, x, y):
        # 接口指定视线时保持该方向，直到显式恢复鼠标跟随。
        self._manual_gaze = {"x": x, "y": y}

    def set_behavior(self, settings):
        self._behavior_settings.update({k: v for k, v in settings.items() if k != "reset_parameters"})
        if "mouse_follow" in settings or settings.get("reset_parameters"):
            self._manual_gaze = None
        self.web.page().runJavaScript(f"window.HsinPmx.setBehavior({json.dumps(settings)});")

    def blink(self):
        self.web.page().runJavaScript("window.HsinPmx.blink();")

    def set_lip_sync(self, value, shape="a", duration=250):
        self.web.page().runJavaScript(f"window.HsinPmx.setLipSync({value}, {json.dumps(shape)}, {duration / 1000});")

    def audio_level(self, value, active):
        self._audio_input = {"value": value, "active": active}
        self._audio_timestamp = time.monotonic()

    def touch_at(self, point, callback):
        if not self.model_loaded:
            return
        request = self._request_id
        def touched(part):
            if not self._closed and self.model_loaded and request == self._request_id and part:
                callback(part)
        self.web.page().runJavaScript(f"window.HsinPmx.touchAt({point.x() / max(1, self.width())}, {point.y() / max(1, self.height())});", touched)

    def _runtime_status(self, details):
        if self.model_loaded and not self._closed:
            self.model_info["runtime"] = json.loads(details)

    def _motion_error(self, details):
        if not self._closed:
            self.model_info["motion_error"] = details
            logger.error("VMD 动作加载失败：{}", details)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.frame_timer.stop()
        if self._ready and not self._closed:
            self.web.page().runJavaScript("window.HsinPmx.setPaused(true);")

    def showEvent(self, event):
        super().showEvent(event)
        if self._ready and not self._closed:
            self.web.page().runJavaScript("window.HsinPmx.setPaused(false);")
            if self.model_loaded:
                self.frame_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.label.setGeometry(20, max(20, self.height() // 2 - 50), max(120, self.width() - 40), 100)

    def cleanup(self):
        self._closed = True
        self.timer.stop()
        self.frame_timer.stop()
        self.web.stop()
        self.web.page().runJavaScript("window.HsinPmx && window.HsinPmx.dispose();")
        self.web.close()
