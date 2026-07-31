# 공개 리플레이 R2 배포 인수인계

이 문서는 WowAnalyzer 공개 릴리즈가 R2 비밀키 없이 분석 자료를 읽도록
배포하는 절차를 정리한다. 기존 `wowanalyzer-cctv` 버킷은 비공개로 유지하고,
Cloudflare Worker가 공개 허용 경로만 대신 읽어 주는 구조를 사용한다.

## 보안 경계

```text
관리자 PC
  └─ rclone + R2 쓰기 자격 증명
       └─ 비공개 R2: wowanalyzer-cctv
            ├─ logs/, cctv/                     비공개 원본
            ├─ public/manifest.json              공개 목록
            ├─ public/replays/<id>/detail.json   공개 분석
            ├─ public/replays/<id>/frames.json   공개 프레임
            ├─ public/replays/<id>/terrain.json  공개 지형
            └─ _internal/public_video_map.json   Worker 전용 영상 매핑
                         │
                         ▼
                 Cloudflare Worker
                    허용된 GET/HEAD만
                         │
                         ▼
                  공개 WowAnalyzer
                    자격 증명 없음
```

- R2 버킷 자체의 Public Access는 켜지 않는다.
- `rclone.conf`, R2 Access Key, WCL/Blizzard 비밀키는 공개 빌드와 Git에
  넣지 않는다.
- Worker는 객체 목록 API를 외부에 제공하지 않는다.
- `logs/`, `cctv/`, `_internal/` 및 임의 R2 key 요청은 반드시 거부한다.
- `_internal/public_video_map.json`은 Worker가 영상 ID를 실제 비공개 객체에
  매핑할 때만 읽으며, 응답 본문으로 반환하지 않는다.

내부 영상 매핑 형식은 다음과 같다. 값은 같은 버킷의 안전한 단일
`cctv/*.mp4` key만 허용한다.

```json
{
  "schemaVersion": 1,
  "videos": {
    "0123456789abcdef01234567": "cctv/original-capture.mp4"
  }
}
```

## 여러 PC에서 운영하기

역할별 전체 설정표와 최초 설치·일상 동기화 체크리스트는
[PC_SETUP_GUIDE.md](PC_SETUP_GUIDE.md)를 함께 참고한다.

`git pull`과 R2/Cloudflare 인증은 서로 독립이다. 다른 PC에서 저장소를
받아도 R2 비밀키와 Cloudflare 로그인은 자동으로 따라오지 않으며, 각 PC에서
아래 항목을 최초 1회만 설정한다.

1. GitHub HTTPS 인증은 Git Credential Manager로 로그인한다.
2. R2 토큰은 PC마다 별도로 만들고 `wowanalyzer-cctv`와
   `wowanalyzer-cache` 두 버킷에만 Object Read & Write 권한을 준다.
   각 PC의 `%APPDATA%\rclone\rclone.conf`에 같은 remote 이름 `r2`로
   등록한다.
3. Worker 코드도 두 PC에서 배포한다면 각 PC에서 `npx wrangler login`
   을 한 번 실행한다. Worker의 R2 binding은 rclone Access Key를 사용하지
   않는다.
4. 공개 릴리즈를 빌드하거나 사용하는 PC에는 Worker URL만 필요하고 R2
   토큰은 필요 없다.

`rclone.conf`는 secret이 가려져 보여도 자격 증명 파일이므로 Git,
OneDrive, 메신저로 공유하지 않는다. PC별 토큰을 쓰면 분실한 PC의
토큰만 폐기할 수 있다. 두 PC에서 `publish_public_replays.ps1`을 동시에
실행하지 않는다.

cache 파일은 자동 병합되지 않는다. PC를 옮길 때는 작업 시작 전에
`scripts\cache_pull.ps1`, 작업이 끝난 뒤 `scripts\cache_push.ps1` 순서를
지키고 두 PC에서 동시에 push하지 않는다. 특히 `cache.db`는 SQLite 단일
파일이므로 동시에 수정하면 한쪽 변경이 덮일 수 있다.

## 외부 HTTP 계약

Worker가 외부에 제공하는 경로는 아래로 제한한다.

