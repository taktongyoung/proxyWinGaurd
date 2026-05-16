# AutoProxy

WireGuard VPN 기반 AI 프록시 서버. HTTP / HTTPS / SOCKS5를 지원하며, 프록시를 통과하는 트래픽만 VPN을 경유합니다. 호스트 PC의 IP와 라우팅은 변경되지 않습니다.

Claude MCP 서버와 OpenAI(Codex)가 통합되어 있어 트래픽 분석, 코드 리뷰, 플러그인 자동 생성이 가능합니다.

## 아키텍처

```
클라이언트
    │
    ▼
AutoProxy 서버 (:8080 HTTP/HTTPS · :1080 SOCKS5)
    │
    ├── 플러그인 파이프라인 ──── traffic_logger
    │                       ├── content_filter
    │                       ├── ai_analyzer (Claude)
    │                       └── codex_review (OpenAI)
    │
    ▼
WireGuard 인터페이스 (wg0) ← 아웃바운드 소켓만 바인딩
    │
    ▼
목적지 서버

※ 호스트 PC 기본 라우트 변경 없음
```

## 기능

| 기능 | 설명 |
|---|---|
| HTTP/HTTPS 프록시 | CONNECT 터널 방식으로 HTTPS 지원 |
| SOCKS5 프록시 | 인증(user/pass) 선택 지원 |
| WireGuard VPN | 프록시 아웃바운드만 VPN 경유, 호스트 IP 유지 |
| Claude MCP 서버 | 트래픽 분석, 플러그인 관리 MCP 도구 제공 |
| Codex 코드 리뷰 | 프록시를 통과하는 코드 파일 자동 리뷰 (OpenAI) |
| 플러그인 시스템 | Python으로 미들웨어 플러그인 추가 가능 |
| 플러그인 자동 생성 | 자연어 설명으로 OpenAI가 플러그인 코드 생성 |

## 요구사항

