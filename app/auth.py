"""사용자 인증 — sqlite users + passlib + itsdangerous signed cookie.

설계:
- 운영자 (본인) 만 사용자 추가. /auth/register 는 없음 — CLI 로 추가.
- 패스워드는 bcrypt 해시. cookie 는 itsdangerous 로 서명 (변조 방지).
- 4명 정도 사용 예상이라 JWT 까지 안 가고 단순 signed session id.

사용 (FastAPI middleware):
    from app.auth import auth_required, login_user, current_user
"""
from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request, Response
from itsdangerous import URLSafeSerializer, BadSignature


# ── 셋업 ────────────────────────────────────────────────────────────────────

# DATA_DIR 은 app.main 에서 결정. 여기선 lazy lookup.
_DB_PATH: Optional[Path] = None
_SERIALIZER: Optional[URLSafeSerializer] = None
COOKIE_NAME = "wowanalyzer_session"
SESSION_TTL_SEC = 30 * 24 * 3600  # 30일


def init(data_dir: Path) -> None:
    """app.main 시작 시 1회 호출. DB 초기화 + secret 로드."""
    global _DB_PATH, _SERIALIZER
    _DB_PATH = data_dir / "users.db"
    # secret 키 — 첫 실행 시 생성, 이후 재사용. data/auth_secret 에 저장.
    secret_path = data_dir / "auth_secret"
    if secret_path.exists():
        secret = secret_path.read_text(encoding="utf-8").strip()
    else:
        secret = secrets.token_urlsafe(48)
        secret_path.write_text(secret, encoding="utf-8")
        try:
            # Windows ACL — POSIX chmod 와 다르지만 best-effort
            os.chmod(secret_path, 0o600)
        except Exception:
            pass
    _SERIALIZER = URLSafeSerializer(secret, salt="wowanalyzer-session")
    _ensure_schema()


def _conn() -> sqlite3.Connection:
    if _DB_PATH is None:
        raise RuntimeError("auth.init() 호출 안 됨")
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT NOT NULL UNIQUE,
                pw_hash     TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                last_login  TEXT
            )
        """)
        c.commit()


# ── 사용자 관리 (CLI / 인증 endpoint 에서 호출) ─────────────────────────────

def _hash(password: str) -> str:
    # bcrypt 입력 72바이트 제한 — 그 안에서 truncate.
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def _verify(password: str, hashed: str) -> bool:
    try:
        pw = password.encode("utf-8")[:72]
        return bcrypt.checkpw(pw, hashed.encode("utf-8"))
    except Exception:
        return False


def add_user(username: str, password: str) -> int:
    """신규 사용자. 중복 시 IntegrityError."""
    pw_hash = _hash(password)
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO users (username, pw_hash) VALUES (?, ?)",
            (username, pw_hash))
        c.commit()
        return cur.lastrowid


def delete_user(username: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM users WHERE username = ?", (username,))
        c.commit()
        return cur.rowcount > 0


def set_password(username: str, password: str) -> bool:
    pw_hash = _hash(password)
    with _conn() as c:
        cur = c.execute(
            "UPDATE users SET pw_hash = ? WHERE username = ?",
            (pw_hash, username))
        c.commit()
        return cur.rowcount > 0


def list_users() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT id, username, created_at, last_login FROM users").fetchall()
    return [dict(r) for r in rows]


def verify_login(username: str, password: str) -> Optional[dict]:
    """패스워드 검증. 성공 시 user dict, 실패 시 None."""
    with _conn() as c:
        row = c.execute(
            "SELECT id, username, pw_hash FROM users WHERE username = ?",
            (username,)).fetchone()
    if not row:
        return None
    if not _verify(password, row["pw_hash"]):
        return None
    # last_login 갱신
    with _conn() as c:
        c.execute(
            "UPDATE users SET last_login = datetime('now') WHERE id = ?",
            (row["id"],))
        c.commit()
    return {"id": row["id"], "username": row["username"]}


# ── 세션 cookie (signed) ───────────────────────────────────────────────────

def _make_token(user: dict) -> str:
    if _SERIALIZER is None:
        raise RuntimeError("auth.init() 호출 안 됨")
    return _SERIALIZER.dumps({"uid": user["id"], "u": user["username"]})


def _parse_token(token: str) -> Optional[dict]:
    if _SERIALIZER is None:
        return None
    try:
        return _SERIALIZER.loads(token)
    except BadSignature:
        return None


def set_session(response: Response, user: dict) -> None:
    token = _make_token(user)
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=SESSION_TTL_SEC,
        httponly=True,
        samesite="lax",
        # 로컬 / HTTP 환경에서도 동작. HTTPS 도입 시 secure=True 로 강화.
        secure=False,
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


def current_user(request: Request) -> Optional[dict]:
    """request 의 cookie 에서 user 추출. 없거나 invalid 면 None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return _parse_token(token)


# ── FastAPI 의존성 ──────────────────────────────────────────────────────────

def auth_required(request: Request) -> dict:
    """Depends 로 사용 — 인증 안 됐으면 401."""
    user = current_user(request)
    if not user:
        raise HTTPException(401, "로그인 필요")
    return user
