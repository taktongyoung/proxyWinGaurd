**모든 대답과 설명은 한국어로 해줘.**

---

## 프로젝트 개요

**AutoProxy** — Python asyncio 기반 HTTP/HTTPS/SOCKS5 프록시 서버 (Windows 11)

| 항목 | 값 |
|------|-----|
| 언어/런타임 | Python 3.11, asyncio |
| VPN | PPTP (ipTIME, `183.103.151.104`, Windows `rasdial`) |
| 프록시 포트 | HTTP `127.0.0.1:8080` / SOCKS5 `127.0.0.1:1080` |
| AI 연동 | Claude (Anthropic SDK) + OpenAI (GPT-4o) |
| MCP 서버 | FastMCP, stdio 전송 |
| 테스트 | pytest, 23개 테스트 (`tests/test_handler.py`) |
| GitHub | https://github.com/taktongyoung/proxyWinGaurd |

---

## 디렉토리 구조

```
autoproxy/
├── main.py              # CLI 진입점 (click)
├── config/config.yaml   # 전체 설정
├── .env                 # 비밀값 (gitignore)
├── proxy/
│   ├── server.py        # TCP 서버, IP 허용목록
│   ├── handler.py       # HTTP/HTTPS/SOCKS5 핸들러
│   └── tunnel.py        # 원격 연결, SOCKS5 upstream
├── vpn/
│   ├── manager.py       # VPN 디스패처 + 헬스모니터
│   ├── pptp.py          # PPTP (rasdial, 프로파일 자동생성)
│   ├── ssh_tunnel.py    # SSH 동적 포워딩 (paramiko)
│   └── wireguard.py     # WireGuard (wg0.conf 필요)
├── plugins/
│   ├── base.py          # ProxyPlugin ABC
│   ├── traffic_logger.py
│   ├── content_filter.py
│   ├── ai_analyzer.py   # Claude로 트래픽 분석
│   └── codex_review.py  # OpenAI로 통과 코드 자동 리뷰
├── ai/
│   ├── claude_client.py
│   └── openai_client.py
├── mcp_server/
│   ├── server.py        # FastMCP 서버
│   └── tools.py         # MCP 도구 (38개)
├── utils/logger.py
└── tests/test_handler.py
```

---

## 환경 설정

**`.env` (절대 커밋 금지)**
```
VPN_USER=takty
VPN_PASS=xkrehd0
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
GITHUB_TOKEN=...
```

**`config/config.yaml`** — VPN 타입, 프록시 포트, 플러그인 on/off, AI 모델 설정

---

## 자주 쓰는 명령

```powershell
# 프록시 서버 시작 (VPN 자동 연결 포함)
python main.py start

# MCP 서버 함께 시작
python main.py start --mcp

# VPN/프록시 상태 확인
python main.py status

# IP 허용목록 관리
python main.py ip list
python main.py ip add 192.168.1.100
python main.py ip remove 192.168.1.100

# 플러그인 목록 / 생성 (OpenAI 필요)
python main.py plugin list
python main.py plugin add "요청 헤더에 X-Request-Id 추가하는 플러그인"

# 테스트
python -m pytest tests/ -v

# 설정 파일 지정 시작
python main.py --config config/config.yaml start
```

---

## 워크플로우 커맨드

> `.claude/commands/` 폴더는 아직 없음 — 아래는 Claude에게 요청할 때 쓰는 작업 단위 이름이며, 실제 쉘 명령이 아닌 Claude 운영 규칙이다.

| 명령 | 실제 동작 |
|------|-----------|
| `/test` | `python -m pytest tests/ -v` 전체 실행 |
| `/ci` | pytest 23개 통과 확인 — **통과 전 sync 금지** |
| `/codex-review [지시]` | `codex exec --skip-git-repo-check --sandbox read-only` 로 외부 시각 리뷰 |
| `/codex-rescue <상황>` | 막힌 상황 즉시 구조 요청 — Codex에 디버그·에러 도움 요청 |
| `/brainstorm <작업>` | 구현 전 접근법 3안 비교 후 권장안 선택 |
| `/verify <지시>` | verifier 서브에이전트 교차 검증 — 승인 시에만 구현 |
| `/sync [메시지]` | `git add → commit → push` 자동화 |
| `/status` | `python main.py status` — VPN 연결 상태 + 포트 확인 |

