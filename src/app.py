"""独立的心桌面应用，负责窗口、本地服务与退出清理。"""
import argparse
import json
import os
import signal
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="心 · Hsin 桌面精灵")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--headless", action="store_true", help="使用离屏界面进行自动验证")
    parser.add_argument("--run-for", type=float, help="验证用：指定秒数后自动退出")
    parser.add_argument("--snapshot", help="验证用：导出窗口预览 PNG")
    args = parser.parse_args(argv)
    if args.headless:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from loguru import logger
    from PyQt6.QtCore import QLockFile, Qt, QTimer
    from PyQt6.QtWidgets import QApplication
    from src.core.app_config import load_config, project_path
    from src.core.control_bridge import ControlBridge
    from src.core.control_services import ControlServices
    from src.core.sprite_window import HsinSpriteWindow
    from src.utils.logger import setup_logging
    try:
        config = load_config(args.config)
        setup_logging(config)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Hsin 配置读取失败：{exc}", file=sys.stderr)
        return 1
    runtime = project_path(config["runtime"]["directory"])
    runtime.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(runtime / "hsin.lock"))
    if not lock.tryLock(0):
        logger.warning("此 Hsin 项目已经运行，跳过重复启动")
        return 0
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([sys.argv[0]])
    app.setApplicationName("HsinDesktopSprite")
    app.setOrganizationName("Hsin")
    from src.ui.app_icon import create_icon
    app.setWindowIcon(create_icon())
    app.setQuitOnLastWindowClosed(False)
    window = HsinSpriteWindow(config)
    bridge = ControlBridge(window)
    services = ControlServices(bridge, config)
    cleaned = False

    def cleanup():
        nonlocal cleaned
        if cleaned:
            return
        cleaned = True
        bridge.close()
        services.stop()
        window.cleanup()
        lock.unlock()
        logger.info("心桌面精灵已退出")

    app.aboutToQuit.connect(cleanup)
    window.quit_requested.connect(app.quit)
    window.touch_event.connect(lambda action, part: services.broadcast_sync("touch_event", {"action": action, "part": part}))
    window.tts.changed.connect(lambda: services.broadcast_sync("tts_status", window.tts.snapshot()))
    window.chat.changed.connect(lambda: services.broadcast_sync("chat_status", window.chat.snapshot()))
    window.stt.changed.connect(lambda: services.broadcast_sync("stt_status", window.stt.snapshot()))
    try:
        services.start()
    except RuntimeError as exc:
        logger.error("{}", exc)
        cleanup()
        return 1
    (runtime / "endpoints.json").write_text(json.dumps(services.endpoints(), indent=2), encoding="utf-8")
    window.show_sprite()
    logger.info("心桌面精灵已启动；渲染器：{}", window.sprite_view.renderer_name)
    if args.snapshot:
        target = project_path(args.snapshot)
        target.parent.mkdir(parents=True, exist_ok=True)
        def capture():
            window.grab().save(str(target))
        if hasattr(window.sprite_view, "load_finished"):
            window.sprite_view.load_finished.connect(lambda success: QTimer.singleShot(800, capture))
        else:
            QTimer.singleShot(500, capture)
    if args.run_for is not None:
        QTimer.singleShot(max(1, int(args.run_for * 1000)), app.quit)
    # 保持 Python 有机会处理 Ctrl+C；自然动作与鼠标采样由 PMX 视图帧循环管理。
    heartbeat = QTimer(app)
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(250)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    try:
        return app.exec()
    finally:
        cleanup()