| 메서드 | 공개 경로 | R2 동작 |
|---|---|---|
| `GET`, `HEAD` | `/manifest.json` | `public/manifest.json` |
| `GET`, `HEAD` | `/replays/<id>/detail.json` | 같은 ID의 공개 detail |
| `GET`, `HEAD` | `/replays/<id>/frames.json` | 같은 ID의 공개 frames |
| `GET`, `HEAD` | `/replays/<id>/terrain.json` | 같은 ID의 공개 terrain |
| `GET`, `HEAD` | `/videos/<id>` | 내부 영상 매핑을 거쳐 비공개 영상 스트리밍 |

그 밖의 메서드와 경로는 `404` 또는 `405`로 응답한다. `<id>`는 게시 도구가
생성한 소문자 24자리 hex(`[a-f0-9]{24}`)만 허용하고, 슬래시·`..`·임의
파일명·URL 디코딩 후 경로 탈출은 거부한다. 영상 응답은 재생 탐색을 위해
`Range`, `Content-Range`,
`Accept-Ranges`, `Content-Length`, 올바른 `Content-Type`을 보존해야 한다.

`manifest.json`은 버전 1 형식을 사용한다. 각 공개 row의
`public_artifacts`가 detail, frames, terrain 및 video 공개 경로를 가리킨다.
클라이언트가 R2 내부 key를 조합하지 않도록 모든 참조는 Worker 기준 경로로
기록한다. 참조값은 선행 `/`가 없는 상대경로여야 하며, 절대 URL, 쿼리,
fragment 및 `..` 경로는 허용하지 않는다.

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

실제 row에는 목록 화면에 필요한 보스, 시작 시각, 전투 시간 등의 공개
메타데이터가 함께 들어간다. `public_artifacts`의 키 이름과
`schema_version: 1`은 클라이언트 계약이므로 임의로 바꾸지 않는다.

## 게시 순서

목록이 아직 올라가지 않은 객체를 가리키는 시간을 막기 위해 아래 순서를
지킨다.

1. 관리자 PC에서 공개 exporter를 실행해 임시 폴더에 정제 산출물을 만든다.
2. 산출물에 원본 전투로그, R2 자격 증명, 로컬 절대경로가 없는지 검사한다.
3. `public/replays/<id>/`의 JSON을 먼저 업로드하고, 영상 매핑이 가리키는
   비공개 `cctv/` 객체가 실제로 존재하는지 확인한다.
4. `_internal/public_video_map.json`을 갱신한다.
5. 모든 공개 URL을 확인한 뒤 `public/manifest.json`을 마지막에 교체한다.

관리자 PC에서는 검증과 게시 순서를 묶은 스크립트를 사용한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\publish_public_replays.ps1
```

이 스크립트는 exporter 실행, 모든 영상 key의 R2 존재 확인, replay JSON
checksum 검증, 기존·신규 영상 map 합집합 게시, manifest 마지막 교체 및
재확인을 수행한다. manifest 검증이 실패하면 이전 manifest를 복원한다.
`--output`과 `--private-video-map`을 직접 사용하는 exporter 모드는 진단용이며,
private map은 어떤 경우에도 공개 prefix에 넣지 않는다.

삭제도 반대 순서로 수행한다. 먼저 새 manifest에서 row를 제거하고, 캐시가
갱신된 뒤 더 이상 참조되지 않는 map 항목과 산출물을 정리하고 해당 CDN URL도
purge한다. 기존 `scripts/cctv_push*.ps1` 및 `scripts/cctv_pull.ps1`은 비공개
원본 백업용이며 공개 게시 도구가 아니다.

## Worker와 캐시 설정

- Worker에 기존 비공개 R2 버킷을 binding하고 외부 라우팅은 위 allowlist로
  구현한다. Cloudflare-managed domain이 없는 계정은 먼저
  `https://wowanalyzer-r2-public-gateway.<계정-subdomain>.workers.dev`를
  사용하고, 나중에 Worker Custom Domain으로 교체할 수 있다.
- 공개 앱 origin에서 직접 요청한다면 `GET`, `HEAD` CORS를 허용한다.
  허용 origin은 실제 배포 origin으로 좁히고 로컬 검증이 필요하면
  `http://127.0.0.1:9876`을 추가한다.