---

## 개발 표준 흐름

**단순 작업** (1~3파일, 접근법 명확):
```
/verify → 구현 → /ci → /codex-review → /sync
```

**복잡 작업** (신기능·설계 결정·아키텍처 변경):
```
/brainstorm → /verify → 구현 → /ci → /codex-review → 수정 → /ci → /sync
```

---

## 작업 영역별 흐름

| 변경 영역 | 흐름 |
|-----------|------|
| `proxy/`, `vpn/`, `plugins/`, `ai/` | `/ci` → `/codex-review` → `/sync` |
| `mcp_server/` | `/ci` → `/codex-review` → `/sync` |
| `config/config.yaml` | 검토 → `/sync` |
| `CLAUDE.md` / 문서 | `/codex-review` → `/sync` |
| `tests/` | `/ci` 통과 확인 → `/sync` |

원칙:
- **`/ci` (pytest 23개) 통과 전에는 절대 `/sync` 하지 않는다**
- `/codex-review` 는 push 전 필수 외부 시각 검증
- `.env` 는 절대 커밋하지 않는다 — gitignore 등록됨
- `*.conf`, `wg0.conf` 도 gitignore — WireGuard 개인키 보호

---

## /codex-review 운영 방법

```powershell
# 변경된 파일 전체 리뷰
git diff HEAD | codex exec --skip-git-repo-check --sandbox read-only

# 특정 파일 리뷰
Get-Content proxy/handler.py | codex exec --skip-git-repo-check --sandbox read-only

# 프롬프트 파일로 리뷰
"proxy/handler.py의 버그와 보안 취약점을 찾아줘" | codex exec --skip-git-repo-check --sandbox read-only
```

`/codex-rescue` 사용 시점:
- 같은 에러 2회 이상 재발
- 로그 메시지 의미 불명
- asyncio / paramiko API 불확실
- VPN 라우팅 동작 확인 필요

---

## 서브에이전트

| 에이전트 | 언제 호출 |
|----------|-----------|
| `verifier` | 새 작업 지시 받으면 구현 전 교차 검증 — 승인/조건부승인/거부 판정 |
| `explore` | 여러 모듈 탐색 시 메인 컨텍스트 보호 — "X 구현 위치", "Y 호출자" 등 |

호출: `Agent(subagent_type="verifier" | "explore", prompt="<질문/지시>")`

- verifier 판정이 **승인·조건부승인** 일 때만 구현 시작
- explore 결과는 `file:line` 형식 요약으로 반환

---

## 플러그인 개발 규칙

새 플러그인은 `plugins/base.py`의 `ProxyPlugin` ABC 상속:

```python
class MyPlugin(ProxyPlugin):
    async def on_request(self, ctx: RequestContext) -> RequestContext | None: ...
    async def on_response(self, ctx: ResponseContext) -> ResponseContext | None: ...
    async def on_connect(self, host: str, port: int) -> bool: ...
```

- `on_request` / `on_response` 에서 `None` 반환 → 403 차단
- `on_connect` 에서 `False` 반환 → CONNECT/SOCKS5 차단
- 플러그인 추가 후 `/codex-review` 실행

---

## VPN 설정

| 타입 | 설정 (`config.yaml vpn.type`) | 필요 조건 |
|------|-------------------------------|-----------|
| `pptp` | `type: pptp` | Windows rasdial, ipTIME 라우터 |
| `wireguard` | `type: wireguard` | `wg0.conf` 파일 (gitignore됨) |
| `ssh` | `type: ssh` | paramiko, SSH 서버 공개키 인증 |

PPTP split-tunneling: PC 외부 IP 유지, LAN `192.168.0.x` 접근 가능

---

## 핵심 원칙

- Python 표준 asyncio — `threading` 은 VPN SSH relay 전용
- 비밀값은 `.env` + `${VAR}` 환경변수 치환 방식
- IP 허용목록이 비어있으면 전체 허용, 설정 시 명시된 IP만 허용
- 세션 시작 시 `python main.py status` 로 VPN/포트 상태 먼저 확인
- 작업 후 반드시 `/ci` → `/codex-review` → `/sync` 순서 준수
