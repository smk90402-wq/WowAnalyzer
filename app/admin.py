"""사용자 관리 CLI.

사용법:
    python -m app.admin list
    python -m app.admin add <username> <password>
    python -m app.admin delete <username>
    python -m app.admin passwd <username> <new_password>
"""
from __future__ import annotations

import sys
from pathlib import Path

# data_dir 결정 — frozen vs dev
import os
if getattr(sys, "frozen", False):
    DATA_DIR = Path(sys.executable).parent / "data"
else:
    DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

from app import auth  # noqa: E402
auth.init(DATA_DIR)


def cmd_list() -> None:
    users = auth.list_users()
    if not users:
        print("(사용자 0명)")
        return
    print(f"{'id':>4} {'username':<20} {'created':<22} {'last_login':<22}")
    print("-" * 70)
    for u in users:
        print(f"{u['id']:>4} {u['username']:<20} {u['created_at']:<22} {u.get('last_login') or '-':<22}")


def cmd_add(username: str, password: str) -> None:
    try:
        uid = auth.add_user(username, password)
        print(f"OK — uid={uid} {username}")
    except Exception as e:
        print(f"실패: {e}")
        sys.exit(1)


def cmd_delete(username: str) -> None:
    if auth.delete_user(username):
        print(f"OK — {username} 삭제됨")
    else:
        print(f"NOT FOUND — {username}")
        sys.exit(1)


def cmd_passwd(username: str, password: str) -> None:
    if auth.set_password(username, password):
        print(f"OK — {username} 패스워드 변경됨")
    else:
        print(f"NOT FOUND — {username}")
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "list":
        cmd_list()
    elif cmd == "add" and len(args) == 2:
        cmd_add(*args)
    elif cmd == "delete" and len(args) == 1:
        cmd_delete(*args)
    elif cmd == "passwd" and len(args) == 2:
        cmd_passwd(*args)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
