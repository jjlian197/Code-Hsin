"""Windows 无控制台入口；常规日志就绪前保存启动异常。"""
import sys
from pathlib import Path
import traceback

try:
    from src.app import main
    raise SystemExit(main())
except Exception:
    from src.core.app_config import user_data_root
    error_log = (user_data_root() or Path(sys.executable).parent) / '.runtime/startup-error.log'
    error_log.parent.mkdir(parents=True, exist_ok=True)
    error_log.write_text(traceback.format_exc(), encoding='utf8')
    raise
