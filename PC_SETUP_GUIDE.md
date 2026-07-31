# WowAnalyzer PC별 설정 및 운영 가이드

이 문서는 집·회사·RTV 캡처·배포 PC처럼 여러 컴퓨터에서 WowAnalyzer를
운영할 때 **무엇을 공통으로 쓰고, 무엇을 PC마다 따로 설정해야 하는지**를
정리한다. 한 PC가 여러 역할을 맡으면 해당 역할의 설정을 합쳐서 적용한다.

## 핵심 원칙

1. Git은 코드와 검토된 소형 메타데이터를 공유한다.
2. R2는 대용량 캐시와 비공개 CCTV/전투로그를 공유한다.
3. GitHub HTTPS 인증, `.env`, `rclone.conf`, Cloudflare 로그인은 PC 로컬
   설정이며 Git으로 공유하지 않는다.
4. R2 Access Key는 PC마다 별도로 발급한다. 한 PC를 분실하면 그 PC의 키만
   폐기할 수 있어야 한다.
5. 공개판 사용자에게는 Worker URL만 전달한다. WCL, Blizzard, R2 자격 증명은
   전달하지 않는다.
6. 캐시 게시와 공개 리플레이 게시는 동시에 두 PC에서 실행하지 않는다.

## 역할별 설정표

| 설정 | 주 관리자·게시 PC | 보조 분석 PC | RTV 캡처 PC | Worker 배포 전용 PC | 공개판 사용자 PC |
|---|---:|---:|---:|---:|---:|
| GitHub HTTPS 인증 | 필요 | 필요 | 저장소 사용 시 필요 | 필요 | 불필요 |
| Git + Python 개발환경 | 필요 | 필요 | 스크립트 사용 시 필요 | Worker 저장소만 필요 | 불필요 |
| WCL/Blizzard `.env` | 필요 | 분석·메타 갱신 시 필요 | 불필요 | 불필요 | 금지 |
| PC별 R2 Access Key | 두 버킷 Read/Write | 캐시 동기화 시 두 버킷 Read/Write | CCTV 버킷 Read/Write | 불필요 | 금지 |
| `rclone` remote `r2` | 필요 | 필요 | 필요 | 불필요 | 불필요 |
| `WOW_LOG_DIR` | 실제 WoW 로그 경로 | 실제 WoW 로그 경로 | 입력 폴더가 다르면 선택 | 불필요 | 불필요 |
| `WARCRAFTCCTV_DIR` | 실제 CCTV 경로 | 실제 CCTV 경로 | `cctvlog` 사용 시 불필요 | 불필요 | 불필요 |
| `npx wrangler login` | Worker도 배포하면 필요 | Worker도 배포하면 필요 | 불필요 | 필요 | 불필요 |
| 공개 Worker URL | 빌드·검증 시 필요 | 공개판 빌드 시 필요 | 불필요 | 배포 후 기록 | 실행 시 필요 |

`주 관리자·게시 PC`는 공개 리플레이를 R2에 게시하는 단일 작성자다. 보조
분석 PC에서도 게시할 수는 있지만, 같은 시간에 두 PC가
`publish_public_replays.ps1`을 실행하면 안 된다.

## 공통 최초 설치

개발·분석 PC는 저장소를 받은 뒤 다음을 실행한다.

```powershell
git clone https://github.com/smk90402-wq/WowAnalyzer.git
Set-Location WowAnalyzer
python .\bootstrap_dev.py
```

GitHub 인증은 PC마다 Git Credential Manager 또는 GitHub CLI에 로그인한다.

```powershell
gh auth status
# 로그인 상태가 아닐 때만
gh auth login
```

`bootstrap_dev.py`는 Python 패키지와 `.env` 템플릿을 준비한다. 스크립트와
`PullLatest.bat`에 남아 있는 Git LFS 단계는 이전 저장소와의 호환용이다.
현재 `data/v2_cache_*.json` 대용량 캐시는 Git에서 제외되어 있으므로,
관리자·분석 PC는 R2 설정 후 별도로 `scripts\cache_pull.ps1`을 실행해야 한다.

공개판 사용자 PC는 저장소와 개발환경을 설치하지 않는다. 정제된
`dist\LogAnalyzePublic` 패키지만 받는다.

## 관리자·분석 PC 설정

### 1. API 자격 증명

저장소 루트에서 `.env.example`을 `.env`로 복사하고 다음 네 값을 채운다.

```dotenv
WCL_V2_CLIENT_ID=
WCL_V2_CLIENT_SECRET=
BLIZZARD_CLIENT_ID=
BLIZZARD_CLIENT_SECRET=
```

- WCL/Blizzard 애플리케이션 자격 증명은 신뢰하는 관리자 PC끼리 재사용할 수
  있지만 각 PC의 로컬 `.env`에만 둔다.
- `.env`와 `keys_local.txt`를 Git, OneDrive, 메신저에 올리지 않는다.
- 공개판 패키지에는 `.env`를 복사하지 않는다.