- Python 3.11+
- WireGuard (Windows: [wireguard.com](https://www.wireguard.com/install/))
- WireGuard 설정 파일 (`wg0.conf`)

## 설치

```powershell
git clone https://github.com/taktongyoung/proxyWinGaurd.git
cd proxyWinGaurd

pip install -r requirements.txt
```

## 설정

### 환경변수

`.env` 파일을 프로젝트 루트에 생성합니다 (`.gitignore`에 포함되어 커밋되지 않습니다):

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

### WireGuard 설정

VPN 제공자로부터 받은 `.conf` 파일을 프로젝트 루트에 `wg0.conf`로 저장합니다:

```ini
[Interface]
PrivateKey = <your-private-key>
Address = 10.0.0.2/24

[Peer]
PublicKey = <server-public-key>
Endpoint = vpn.example.com:51820
AllowedIPs = 0.0.0.0/0
```

### `config/config.yaml`

```yaml
proxy:
  host: "0.0.0.0"
  port: 8080          # HTTP/HTTPS 프록시 포트
  socks5_port: 1080   # SOCKS5 포트
  auth:
    enabled: false    # true로 변경 시 user/pass 인증 활성화
    username: ""
    password: ""

vpn:
  type: "wireguard"
  config_file: "wg0.conf"
  interface: "wg0"
  auto_connect: true

ai:
  claude:
    api_key: "${ANTHROPIC_API_KEY}"
    model: "claude-sonnet-4-6"
    enabled: true
  openai:
    api_key: "${OPENAI_API_KEY}"
    model: "gpt-4o"
    enabled: true

plugins:
  traffic_logger:
    enabled: true
    log_file: "logs/traffic.log"
  content_filter:
    enabled: false
    blocked_domains: []
  ai_analyzer:
    enabled: true
    analyze_every_n_requests: 100
  codex_review:
    enabled: true
    max_body_size: 60000  # 리뷰할 최대 파일 크기 (bytes)
    min_lines: 5          # 최소 줄 수 (이하 파일은 스킵)
```

## 실행

```powershell
# 프록시 서버 시작
python main.py start

# 프록시 + Claude MCP 서버 동시 시작
python main.py start --mcp

# VPN / 프록시 상태 확인
python main.py status

# MCP 서버만 단독 실행 (Claude Code 연동용)
python main.py mcp
```

## 클라이언트 설정

프록시 서버 시작 후 클라이언트에서 아래와 같이 설정합니다:

| 방식 | 주소 | 포트 |
|---|---|---|
| HTTP 프록시 | `127.0.0.1` | `8080` |
| HTTPS 프록시 | `127.0.0.1` | `8080` |
| SOCKS5 | `127.0.0.1` | `1080` |

**curl 예시:**
```bash
curl -x http://127.0.0.1:8080 https://ifconfig.me
# → WireGuard VPN의 IP가 출력됨
```

## 플러그인

### 기본 제공 플러그인

| 플러그인 | 기능 |
|---|---|
| `traffic_logger` | 모든 요청/응답을 파일에 기록 |
| `content_filter` | 도메인 블랙리스트 차단 |
| `ai_analyzer` | N건마다 Claude로 트래픽 패턴 분석 |
| `codex_review` | `.py` `.js` `.ts` 등 코드 파일 통과 시 OpenAI로 자동 리뷰 |

**codex_review 지원 언어:** Python, JavaScript, TypeScript, TSX/JSX, Go, Rust, Java, C/C++, C#, Ruby, PHP, Swift, Kotlin, Bash, YAML, TOML

### 플러그인 자동 생성 (OpenAI)

```powershell
# 자연어 설명으로 플러그인 생성
python main.py plugin add "광고 서버 도메인을 자동으로 차단하는 플러그인"

# 생성된 플러그인 목록 확인
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
        # None 반환 시 해당 요청 차단 (403 응답)
        return ctx

    async def on_response(self, ctx: ResponseContext) -> ResponseContext | None:
        # ctx.body, ctx.headers, ctx.status_code 수정 가능
        return ctx

    async def on_connect(self, host: str, port: int) -> bool:
        # False 반환 시 CONNECT/SOCKS5 터널 차단
        return True
```

## Claude MCP 연동

`python main.py start --mcp` 실행 시 stdio 방식 MCP 서버가 함께 시작됩니다.

### 제공 MCP 도구

| 도구 | 설명 |
|---|---|
| `get_proxy_stats` | 활성 연결, 총 요청 수, 송수신 바이트 |
| `analyze_traffic` | 최근 N건 로그를 Claude로 분석 |
| `toggle_plugin` | 플러그인 활성화/비활성화 |
| `vpn_status` | WireGuard 연결 상태 |
| `generate_plugin` | 설명으로 플러그인 생성 |
| `list_plugins` | 등록된 플러그인 목록 |
| `get_code_reviews` | Codex가 수집한 코드 리뷰 조회 |
| `review_code_snippet` | 코드 스니펫 즉시 리뷰 요청 |

### MCP 리소스

| 리소스 URI | 내용 |
|---|---|
| `autoproxy://traffic_logs` | 최근 트래픽 로그 100건 |
| `autoproxy://active_connections` | 현재 활성 연결 목록 |
| `autoproxy://code_reviews` | Codex 코드 리뷰 전체 목록 |

## 테스트

```powershell
pip install pytest pytest-asyncio
python -m pytest tests/ -v --asyncio-mode=auto
```

```
20 passed in 0.47s
```

커버리지:
- HTTP 응답 전체 수신 (Content-Length / chunked / EOF)
- 플러그인 수정 내용 응답 반영
- IPv6 URL 파싱 (`[::1]:8080`)
- SOCKS5 RFC 1929 인증 버전 검증
- 연결 종료 후 `wait_closed()` 호출 확인

## 프로젝트 구조

```
autoproxy/
├── main.py                 # CLI 진입점 (click)
├── requirements.txt
├── config/
│   └── config.yaml         # 설정 파일
├── proxy/
│   ├── server.py           # asyncio 듀얼 서버 (HTTP + SOCKS5)
│   ├── handler.py          # 요청 처리 + 플러그인 파이프라인
│   └── tunnel.py           # CONNECT 터널 + 양방향 relay
├── vpn/
│   ├── wireguard.py        # WireGuard 연결 관리
│   ├── manager.py          # VPN 생명주기 + 자동 재연결
│   └── interface.py        # 네트워크 인터페이스 바인딩
├── mcp_server/
│   ├── server.py           # FastMCP 서버
│   └── tools.py            # MCP 도구 구현
├── plugins/
│   ├── base.py             # ProxyPlugin ABC
│   ├── traffic_logger.py
│   ├── content_filter.py
│   ├── ai_analyzer.py
│   └── codex_review.py
├── ai/
│   ├── claude_client.py    # Anthropic SDK (prompt caching 적용)
│   └── openai_client.py    # OpenAI SDK
├── utils/
│   └── logger.py           # Rich 기반 로거
└── tests/
    └── test_handler.py     # 20개 단위 테스트
```

## 라이선스

MIT
