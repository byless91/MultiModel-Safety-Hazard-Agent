"""Create/reset a login user: python -m app.cli.create_user --username admin --role admin."""

import argparse
import getpass
import sys
from collections.abc import Sequence

from app.core.db import SessionLocal, init_db
from app.core.security import ALL_ROLES, hash_password
from app.models import User


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="创建或重置系统用户（运维命令，无需 HTTP 登录）")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", default="inspector", choices=ALL_ROLES)
    password_args = parser.add_mutually_exclusive_group()
    password_args.add_argument("--password", default="", help="兼容旧脚本；自动化建议使用 --password-stdin")
    password_args.add_argument("--password-stdin", action="store_true", help="从标准输入读取一行密码")
    args = parser.parse_args(argv)
    password = (sys.stdin.readline().rstrip("\r\n") if args.password_stdin else
                args.password or getpass.getpass(f"为 {args.username} 设置密码（至少 8 位）："))
    if not args.username.strip() or len(args.username) > 64 or len(password) < 8:
        print("用户名需为 1–64 字符，密码至少 8 位", file=sys.stderr)
        return 1
    init_db()
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == args.username).first()
        action = "创建" if user is None else "重置"
        if user is None:
            user = User(username=args.username, password_hash=hash_password(password), role=args.role)
            db.add(user)
        else:
            user.password_hash = hash_password(password)
            user.role = args.role
        db.commit()
        print(f"已{action}用户 {args.username}（角色 {args.role}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
