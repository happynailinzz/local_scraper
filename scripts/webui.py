#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))

    project_dir = Path(__file__).resolve().parents[1]
    src_dir = project_dir / "src"
    sys.path.insert(0, str(src_dir))

    host = os.environ.get("WEBUI_HOST", "127.0.0.1")
    port = int(os.environ.get("WEBUI_PORT", "8000"))

    import uvicorn

    uvicorn.run(
        "local_scraper.web.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