- manifest는 짧은 캐시 또는 재검증을 사용하고, ID가 바뀌는 불변 산출물은
  긴 캐시를 사용할 수 있다.
- CORS 변경 뒤 기존 캐시 응답에 헤더가 남아 있으면 해당 hostname 캐시를
  purge한 뒤 다시 확인한다.

Cloudflare 공식 참고:

- [R2 Public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/)
- [R2 CORS](https://developers.cloudflare.com/r2/buckets/cors/)
- [Workers R2 API](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/)

## 앱 설정

공개 읽기는 빌드 시 아래 두 환경변수를 사용한다.

```dotenv
WOWANALYZER_PUBLIC_REPLAY_BASE_URL=https://replays.example.com
# 선택: 기본값은 <base URL>/manifest.json
WOWANALYZER_PUBLIC_REPLAY_MANIFEST_URL=https://replays.example.com/manifest.json
```

템플릿은 `packaging/public_release.env.example`이며 실제 비밀값은 없다.
`build.bat --public`은 base URL이 설정되어 있으면 공개 패키지 루트에
비밀값이 없는 `public_replay.json`을 생성한다. 실행 파일을 받은 사용자는
별도 설정이나 R2 자격 증명이 필요 없다. URL이 정해지기 전의 검증 빌드는
`public_replay.json.example`만 포함하며 공개 서버 연결은 비활성화된다.
manifest override는 CDN 버전 전환이나 검증용 manifest를 사용할 때만 지정한다.

## 빌드 분리

```bat
build.bat
```

기존 개인·관리자용 `dist\LogAnalyze`를 만든다. 현재 동작을 보존하므로 로컬
`.env`, 관리자 sync 스크립트, R2 더블클릭 래퍼가 포함될 수 있으며 외부에
배포하면 안 된다.

```bat
set WOWANALYZER_PUBLIC_REPLAY_BASE_URL=https://replays.example.com
build.bat --public
```

공개용 `dist\LogAnalyzePublic`을 별도로 만든다.

- 로컬 `.env`를 복사하지 않는다.
- `scripts/`, Cache/CCTV Push/Pull 래퍼를 넣지 않는다.
- `data/` junction을 만들지 않는다.
- `packaging/public_data_allowlist.txt`에서 명시적으로 검토한 정적 자료만
  복사한다. Git 추적 여부만으로 공개 가능하다고 간주하지 않는다.
- 개인 캐릭터, 원시 랭킹, report ID/캐릭터명이 든 보스 통계, 로컬 경로가
  든 분석·추천·업데이트 자료는 포함하지 않는다.
- ignored 로컬 DB, 인증 secret, R2 mirror, 생성형 maps/icons는 포함되지
  않았는지 빌드 마지막에 다시 검사한다.

배포 전에는 최소한 아래를 확인한다.

```powershell
Test-Path dist\LogAnalyzePublic\.env
Test-Path dist\LogAnalyzePublic\scripts
Get-Item dist\LogAnalyzePublic\data | Select-Object Attributes, LinkType
Invoke-RestMethod https://replays.example.com/manifest.json
```

앞의 두 결과는 `False`, `data`의 `LinkType`은 비어 있어야 한다.

## 릴리즈 검증 체크리스트

- [ ] 공개 Worker에서 `/manifest.json`이 버전 1 JSON으로 반환된다.
- [ ] manifest의 모든 `public_artifacts` URL이 `200` 또는 영상 `206`으로
      응답한다.
- [ ] `/logs/`, `/cctv/`, `/_internal/` 및 임의 key가 노출되지 않는다.
- [ ] 공개 PC에 `rclone.conf`가 없어도 리플레이 목록과 재생이 동작한다.
- [ ] 공개 산출물에 원본 로그, GUID, 로컬 절대경로, API/R2 secret이 없다.
- [ ] 2분 미만 및 르우라 전용 보존 정책이 manifest 생성 단계에도 적용된다.
- [ ] `dist\LogAnalyzePublic`에 `.env`와 관리자 sync 도구가 없다.
