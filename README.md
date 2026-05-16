# AutoProxy

Python asyncio 기반 HTTP / HTTPS / SOCKS5 프록시 서버 (Windows 11).  
프록시를 통과하는 트래픽만 VPN을 경유하며, **호스트 PC의 IP와 라우팅은 변경되지 않습니다** (split-tunneling).

Claude MCP 서버와 OpenAI가 통합되어 있어 트래픽 분석, 코드 리뷰, 플러그인 자동 생성이 가능합니다.

---

## 아키텍처

```
클라이언트
    │
    ▼
AutoProxy (:8080 HTTP/HTTPS · :1080 SOCKS5)
    │
    ├── IP 허용목록 (기본: 127.0.0.1만 허용)
    │
    ├── 플러그인 파이프라인
    │       ├── traffic_logger   (모든 요청/응답 기록)
    │       ├── content_filter   (도메인 차단)
    │       ├── ai_analyzer      (Claude 트래픽 분석)
    │       └── codex_review     (OpenAI 코드 자동 리뷰)
    │
    ▼
VPN 어댑터 (PPTP / WireGuard / SSH 중 택1)
    │
    ▼
목적지 서버

※ 호스트 PC 기본 라우트·외부 IP 변경 없음
```

---

## 기능

| 기능 | 설명 |
|------|------|
| HTTP/HTTPS 프록시 | CONNECT 터널 방식으로 HTTPS 지원 |
| SOCKS5 프록시 | user/pass 인증 선택 지원 |
| **PPTP VPN** | ipTIME 라우터 PPTP — Windows `rasdial` + 프로파일 자동 생성 |
| **WireGuard VPN** | `wg0.conf` 기반 (파일 제공 시 활성화) |
| **SSH 터널 VPN** | SSH 동적 포워딩 — paramiko SOCKS5 릴레이 |
| VPN 헬스모니터 | 30초마다 연결 확인, 끊기면 자동 재연결 |
| IP 허용목록 | 클라이언트 IP 화이트리스트 (CLI로 관리) |
| Claude MCP 서버 | 트래픽 분석·플러그인 관리 MCP 도구 |
| Codex 코드 리뷰 | 통과하는 코드 파일 OpenAI로 자동 리뷰 |
| 플러그인 시스템 | Python으로 미들웨어 플러그인 추가 |
| 플러그인 자동 생성 | 자연어 설명으로 OpenAI가 플러그인 코드 생성 |

---

## 요구사항

- Python 3.11+
- Windows 10/11 (PPTP 사용 시)
- (선택) WireGuard — `wg0.conf` 파일 보유 시
- (선택) paramiko — SSH 터널 사용 시

```powershell
pip install -r requirements.txt
# 선택: pip install paramiko wgconfig
```

---

## 설치

```powershell
git clone https://github.com/taktongyoung/proxyWinGaurd.git
cd proxyWinGaurd
pip install -r requirements.txt
```

---

## 설정

### `.env` (절대 커밋 금지 — `.gitignore` 등록됨)

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
VPN_USER=your_vpn_username
VPN_PASS=your_vpn_password
```

### `config/config.yaml`

```yaml
proxy:
  host: 127.0.0.1        # 로컬 바인드 (외부 노출 원하면 0.0.0.0)
  port: 8080
  socks5_port: 1080
  auth:
    enabled: false       # true로 바꾸면 SOCKS5 user/pass 인증 활성화
    username: ""
    password: ""

access_control:
  allowed_ips:
    - 127.0.0.1          # 허용할 클라이언트 IP (비우면 전체 허용)

vpn:
  type: pptp             # pptp | wireguard | ssh
  name: "autoproxy-pptp" # PPTP 연결 프로파일 이름 (자동 생성됨)
  host: "183.103.151.104"
  username: "${VPN_USER}"
  password: "${VPN_PASS}"
  auto_connect: true

  # WireGuard 사용 시:
  # type: wireguard
  # config_file: wg0.conf   # gitignore됨 — 직접 복사 필요
  # interface: wg0

  # SSH 터널 사용 시:
  # type: ssh
  # host: ssh.example.com
  # port: 22
  # username: "${VPN_USER}"
  # password: "${VPN_PASS}"
  # local_socks_port: 9050

