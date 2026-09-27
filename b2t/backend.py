"""Start the existing Web backend using project configuration."""

import os
import sys
from pathlib import Path

from b2t.config import load_config


def run_backend(config_path: str | None = None) -> None:
    import uvicorn

    config = load_config(config_path)
    web_root = Path(__file__).resolve().parents[1] / "web-ui"
    if not (web_root / "backend" / "main.py").is_file():
        raise FileNotFoundError("找不到 web-ui/backend/main.py，请在项目源码安装中运行")
    if config_path is not None:
        os.environ["B2T_CONFIG"] = str(Path(config_path).expanduser().resolve())
    if str(web_root) not in sys.path:
        sys.path.insert(0, str(web_root))
    uvicorn.run("backend.main:app", host=config.backend.host, port=config.backend.port)
