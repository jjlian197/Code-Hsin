"""日志只写 Hsin 项目目录。"""
import sys
from loguru import logger
from src.core.app_config import project_path


def setup_logging(config):
    path = project_path(config["logging"]["file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.remove()
    if sys.stderr:
        logger.add(sys.stderr, level=config["logging"]["level"])
    logger.add(path, level=config["logging"]["level"], encoding="utf-8", rotation="10 MB", retention=5)
