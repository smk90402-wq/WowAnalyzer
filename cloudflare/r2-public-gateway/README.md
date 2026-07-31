# WowAnalyzer R2 공개 게이트웨이

기존 비공개 `wowanalyzer-cctv` R2 버킷 앞에서 **정제된 분석 산출물과
승인된 영상만** 익명 읽기로 제공하는 Cloudflare Worker입니다. 원본 전투로그,
원본 파일명과 업로드 권한은 공개하지 않습니다.

## 보안 경계

버킷 자체의 Public Access(`r2.dev`와 R2 custom domain)는 켜지 않습니다. Worker에
private R2 binding을 연결하고 기존 버킷을 다음처럼 사용합니다.

```text
logs/...                         # 비공개: Worker에서 접근 불가
_internal/public_video_map.json  # 비공개: 공개 ID -> cctv 원본 영상 키
public/manifest.json             # 공개 목록
public/replays/<24hex>/detail.json
public/replays/<24hex>/frames.json
public/replays/<24hex>/terrain.json
cctv/<original>.mp4              # map에 등재된 영상만 /videos/<id>로 공개
```

Worker가 제공하는 읽기 경로는 세 가지뿐입니다. manifest가 공개 목록이며
버킷 list API는 제공하지 않습니다.

| 요청 | R2 키/동작 |
| --- | --- |
| `GET /manifest.json` | `public/manifest.json` |
| `GET /replays/<id>/detail.json` | 같은 ID의 공개 detail |
| `GET /replays/<id>/frames.json` | 같은 ID의 공개 frames |
| `GET /replays/<id>/terrain.json` | 같은 ID의 공개 terrain |
| `GET /videos/<replay-id>` | private map에서 승인된 `cctv/<original>.mp4` |

`HEAD`도 지원합니다. `OPTIONS`는 CORS preflight 전용입니다. 다른 경로는 모두
`404`, `POST`/`PUT`/`PATCH`/`DELETE`는 `405`이며 쓰기 R2 API는 코드에 없습니다.
`/_internal/*`, `/logs/*`, `/cctv/*`, `/public/*` 직접 접근은 모두 차단합니다.
`<id>`와 `<replay-id>`는 exporter가 생성한 소문자 24자리 hex
(`[a-f0-9]{24}`)만 허용합니다. 따라서 `/replays/` 아래라도 임의 파일명,
추가 디렉터리, 다른 JSON 이름은 공개되지 않습니다.

## Manifest v1 계약

`public/manifest.json`은 exporter가 생성하는 다음 v1 layout을 그대로 제공합니다.
각 `public_artifacts` 값은 선행 `/`가 없는 Worker 기준 상대 경로입니다.

```json
{
  "schema_version": 1,
  "generated_at": "2026-07-31T00:00:00Z",
  "rows": [
    {
      "id": "0123456789abcdef01234567",
      "public_artifacts": {
        "detail": "replays/0123456789abcdef01234567/detail.json",
        "frames": "replays/0123456789abcdef01234567/frames.json",
        "terrain": "replays/0123456789abcdef01234567/terrain.json",
        "video": "videos/0123456789abcdef01234567"
      }
    }
  ],
  "stats": {
    "replays": 1,
    "videos": 1,
    "terrain": 1
  }
}
```

지형이 없는 row의 `terrain`, 영상이 없는 row의 `video`는 `null`입니다.
manifest에 기록되지 않은 R2 key를 클라이언트가 조합해서 요청하지 않습니다.

private map 형식은 다음과 같습니다. 공개 ID는 manifest의
`public_artifacts.video`에 사용하고, 값은 같은 버킷의 단일 `cctv/*.mp4`
key만 허용합니다.

```json
{
  "schemaVersion": 1,
  "videos": {
    "0123456789abcdef01234567": "cctv/original-capture-name.mp4"
  }
}
```

## HTTP 동작

- 단일 `Range: bytes=...` 요청을 `206`과 `Content-Range`로 응답합니다.
- `ETag`, `If-None-Match`, `If-Range`, `Last-Modified`, `HEAD`를 지원합니다.
- 각 replay/video 요청마다 최신 manifest membership을 확인할 수 있도록
  gateway의 Workers Caching은 끕니다. 브라우저·일반 HTTP 캐시용
  `Cache-Control`은 산출물을 저장하되 매 요청 재검증하도록 적용하고,
  manifest에는 짧은 TTL을 적용합니다. Worker가 단일 Range 요청을 직접
  처리합니다.
- 기본 CORS는 공개 읽기용 `*`입니다. `CORS_ALLOW_ORIGINS`에 쉼표로 구분한
  출처를 넣으면 allowlist로 전환됩니다.
- 저장된 R2 HTTP metadata를 사용하되, manifest의 Content-Type과 공개 캐시
  정책은 Worker 설정이 우선합니다.

공개 승인을 철회한 ID는 다음 Worker 요청부터 manifest 검사에서 거부됩니다.
별도의 CDN 또는 Cache Everything 규칙을 앞에 둘 경우에는 Worker를 우회하지
않도록 구성해야 하며, 같은 URL의 파일을 교체했다면 해당 외부 캐시도
purge해야 합니다.

## 로컬 검증

Node.js 18 이상만 있으면 Worker 단위 테스트를 실행할 수 있습니다.

```powershell
cd cloudflare\r2-public-gateway
npm test
npm run check
```

테스트는 private 경로 차단, private video map, Range/ETag/HEAD, CORS, 쓰기
메서드 차단을 가짜 R2 binding으로 검증합니다.

Wrangler 인증 상태와 배포 번들만 확인하려면 다음을 사용합니다. 두 명령 모두
실제 배포를 하지 않습니다.

```powershell
npx wrangler whoami
npx wrangler deploy --dry-run
```

## 배포 전 설정

1. `wrangler.jsonc`의 R2 binding은 `wowanalyzer-cctv`를 사용합니다.
2. 별도 Cloudflare 도메인이 없으면 `workers_dev: true`를 유지해
   `https://wowanalyzer-r2-public-gateway.<계정-subdomain>.workers.dev`를
   사용합니다.
3. 나중에 custom domain을 쓸 때만 `workers_dev: false`로 바꾸고 다음 형태의
   route를 추가합니다.

   ```jsonc
   "routes": [
     { "pattern": "replays.example.com", "custom_domain": true }
   ]
   ```

4. 공개 앱의 출처만 허용하려면 `CORS_ALLOW_ORIGINS`를 바꿉니다. 데스크톱 앱처럼
   `Origin`이 일정하지 않은 공개 클라이언트는 `*`를 유지합니다.
5. 업로더에서 manifest v1 `public/manifest.json`, ID별 detail/frames/terrain,
   `_internal/public_video_map.json`을 생성합니다. 원본 영상은 기존 `cctv/`에
   그대로 두고 공개할 ID만 map에 등재합니다.
6. private 버킷의 `r2.dev` Public Access가 꺼져 있는지 다시 확인합니다.
7. `npm test`와 `npx wrangler deploy --dry-run`을 통과한 뒤에만 사람이
   `npx wrangler deploy`를 실행합니다.

`wrangler.jsonc`에는 binding 이름과 일반 설정만 있으며 API 토큰, access key,
secret key는 저장하지 않습니다. Worker의 R2 binding도 별도 R2 access key 없이
Cloudflare가 런타임에 주입합니다.

## 참고

- [R2 Workers API](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/)
- [R2 public bucket 주의사항](https://developers.cloudflare.com/r2/buckets/public-buckets/)
- [Workers Caching 설정](https://developers.cloudflare.com/workers/cache/configuration/)
