**모든 대답과 설명은 한국어로 해줘.**

각 파트별 상세 규칙은 `rules/` 디렉토리 참조.

| # | 파일 | 설명 |
|---|------|------|
| 0 | [rules/00-session.md](rules/00-session.md) | 세션 시작 시 필수 확인 (job.md/history.md 읽기) |
| 1 | [rules/01-build-deploy.md](rules/01-build-deploy.md) | pnpm, 빌드/배포, PM2, Docker |
| 2 | [rules/02-infra.md](rules/02-infra.md) | nginx, DB, API 키, Cron |
| 3 | [rules/03-ai-models.md](rules/03-ai-models.md) | AI 모델/에이전트 (Local AI, Claude, ChatGPT, Gemini, TTS) |
| 4 | [rules/04-frontend.md](rules/04-frontend.md) | 프론트엔드 컴포넌트, 다크/라이트 모드, 모바일/PWA |
| 5 | [rules/05-backend.md](rules/05-backend.md) | 백엔드 모듈, DB 모델, 웹검색, 업데이트 노트 |
| 6 | [rules/06-google.md](rules/06-google.md) | Google 연동, Workspace API, 소셜 로그인 |
| 7 | [rules/07-firebase-push.md](rules/07-firebase-push.md) | Firebase, FCM 푸시 알림 |
| 8 | [rules/08-support-call.md](rules/08-support-call.md) | 1:1 문의 채팅, WebRTC 음성통화, barrier 패턴 |
| 9 | [rules/09-map.md](rules/09-map.md) | 네이버 지도 길찾기, 대중교통(ODsay), 자연어 감지 |
| 10 | [rules/10-mcp-server.md](rules/10-mcp-server.md) | MCP 서버 (38개 도구, /opt/mcp/) |
| 11 | [rules/11-apk-extension.md](rules/11-apk-extension.md) | APK Builder, Flutter 템플릿, 크롬 익스텐션 |
| 12 | [rules/12-scraper.md](rules/12-scraper.md) | 웹 스크래퍼 (추출 프롬프트 규칙, 렌더링) |
| 13 | [rules/13-git-policy.md](rules/13-git-policy.md) | Git 운영 (원격 저장소, .gitignore 화이트리스트, push 워크플로우) |
| 14 | [rules/14-design.md](rules/14-design.md) | 디자인 토큰 (Pretendard, Coolicons, Wanted Montage 토큰), 단일 진실 원칙 |

## Rules Audit (동기화 검증)
- 전체 검사: `python3 rules/audit.py` (또는 `/audit`)
- 특정 파트: `python3 rules/audit.py 04` (04-frontend만)
- 드리프트 상세: `python3 rules/audit.py --fix`
- **새 기능 추가/파일 변경 후 반드시 audit 실행하여 rule 동기화 확인**

## 슬래시 커맨드 (`.claude/commands/`)

| 명령 | 동작 |
|---|---|
| `/audit [파트]` | `python3 rules/audit.py` 실행 + drift 요약 |
| `/test [패턴]` | `pytest` 전체 실행 (smoke + audit 헬퍼 + models + drift 회귀) |
| `/ci` | audit + pytest 통합 게이트 (배포 전 권장) |
| `/brainstorm <작업>` | 구현 전 Opus 브레인스토밍 — 접근법 3안 비교 후 권장안 선택 |
| `/verify <지시>` | verifier 서브에이전트 명시적 호출 (작업 검증) |
| `/codex-review [지시]` | OpenAI Codex(`codex exec review --uncommitted`)로 외부 시각 2차 리뷰 |
| `/codex-rescue <상황>` | **막힌 상황 즉시 구조요청** — Codex에 디버그·에러·미지의 API 도움 요청 (실시간) |
| `/codex-stats [일수]` | Codex 사용량 통계 (토큰 누적, 명령별 분포, 일별 추이) |
| `/sync [메시지]` | 변경분 commit + GitHub push (gitleaks 안전망 + pre-push 훅 자동 검증) |
| `/deploy-front` | 프론트 빌드 후 `assistant-frontend` 재시작 (빌드 실패 시 재시작 중단) |
| `/deploy-back` | `assistant-backend` 재시작 + 최근 로그 30줄 확인 |
| `/build-front` | 프론트 빌드만 (타입 체크용, 재시작 없음) |
| `/restart-all` | 어시스턴트 프론트·백 동시 재시작 (빌드 없음) |
| `/status` | PM2·Docker·주요 포트 LISTEN 상태 일괄 확인 |
| `/update-notes <제목>` | `backend/update_notes.md`에 오늘 날짜 항목 추가 |

### 개발 표준 흐름

**단순 작업** (접근법 명확, 1-3파일 수정):
```
/verify → branch → 구현 → /ci → /codex-review → /sync → PR
```

**복잡 작업** (신기능·설계 결정·아키텍처 변경):
```
/brainstorm → /verify → branch → 구현 → /ci → /codex-review → 수정 → /ci → /sync → PR
```