### 2. PC별 로컬 경로

기본값과 다른 위치를 사용하면 PC마다 아래 사용자 환경변수를 설정한다.

```powershell
[Environment]::SetEnvironmentVariable(
    'WOW_LOG_DIR',
    'D:\World of Warcraft\_retail_\Logs',
    'User'
)
[Environment]::SetEnvironmentVariable(
    'WARCRAFTCCTV_DIR',
    'D:\cctv',
    'User'
)
```

새 PowerShell 창부터 적용된다. 현재 창에서 바로 시험하려면 다음처럼 별도로
설정한다.

```powershell
$env:WOW_LOG_DIR = 'D:\World of Warcraft\_retail_\Logs'
$env:WARCRAFTCCTV_DIR = 'D:\cctv'
```

기본 경로는 다음과 같다.

- `WOW_LOG_DIR`: `C:\Program Files (x86)\World of Warcraft\_retail_\Logs`
- `WARCRAFTCCTV_DIR`: `E:\cctv`

### 3. PC별 R2 인증

각 PC에 rclone을 설치한다.

```powershell
winget install Rclone.Rclone
rclone config
```

Cloudflare에서 **PC마다 다른** R2 토큰을 만들고 다음 계약으로 등록한다.

- remote 이름: `r2`
- 저장소 타입: S3 compatible / Cloudflare R2
- endpoint: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`
- 관리자·분석 PC 권한: `wowanalyzer-cache`, `wowanalyzer-cctv`에 Object Read & Write
- RTV 캡처 PC 권한: 가능하면 `wowanalyzer-cctv`만 Object Read & Write
- 설정 파일 기본 위치: `%APPDATA%\rclone\rclone.conf`

portable 설정을 쓸 때만 그 PC에 `RCLONE_CONFIG`를 지정한다.

```powershell
[Environment]::SetEnvironmentVariable(
    'RCLONE_CONFIG',
    'D:\secure\rclone.conf',
    'User'
)
```

설정 확인:

```powershell
rclone listremotes
rclone lsf r2:wowanalyzer-cache --max-depth 1
rclone lsf r2:wowanalyzer-cctv --max-depth 1
```

`rclone listremotes`에 `r2:`가 보여야 한다. `rclone.conf`는 자격 증명 파일이므로
PC 사이에 복사하지 말고 각 PC에서 별도 토큰으로 다시 만든다.

### 4. PC를 옮겨 작업하는 순서

작업 시작:

```powershell
.\PullLatest.bat
.\scripts\cache_pull.ps1
# 원본 리플레이도 필요할 때만
.\scripts\cctv_pull.ps1
```

작업 종료:

```powershell
# 대용량 캐시를 실제로 갱신했을 때만
.\scripts\cache_push.ps1

git status --short
# 아래 경로 대신 실제로 검토한 파일만 명시한다.
git add -- README.md
git commit -m "작업 요약"
git push origin main
```

- `cache_pull.ps1`과 `cache_push.ps1`은 파일을 병합하지 않는다. 작업 시작 전에
  pull하고 끝난 뒤 push한다.
- 두 PC에서 같은 캐시를 동시에 갱신하지 않는다.
- Git 워킹 트리에 미커밋 변경이 있으면 `PullLatest.bat`이 의도적으로 중단된다.
- `data/cache_manifest.json`, `data/update_log.json`, `data/user_characters.json`처럼
  Git에 추적되는 파일은 일반 Git 커밋으로 동기화한다.

## RTV 캡처 PC 설정

RTV PC가 `바탕 화면\cctvlog`에 영상·JSON·전투로그를 모으는 경우 다음만
필요하다.

1. Git 또는 스크립트가 포함된 저장소 사본
2. rclone 설치
3. 그 PC 전용 R2 토큰과 remote 이름 `r2`
4. `wowanalyzer-cctv` 버킷 접근 권한

기본 폴더를 사용할 때:

```powershell
.\scripts\cctv_push_RTV.ps1
```

다른 폴더를 사용할 때:

```powershell
.\scripts\cctv_push_RTV.ps1 -SrcDir 'D:\cctvlog'
```

이 PC에는 WCL/Blizzard `.env`, Worker URL, Wrangler 로그인이 필요 없다.

## Cloudflare Worker 배포 PC 설정

Worker만 배포하는 PC는 Node.js 18 이상과 GitHub/Cloudflare 인증이 필요하다.
R2 Access Key나 `rclone.conf`는 필요 없다. Cloudflare가 `wrangler.jsonc`의
`PUBLIC_DATA` R2 binding을 Worker에 연결한다.

```powershell
Set-Location .\cloudflare\r2-public-gateway
npx wrangler login
npm test
npm run check
npx wrangler deploy --dry-run
```

실제 배포 권한이 있는 PC에서 검증이 끝난 뒤에만 실행한다.

```powershell
npx wrangler deploy
```

- 각 배포 PC는 `npx wrangler login`을 따로 수행한다.
- `.wrangler\`의 로그인 상태를 다른 PC로 복사하지 않는다.
- Worker 이름, binding 이름, 버킷 이름은 저장소의 `wrangler.jsonc`와 동일하게
  유지한다.
- 배포 후 Worker URL을 공개판 빌드 담당 PC에 전달한다. URL은 비밀값이 아니다.

## 공개판 빌드·사용자 PC 설정

공개판 빌드 PC는 Worker URL만 지정하고 별도 출력 폴더를 만든다.

```powershell
$env:WOWANALYZER_PUBLIC_REPLAY_BASE_URL = 'https://replays.example.com'
cmd /c build.bat --public
```

선택적인 별도 manifest가 있을 때만 아래 값을 추가한다.

```powershell
$env:WOWANALYZER_PUBLIC_REPLAY_MANIFEST_URL = `
    'https://replays.example.com/manifest.json'
```

