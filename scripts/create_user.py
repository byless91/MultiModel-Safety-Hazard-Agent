"""创建/重置登录用户（B4/WP2.1）。

用法（项目根目录）：
  .\\backend\\.venv\\Scripts\\python.exe scripts\\create_user.py --username admin --role admin
  密码未提供时交互式输入（不回显）。角色：admin / reviewer / inspector。
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.db import SessionLocal, init_db  # noqa: E402
from app.core.security import ALL_ROLES, hash_password  # noqa: E402
from app.models import User  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="创建或重置系统用户")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", default="inspector", choices=ALL_ROLES)
    parser.add_argument("--password", default="", help="不提供则交互式输入")
    args = parser.parse_args()

    password = args.password or getpass.getpass(f"为 {args.username} 设置密码（至少 8 位）：")
    if len(password) < 8:
        print("密码至少 8 位", file=sys.stderr)
        return 1

    init_db()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == args.username).first()
        if user is None:
            user = User(username=args.username, password_hash=hash_password(password), role=args.role)
            db.add(user)
            action = "创建"
        else:
            user.password_hash = hash_password(password)
            user.role = args.role
            action = "重置"
        db.commit()
        print(f"已{action}用户 {args.username}（角色 {args.role}）")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
