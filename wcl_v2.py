"""WarcraftLogs V2 GraphQL 클라이언트.

V2는 OAuth2 client_credentials grant 를 쓴다:
  POST https://www.warcraftlogs.com/oauth/token
       Basic auth = client_id:client_secret
       body: grant_type=client_credentials
       => {access_token, expires_in}

이후 모든 GraphQL 요청:
  POST https://www.warcraftlogs.com/api/v2/client
       Authorization: Bearer <token>
       body: {"query": "...", "variables": {...}}

토큰 캐시: data/cache_v2_token.json  (만료 5분 전 자동 재발급)

레이트리밋: 포인트 기반 (응답에 X-RateLimit-* 헤더). 응답에 rateLimitData
오브젝트도 들어있어 매번 잔량 알 수 있음. 429 도 발생 가능.

사용 예:
  from wcl_v2 import WCLV2
  cli = WCLV2()
  res = cli.query('''
    query($id: Int!) {
      worldData { encounter(id: $id) { name } }
    }
  ''', {'id': 3306})
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

OAUTH = "https://www.warcraftlogs.com/oauth/token"
GRAPHQL = "https://www.warcraftlogs.com/api/v2/client"

log = logging.getLogger("wcl_v2")


class WCLV2Error(RuntimeError):
    pass


class WCLV2:
    """V2 GraphQL 클라이언트 — 토큰 자동 관리 + 429 대기."""

    def __init__(self, token_cache: Path | None = None) -> None:
        self.client_id = os.environ.get("WCL_V2_CLIENT_ID")
        self.client_secret = os.environ.get("WCL_V2_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            raise WCLV2Error(
                "WCL_V2_CLIENT_ID / WCL_V2_CLIENT_SECRET 가 .env 에 없음. "
                "https://www.warcraftlogs.com/api/clients 에서 발급."
            )
        self.token_cache = token_cache or (
            Path(__file__).parent / "data" / "cache_v2_token.json"
        )
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._load_cached_token()

    # ── OAuth ─────────────────────────────────────────────────────────────
    def _load_cached_token(self) -> None:
        if not self.token_cache.exists():
            return
        try:
            d = json.loads(self.token_cache.read_text(encoding="utf-8"))
            if d.get("client_id") != self.client_id:
                return  # 다른 client 의 토큰이면 무시
            self._token = d.get("token")
            self._expires_at = float(d.get("expires_at", 0))
        except Exception:
            pass

    def _save_token(self) -> None:
        self.token_cache.parent.mkdir(parents=True, exist_ok=True)
        self.token_cache.write_text(
            json.dumps({
                "client_id": self.client_id,
                "token": self._token,
                "expires_at": self._expires_at,
            }),
            encoding="utf-8",
        )

    def _ensure_token(self) -> str:
        # 만료 5분 전 갱신
        if self._token and time.time() < self._expires_at - 300:
            return self._token
        r = requests.post(
            OAUTH,
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
            timeout=30,
        )
        if r.status_code != 200:
            raise WCLV2Error(f"OAuth 실패: {r.status_code}  body={r.text[:200]}")
        d = r.json()
        self._token = d["access_token"]
        self._expires_at = time.time() + int(d.get("expires_in", 3600))
        self._save_token()
        log.info("V2 토큰 발급/갱신 (만료 %ds 후)", int(d.get("expires_in", 0)))
        return self._token

    # ── GraphQL ───────────────────────────────────────────────────────────
    def query(self, query: str, variables: dict | None = None,
              retry: int = 5) -> dict:
        """GraphQL 쿼리. data 부분만 리턴. 에러는 raise."""
        for attempt in range(retry):
            token = self._ensure_token()
            r = requests.post(
                GRAPHQL,
                headers={"Authorization": f"Bearer {token}"},
                json={"query": query, "variables": variables or {}},
                timeout=60,
            )
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 30))
                log.warning("V2 429, sleep %ds", wait)
                time.sleep(wait)
                continue
            if r.status_code == 401:
                # 토큰이 만료된 듯 — 강제 재발급 후 재시도
                self._token = None
                self._expires_at = 0
                continue
            if r.status_code >= 500:
                wait = 5 * (attempt + 1)
                log.warning("V2 %d, retry in %ds", r.status_code, wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            payload = r.json()
            if "errors" in payload:
                raise WCLV2Error(f"GraphQL errors: {payload['errors']}")
            return payload.get("data", {})
        raise WCLV2Error(f"V2 query 포기: {retry}회 재시도 실패")

    # ── 편의: 현재 rate limit 잔량 ────────────────────────────────────────
    def points_left(self) -> dict | None:
        """rateLimitData 쿼리로 잔량 조회."""
        try:
            data = self.query("""
                query {
                  rateLimitData {
                    limitPerHour
                    pointsSpentThisHour
                    pointsResetIn
                  }
                }
            """)
            return data.get("rateLimitData")
        except Exception:
            log.exception("rate limit 조회 실패")
            return None


if __name__ == "__main__":
    # python wcl_v2.py  — 인증 + 잔량만 출력
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cli = WCLV2()
    info = cli.points_left()
    if info:
        print(f"limit per hour: {info['limitPerHour']}")
        print(f"spent this hour: {info['pointsSpentThisHour']}")
        print(f"reset in: {info['pointsResetIn']} sec")
    else:
        print("잔량 조회 실패")
