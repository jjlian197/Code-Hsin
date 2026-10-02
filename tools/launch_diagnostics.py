"""启动器无 GUI 预检；不输出连接凭据。"""
import importlib
import json
import sys


def main():
    try:
        for module in ("PyQt6.QtWidgets", "PyQt6.QtWebEngineWidgets", "PyQt6.QtMultimedia",
                       "aiohttp", "websockets", "yaml", "loguru", "edge_tts", "requests", "webrtcvad"):
            importlib.import_module(module)
        from src.core.app_config import load_config, project_path
        config = load_config()
        if config["sprite"]["renderer"] == "pmx" and not project_path(config["sprite"]["model"]["path"]).is_file():
            raise ValueError("找不到 PMX 模型，请在 config.local.yaml 配置 sprite.model.path")
        data = {"success": True, "python": sys.executable,
                "http_enabled": config["http"]["enabled"], "http_host": config["http"]["host"],
                "http_port": config["http"]["port"], "runtime": str(project_path(config["runtime"]["directory"]))}
    except Exception as error:
        data = {"success": False, "error": str(error)}
    print(json.dumps(data, ensure_ascii=True))
    return 0 if data["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