ai:
  claude:
    api_key: "${ANTHROPIC_API_KEY}"
    model: claude-sonnet-4-6
    enabled: true
  openai:
    api_key: "${OPENAI_API_KEY}"
    model: gpt-4o
    enabled: true

plugins:
  traffic_logger:
    enabled: true
    log_file: logs/traffic.log
  content_filter:
    enabled: false
    blocked_domains: []
  ai_analyzer:
    enabled: true
    analyze_every_n_requests: 100
  codex_review:
    enabled: true
    max_body_size: 60000   # 리뷰할 최대 파일 크기 (bytes)
    min_lines: 5           # 이 줄 수 미만은 스킵

mcp:
  enabled: true
  transport: stdio
```

---

## 실행

```powershell
# 프록시 서버 시작 (VPN 자동 연결 포함)
python main.py start

# 프록시 + Claude MCP 서버 동시 시작
python main.py start --mcp

# VPN / 프록시 상태 확인
python main.py status

# MCP 서버만 단독 실행 (Claude Code 연동용)
python main.py mcp
```

시작 시 출력 예시:
```
┌────────────────────────────────┐
│       AutoProxy Status         │
├──────────────┬─────────────────┤
│ HTTP Proxy   │ 127.0.0.1:8080  │
│ SOCKS5 Proxy │ 127.0.0.1:1080  │
│ VPN Status   │ Connected       │
│ VPN IP       │ 192.168.0.254   │
│ Allowed IPs  │ 127.0.0.1       │
└──────────────┴─────────────────┘
```

---

## 클라이언트 설정

| 방식 | 주소 | 포트 |
|------|------|------|
| HTTP 프록시 | `127.0.0.1` | `8080` |
| HTTPS 프록시 | `127.0.0.1` | `8080` |
| SOCKS5 | `127.0.0.1` | `1080` |

```powershell
# HTTP 프록시
curl -x http://127.0.0.1:8080 http://httpbin.org/ip

# SOCKS5 프록시
curl -x socks5://127.0.0.1:1080 http://httpbin.org/ip

# HTTPS (CONNECT 터널)
curl -x http://127.0.0.1:8080 https://httpbin.org/ip

# → 호스트 PC 원래 외부 IP가 출력됨 (split-tunneling으로 PC IP 유지)
# → 프록시 경유 LAN 접근: curl -x http://127.0.0.1:8080 http://192.168.0.1/
```

---

## IP 허용목록 관리

기본값은 `127.0.0.1`만 허용합니다. CLI로 런타임 없이 설정 파일을 직접 수정합니다.

```powershell
# 현재 허용 IP 목록
python main.py ip list

# IP 추가 (프록시 재시작 후 적용)
python main.py ip add 192.168.1.50

# IP 제거
python main.py ip remove 192.168.1.50
```

---

## 플러그인

### 기본 제공 플러그인

| 플러그인 | 기능 |
|----------|------|
| `traffic_logger` | 모든 요청/응답을 JSONL 파일에 기록 |
| `content_filter` | 도메인 블랙리스트 차단 |
| `ai_analyzer` | N건마다 Claude로 트래픽 패턴 분석 |
| `codex_review` | 코드 파일 통과 시 OpenAI로 자동 리뷰 (비동기) |

**codex_review 지원 언어:** Python, JavaScript, TypeScript, TSX/JSX, Go, Rust, Java, C/C++, C#, Ruby, PHP, Swift, Kotlin, Bash, YAML, TOML

### 플러그인 자동 생성 (OpenAI)

```powershell
python main.py plugin add "광고 서버 도메인을 자동으로 차단하는 플러그인"
python main.py plugin list
```

### 커스텀 플러그인 작성

`plugins/` 디렉토리에 파일을 추가합니다:

```python
from plugins.base import ProxyPlugin, RequestContext, ResponseContext