- PR 머지 후: `/deploy-back` or `/deploy-front` → `/update-notes`
- `worktree` 추가 옵션: 메인 서비스 격리 실험 필요 시 참고해줘

### 표준 작업 흐름 (적용 전 필수)

작업 후 적용·커밋 전 다음 순서로 실행:

| 변경 영역 | 흐름 |
|---|---|
| **프론트엔드** (`frontend/`) | `/ci` → `/deploy-front` → `/update-notes <제목>` → `/sync` |
| **백엔드** (`backend/*.py`) | `/ci` → `/deploy-back` → `/update-notes <제목>` → `/sync` |
| **양쪽 다** | `/ci` → `/deploy-front` → `/deploy-back` → `/update-notes <제목>` → `/sync` |
| **rules·CLAUDE.md만** | `/audit` → `/sync` (deploy 불필요) |
| **타입 체크만 (반영 X)** | `/build-front` |

원칙:
- **`/ci` 가 통과하지 않으면 절대 deploy/sync 하지 않는다** — drift 0 + pytest 27 passed 가 게이트
- `/update-notes` 는 **사용자 향 신기능·개선만** 기록 (오류·디버그 제외)
- `/sync` 는 commit + push 자동화 — gitleaks pre-push 훅이 secret leak 마지막 방어선
- 단순 1-line 수정·문서 변경은 `/audit` → `/sync` 만으로 충분
- 자동 안전망: 매일 09:00 KST `deepseek-ci.timer` 가 `/ci` 자동 실행 → `.last-ci-status` 마커 갱신

## 서브에이전트 (`.claude/agents/`)

| 에이전트 | 언제 호출 |
|---|---|
| `verifier` | 새 작업 지시를 받으면 구현 전에 교차 검증 — 승인/조건부승인/거부 판정 (구 `codex_analy`/`claude_analy` 파일 왕복 대체) |
| `explore` | `backend/main.py` 5000줄+·프론트 다수 컴포넌트 탐색 — 메인 컨텍스트 오염 없이 "X 구현 위치", "Y 호출자", "Z 엔드포인트 역추적" 등 |

호출: `Agent(subagent_type="verifier"|"explore", prompt="<질문/지시>")`

- verifier: 판정이 승인·조건부승인일 때만 구현 시작. 범위 이탈·규칙 충돌 발견 시 재검증.
- explore: 결과는 `file:line` 형식 요약으로 돌아옴. 원본 파일을 그대로 받지 않음.
- (기존 `codex_analy.md` / `claude_analy.md` 파일 왕복 방식은 2026-04-24 폐기)

### verifier 자동 게이트
`UserPromptSubmit` 훅 (`.claude/hooks/verifier_gate.py`) 이 사용자 지시를 분류해서
작업 지시(task)로 판단되면 verifier 호출 리마인더를 자동 주입한다.
- TASK 분류: `해줘`/`수정`/`추가`/`늘려`/`개선` 등 명령 동사 포함 + 8자 이상 + `?` 미종결
- 자명한 1-line 수정·문서 변경·rules 정리는 verifier 생략 가능 (리마인더 무시)
- 명시 호출: `/verify <지시>`

### Codex 외부 시각 (구조 요청 흐름)
- `/codex-review` — **사후 정합성 리뷰**. push 전 변경분 검증
- `/codex-rescue <상황>` — **실시간 구조 요청**. 막혔을 때 즉시 외부 시각 도움
  - 자동 컨텍스트: `git status` + 변경 파일 + 최근 PM2 에러 + 최근 CI 로그
  - Codex 답변: 핵심 진단 + 즉시 액션 3개 + 추가 조사 위치
  - 사용 시점 권장: 같은 에러 2회+ 재발 / 로그 의미 불명 / 의도 모호 / 빌드 recurring 실패
- `/codex-stats` — 토큰·시간·실패율 누적 통계 (`logs/codex/usage.jsonl`)
- **자동 Rescue 트리거** (`CODEX_AUTO_RESCUE=1` 옵트인):
  - `ci_run.sh` FAIL 시 → 마지막 60줄 컨텍스트로 자동 진단
  - `pre-push` 차단 시 → leak 보고서로 자동 처리 절차 안내
  - 옵트인이라 default 비활성. 활성화: `export CODEX_AUTO_RESCUE=1` (현 셸) 또는 ecosystem 환경변수에 추가

## 핵심 빠른 참조

- **pnpm 필수** (npm/yarn 금지)
- 프론트: `cd /opt/deepseek/frontend && pnpm run build && pm2 restart assistant-frontend`
- 백엔드: `pm2 restart assistant-backend`
- DB: PostgreSQL localhost/deepseek (접속정보는 `backend/.env`의 `DATABASE_URL` 참조)
- 세션 시작: `job.md` 먼저 읽기
- Claude 작업 지시: `verifier` 서브에이전트 검증 후 승인 시 실행
- 업데이트 노트: 개선 내용만 간략히 (오류/디버그 제외)
