"""创建/重置登录用户（B4/WP2.1）。

用法（项目根目录）：
  .\\backend\\.venv\\Scripts\\python.exe scripts\\create_user.py --username admin --role admin
  密码未提供时交互式输入（不回显）。角色：admin / reviewer / inspector。
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.cli.create_user import main

if __name__ == "__main__":
    raise SystemExit(main())