class MyPlugin(ProxyPlugin):
    name = "my_plugin"
    enabled = True

    async def on_request(self, ctx: RequestContext) -> RequestContext | None:
        # None 반환 → 요청 차단 (403)
        return ctx

    async def on_response(self, ctx: ResponseContext) -> ResponseContext | None:
        # ctx.body, ctx.headers, ctx.status_code 수정 가능
        return ctx

    async def on_connect(self, host: str, port: int) -> bool:
        # False 반환 → CONNECT/SOCKS5 터널 차단
        return True
```

---

## Claude MCP 연동

`python main.py start --mcp` 실행 시 stdio 방식 MCP 서버가 함께 시작됩니다.

### 제공 MCP 도구

| 도구 | 설명 |
|------|------|
| `get_proxy_stats` | 활성 연결, 총 요청 수, 송수신 바이트 |
| `analyze_traffic` | 최근 N건 로그를 Claude로 분석 |
| `toggle_plugin` | 플러그인 활성화/비활성화 |
| `vpn_status` | VPN 연결 상태 |
| `generate_plugin` | 설명으로 플러그인 생성 |
| `list_plugins` | 등록된 플러그인 목록 |
| `get_code_reviews` | Codex가 수집한 코드 리뷰 조회 |
| `review_code_snippet` | 코드 스니펫 즉시 리뷰 요청 |

### MCP 리소스

| 리소스 URI | 내용 |
|------------|------|
| `autoproxy://traffic_logs` | 최근 트래픽 로그 100건 |
| `autoproxy://active_connections` | 현재 활성 연결 목록 |
| `autoproxy://code_reviews` | Codex 코드 리뷰 전체 목록 |

---

## 테스트

```powershell
python -m pytest tests/ -v
```

```
23 passed in 0.38s
```

| 테스트 클래스 | 검증 항목 |
|---------------|-----------|
| `TestParseUrl` | HTTP/HTTPS URL 파싱, IPv6 `[::1]:8080` 형식 |
| `TestReadFullResponse` | Content-Length / chunked / EOF 전체 수신 |
| `TestRebuildResponse` | 플러그인 수정 내용 응답 반영, Content-Length 재계산 |
| `TestPipeRemainingBody` | 65KB 초과 POST body 스트리밍 |
| `TestSocks5Auth` | RFC 1929 subnegotiation 버전 검증 |
| `TestWaitClosed` | 연결 종료 후 `wait_closed()` 호출 확인 |

---

## 프로젝트 구조

```
autoproxy/
├── main.py                 # CLI 진입점 (click)
├── requirements.txt
├── CLAUDE.md               # AI 협업 규칙
├── config/
│   └── config.yaml         # 전체 설정 (VPN, 프록시, 플러그인, AI)
├── proxy/
│   ├── server.py           # asyncio 듀얼 서버 (HTTP + SOCKS5), IP 허용목록
│   ├── handler.py          # HTTP/HTTPS/SOCKS5 핸들러 + 플러그인 파이프라인
│   └── tunnel.py           # 원격 연결, SOCKS5 upstream (SSH 터널용)
├── vpn/
│   ├── manager.py          # VPN 디스패처 + 30초 헬스모니터
│   ├── pptp.py             # PPTP (rasdial, 프로파일 자동 생성)
│   ├── ssh_tunnel.py       # SSH 동적 포워딩 (paramiko + threading SOCKS5)
│   ├── wireguard.py        # WireGuard (wg0.conf 필요, gitignore됨)
│   └── interface.py        # 네트워크 인터페이스 유틸
├── plugins/
│   ├── base.py             # ProxyPlugin ABC (on_request/on_response/on_connect)
│   ├── traffic_logger.py
│   ├── content_filter.py
│   ├── ai_analyzer.py
│   └── codex_review.py     # 비동기 fire-and-forget, deque(maxlen=200)
├── mcp_server/
│   ├── server.py           # FastMCP 서버
│   └── tools.py            # MCP 도구 구현
├── ai/
│   ├── claude_client.py    # Anthropic SDK (prompt caching 적용)
│   └── openai_client.py    # OpenAI SDK (json_object 응답 형식)
├── utils/
│   └── logger.py           # Rich 기반 컬러 로거
└── tests/
    └── test_handler.py     # 23개 단위 테스트
```

---

## 라이선스

MIT