URL을 빌드에 넣으면 사용자 PC는 추가 설정 없이 실행한다. URL을 나중에
설정하려면 `dist\LogAnalyzePublic\public_replay.json.example`을 같은 폴더의
`public_replay.json`으로 복사하고 `base_url`만 실제 Worker URL로 바꾼다.

공개판 사용자 PC에 없어야 하는 항목:

- `.env`, `keys_local.txt`
- `rclone.conf`, R2 Access Key
- WCL/Blizzard Client Secret
- `scripts\`와 Cache/CCTV Push/Pull 도구
- 로컬 `data` junction, 원본 전투로그, 비공개 CCTV mirror

공개 JSON 캐시 위치를 바꿔야 하는 특수 환경에서만
`WOWANALYZER_PUBLIC_REPLAY_CACHE_DIR`을 사용한다. 일반 사용자에게는 설정하지
않는다.

## 어떤 데이터가 어디로 동기화되는가

| 데이터 | 전달 경로 | 동시 작업 규칙 |
|---|---|---|
| 코드·문서·소형 메타데이터 | Git/GitHub | pull 후 수정, commit 후 push |
| `data/v2_cache_*.json`, 모델, HD 지도 | `r2:wowanalyzer-cache` | 시작 전 pull, 종료 후 push, 단일 작성자 |
| CCTV 영상·JSON·전투로그 | `r2:wowanalyzer-cctv` | copy 기반, 삭제 없음, 같은 파일 동시 갱신 금지 |
| 정제 공개 리플레이 | 같은 비공개 버킷의 `public/` | 게시 스크립트 한 PC만 실행 |
| 공개 앱 읽기 | Cloudflare Worker HTTPS | 자격 증명 없음 |

## PC별 로컬 기록표

아래 표에는 경로와 역할만 기록한다. Access Key, Client Secret, 토큰 값은
절대 문서에 적거나 커밋하지 않는다.

| 항목 | PC A | PC B | RTV PC |
|---|---|---|---|
| PC 별칭 |  |  |  |
| 역할 | 관리자·게시 | 보조 분석 | 캡처 업로드 |
| 저장소 경로 |  |  |  |
| `WOW_LOG_DIR` |  |  | 해당 없음 또는 입력 폴더 |
| `WARCRAFTCCTV_DIR` |  |  | `Desktop\cctvlog` |
| `RCLONE_CONFIG` | 기본값/별도 경로 | 기본값/별도 경로 | 기본값/별도 경로 |
| R2 토큰 식별용 이름 | 값이 아닌 토큰 이름만 | 값이 아닌 토큰 이름만 | 값이 아닌 토큰 이름만 |
| Wrangler 로그인 | 예/아니오 | 예/아니오 | 아니오 |
| Worker URL |  |  | 해당 없음 |

## PC별 최종 점검

관리자·분석 PC:

```powershell
git status --short --branch
python -m unittest discover -s tests -v
rclone listremotes
.\scripts\cache_pull.ps1
```

RTV 캡처 PC:

```powershell
rclone listremotes
.\scripts\cctv_push_RTV.ps1
```

Worker 배포 PC:

```powershell
Set-Location .\cloudflare\r2-public-gateway
npm run check
npx wrangler deploy --dry-run
```

공개판 사용자 PC에서 앱을 실행한 뒤:

```powershell
Invoke-RestMethod http://127.0.0.1:9876/api/public-replay/status
```

`release_mode`가 `true`여야 한다. URL을 설정한 배포본은 `configured`도
`true`여야 한다.

## 관련 문서

- [README.md](README.md): 개발환경과 데이터 파이프라인
- [PUBLIC_R2_DEPLOYMENT.md](PUBLIC_R2_DEPLOYMENT.md): 공개 R2/Worker 보안 경계와 게시 절차
- [cloudflare/r2-public-gateway/README.md](cloudflare/r2-public-gateway/README.md): Worker HTTP 계약과 배포
- [packaging/public_release.env.example](packaging/public_release.env.example): 공개 URL 환경변수 템플릿
