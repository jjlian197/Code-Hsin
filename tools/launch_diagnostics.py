"""启动器无 GUI 预检；不输出连接凭据。"""
import importlib
import json
import sys


def main():
    try:
        for module in ("PyQt6.QtWidgets", "PyQt6.QtWebEngineWidgets", "PyQt6.QtMultimedia",
                       "aiohttp", "websockets", "yaml", "loguru", "edge_tts", "webrtcvad"):
            importlib.import_module(module)
        if importlib.util.find_spec("requests") is None:
            raise ValueError("缺少 requests，请安装 requirements.txt")
        from src.core.app_config import load_config, project_path
        config = load_config()
        data = {"success": True, "python": sys.executable,
                "model_file_exists": project_path(config["sprite"]["model"]["path"]).is_file(),
                "http_enabled": config["http"]["enabled"], "http_host": config["http"]["host"],
                "http_port": config["http"]["port"], "runtime": str(project_path(config["runtime"]["directory"]))}
    except Exception as error:
        data = {"success": False, "error": str(error)}
    print(json.dumps(data, ensure_ascii=True))
    return 0 if data["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
