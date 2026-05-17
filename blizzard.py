"""Blizzard Battle.net Game Data API 클라이언트.

REST API (V2 GraphQL 과 다름). OAuth2 client_credentials.
공식 한국어 로케일 (locale=ko_KR) 지원 — WoWhead 보다 권위 있음.

토큰: POST https://oauth.battle.net/token
데이터: https://{region}.api.blizzard.com/data/wow/...

us / eu / kr / tw 리전 있는데 ko_KR 데이터는 어느 리전에서도 받을 수 있음 (게임 글로벌 데이터).
us 기본 사용 (가장 안정).

레이트 리밋: 100/sec, 36k/hr (free, 매우 후함).
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("blizzard")

OAUTH = "https://oauth.battle.net/token"
REGION = "us"  # 게임 데이터는 글로벌, ko_KR locale 만 명시하면 됨
BASE = f"https://{REGION}.api.blizzard.com"
NAMESPACE = f"static-{REGION}"


class BlizzardError(RuntimeError):
    pass


class Blizzard:
    """REST 클라이언트 + 토큰 캐시 + ko_KR 디폴트."""

    def __init__(self, token_cache: Path | None = None) -> None:
        self.client_id = os.environ.get("BLIZZARD_CLIENT_ID")
        self.client_secret = os.environ.get("BLIZZARD_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            raise BlizzardError(
                "BLIZZARD_CLIENT_ID / SECRET 가 .env 에 없음."
            )
        self.token_cache = token_cache or (
            Path(__file__).parent / "data" / "cache_blizzard_token.json"
        )
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._load()

    def _load(self) -> None:
        if not self.token_cache.exists():
            return
        try:
            d = json.loads(self.token_cache.read_text(encoding="utf-8"))
            if d.get("client_id") != self.client_id:
                return
            self._token = d.get("token")
            self._expires_at = float(d.get("expires_at", 0))
        except Exception:
            pass

    def _save(self) -> None:
        self.token_cache.parent.mkdir(parents=True, exist_ok=True)
        self.token_cache.write_text(json.dumps({
            "client_id": self.client_id,
            "token": self._token,
            "expires_at": self._expires_at,
        }), encoding="utf-8")

    def _ensure_token(self) -> str:
        if self._token and time.time() < self._expires_at - 300:
            return self._token
        r = requests.post(
            OAUTH,
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
            timeout=30,
        )
        if r.status_code != 200:
            raise BlizzardError(f"OAuth 실패: {r.status_code}  body={r.text[:200]}")
        d = r.json()
        self._token = d["access_token"]
        self._expires_at = time.time() + int(d.get("expires_in", 86400))
        self._save()
        log.info("Blizzard 토큰 발급/갱신 (만료 %ds)", int(d.get("expires_in", 0)))
        return self._token

    def get(self, path: str, params: dict | None = None,
            locale: str = "ko_KR", retry: int = 5) -> dict | None:
        """/data/wow/... 같은 경로 (앞에 / 포함). 404 = None.

        다른 에러는 raise. 헤더와 토큰은 자동.
        """
        params = dict(params or {})
        params.setdefault("namespace", NAMESPACE)
        params.setdefault("locale", locale)
        for attempt in range(retry):
            token = self._ensure_token()
            try:
                r = requests.get(
                    f"{BASE}{path}",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                    timeout=30,
                )
            except requests.RequestException as e:
                log.warning("Blizzard 네트워크 err %s: %s", path, e)
                time.sleep(3 + attempt * 2)
                continue
            if r.status_code == 404:
                return None
            if r.status_code == 401:
                self._token = None
                self._expires_at = 0
                continue
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 5))
                log.warning("Blizzard 429, sleep %ds", wait)
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            try:
                r.raise_for_status()
                return r.json()
            except (ValueError, requests.RequestException) as e:
                log.warning("Blizzard parse err: %s", e)
                time.sleep(2)
                continue
        log.warning("Blizzard %s — %d 회 재시도 후 포기", path, retry)
        return None  # 영구 실패도 None 처리 (raise 대신)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cli = Blizzard()
    # 작동 확인용: spell 190984 = Wrath
    print("=== test: spell 190984 (Wrath) ko_KR ===")
    d = cli.get("/data/wow/spell/190984")
    if d:
        print(f"  name: {d.get('name')!r}  desc: {(d.get('description') or '')[:80]}")
    # journal-encounter 3306 = Chimaerus
    print("\n=== test: journal-encounter 2752 (recent boss) ===")
    # journal-encounter ID 와 WCL encounter ID 다름. 일단 모르겠어서 인덱스부터
    idx = cli.get("/data/wow/journal-instance/index")
    if idx:
        print(f"  instances count: {len(idx.get('instances', []))}")
        for inst in (idx.get("instances") or [])[:5]:
            print(f"    {inst.get('id')}: {inst.get('name')}")
