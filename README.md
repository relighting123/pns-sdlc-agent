# SDLC Agent

요구사항 → 설계 → 구현 → 테스트 → 리뷰 → 배포를 실행하는 범용 Python 런타임입니다.
특정 산업이나 업무 도메인에 종속되지 않습니다. 런타임 의존성은 Python 3.11+와 Git이며,
실제 추론에는 인증된 Codex CLI, Claude Code 또는 조직의 JSON 입출력 명령 어댑터를 사용합니다.

이 패키지는 실행 가능한 오케스트레이터입니다. 목표 애플리케이션 자체는 사용자가 입력한
요구사항과 프로젝트의 소스·테스트·배포 설정을 사용해 생성합니다. 특정 클라우드 계정,
배포 대상, 운영 자격증명을 임의로 가정하지 않습니다.

## 먼저 해야 할 일

| 단계 | 우선 작업 | 저장 결과 | 통과 조건 |
|---|---|---|---|
| 요구사항 | 범위, REQ ID, 비기능 요구, 수용 기준, 모호한 결정 분리 | `artifacts/requirements.md` | 필수 산출물 존재, 차단 사유 없음 |
| 설계 | 모듈 경계, API·데이터 계약, 실패 복구, 테스트 추적성 | `artifacts/design.md` | 필수 산출물 존재, 요구사항 연결 |
| 개발 | 의존 작업 분리, 경로 소유권, 구현과 테스트 | 소스·테스트 파일, 작업 커밋 | 출력 계약·경로 검사 및 지정 검사 통과 |
| 테스트 | 정상·경계·실패·회귀 사례, 실제 테스트 실행 | 테스트 파일, 실행 근거 | 검사 프로세스 exit 0; 기본 Python gate는 0개 테스트 거부 |
| 리뷰 | 전체 요구사항·소스·테스트 검토 | 읽기 전용 리뷰 결과 | 모든 선행 작업 완료, 미해결 issue 없음 |
| 배포 | 대상, 배포 명령, 상태 확인, 롤백 정의 | 배포/상태 확인/롤백 이벤트 | 명시적 실행 승인, 정확한 커밋 재검증, 상태 확인 성공 |

요구사항의 의미적 완전성과 리뷰 품질은 모델 판단입니다. 런타임은 구조·경로·의존성·실행 결과를
검증하며, 모델의 자연어 주장만으로 테스트 성공을 인정하지 않습니다.

## 설치와 실행

```bash
git clone https://github.com/relighting123/pns-sdlc-agent.git
cd pns-sdlc-agent
python3 -m pip install .
sdlc-agent doctor

# TARGET은 구현할 대상 프로젝트의 Git 저장소
sdlc-agent --repo /path/to/TARGET init --goal "구현할 기능과 수용 기준"
```

`TARGET/workflow.json`에서 소스 read/write 범위, 테스트 명령과 필요 시 배포 명령을 설정합니다.
기본 생성 설정은 `src/`, `tests/`를 사용하는 Python 프로젝트용입니다.
Node·Java 등은 해당 프로젝트의 경로와 실제 검증 명령으로 바꿉니다. 초기화를 완료한 workflow와
기존 파일을 커밋한 뒤 실행합니다. 원래 checkout은 깨끗해야 합니다.

```bash
sdlc-agent validate /path/to/TARGET/workflow.json
sdlc-agent --repo /path/to/TARGET run /path/to/TARGET/workflow.json
sdlc-agent --repo /path/to/TARGET status RUN_ID
sdlc-agent --repo /path/to/TARGET report RUN_ID
```

run ID는 시작 즉시 stderr에 JSON으로 출력됩니다. 완료된 코드는 대상 저장소의
`sdlc/RUN_ID` 브랜치에 저장됩니다. 사용자가 작업 중인 브랜치를 자동으로 전환·병합·push하지 않습니다.
검토 후 일반 Git 명령으로 통합할 수 있습니다.

```bash
git -C /path/to/TARGET diff HEAD..sdlc/RUN_ID
git -C /path/to/TARGET merge --ff-only sdlc/RUN_ID
```

실행 결과는 성공 0, 차단·승인 대기 2, 설정/실행 오류 1, 키보드 중단 130으로 종료됩니다.

## 중단, 실패, 수정

```bash
# 중단된 작업부터 재개; 완료된 작업은 다시 호출하지 않음
sdlc-agent --repo /path/to/TARGET resume RUN_ID

# 외부 장애 등을 해결한 뒤 실패 작업 재시도
sdlc-agent --repo /path/to/TARGET resume RUN_ID --retry-failed

# 리뷰/테스트 결함을 개발 작업으로 돌려보내고 하위 테스트·리뷰를 재실행
sdlc-agent --repo /path/to/TARGET repair RUN_ID --task develop \
  --feedback "동시 요청 시 중복 생성되는 경계 조건 수정"
```

`repair`는 원본 실행 이력을 보존하고 새 run ID를 만듭니다. 선택 작업과 그 후속 작업만 무효화하며,
영향받지 않은 완료 결과는 재사용합니다. 설정을 변경해야 하면 workflow를 수정·커밋한 뒤 새 run을
시작합니다. `resume`은 원본의 설정 snapshot과 기준 커밋을 그대로 사용합니다.

## 배포

workflow의 `deployment`에 다음 세 명령을 **실제 배포 환경에 맞게** 지정합니다. 명령은
문자열 shell이 아닌 argv 배열입니다. 런타임은 `SDLC_COMMIT`, `SDLC_RUN_ID`,
`SDLC_CONFIG_DIGEST`를 각 배포 명령의 환경변수로 전달합니다.

```json
{
  "deployment": {
    "command": ["python3", "ops/deploy.py"],
    "healthcheck": ["python3", "ops/healthcheck.py"],
    "rollback": ["python3", "ops/rollback.py"]
  }
}
```

배포 명령은 검증된 detached worktree에서 실행됩니다. 배포 스크립트는 커밋별 불변 artifact를
배포하고, `SDLC_RUN_ID`로 멱등성을 보장하도록 구현하는 것이 좋습니다. 상태 확인은 실제 대상의
버전과 가용성을 검사해야 합니다. `pass`처럼 아무것도 검사하지 않는 명령은 운영 검증이 아닙니다.

```bash
sdlc-agent --repo /path/to/TARGET resume RUN_ID --allow-deploy
```

테스트는 배포 직전 정확한 커밋에서 다시 실행됩니다. 배포/상태 확인 실패 시 롤백합니다.
프로세스 중단 또는 롤백 실패로 결과가 불명확하면 자동으로 재배포하지 않습니다. 대상을 확인한 뒤:

```bash
sdlc-agent --repo /path/to/TARGET resolve-deployment RUN_ID --outcome rolled-back
# 또는 실제 성공을 확인한 경우; 런타임이 healthcheck를 다시 실행함
sdlc-agent --repo /path/to/TARGET resolve-deployment RUN_ID --outcome succeeded
sdlc-agent --repo /path/to/TARGET resume RUN_ID
```

## 프로젝트 구조

| 경로 | 책임 |
|---|---|
| `sdlc_agent/cli.py` | 초기화·검증·실행·재개·수정·상태·보고서 명령 |
| `sdlc_agent/contracts.py` | DAG, 설정, 경로, 모델 JSON 계약 검증 |
| `sdlc_agent/engine.py` | 작업 배정·병렬 실행·수정 재실행·통합·배포 게이트 |
| `sdlc_agent/providers.py` | Codex, Claude, 사용자 command 어댑터 |
| `sdlc_agent/context.py` | 역할/스킬 지연 로딩·선택 소스·의존성 요약 |
| `sdlc_agent/workspace.py` | Git worktree, 경로 소유권, 충돌 검사, 실행 잠금 |
| `sdlc_agent/process.py` | 프로세스 시간 제한·출력 제한·종료 처리 |
| `sdlc_agent/store.py` | SQLite 트랜잭션·체크포인트·감사 이벤트·캐시·예산 |
| `sdlc_agent/verify.py` | 테스트 0개 발견을 거부하는 Python 검증 gate |
| `sdlc_agent/bundle.py` | 동일 리소스로 Codex/Claude 플러그인 생성 |
| `sdlc_agent/resources/agents/` | 단계별 역할 정의; context builder가 실제 로딩 |
| `sdlc_agent/resources/skills/` | 6개 단계별 작업 지침 |
| `plugins/codex/`, `plugins/claude/` | 생성된 호스트 플러그인: 7개 스킬, Claude 역할 6개 |
| `tests/` | 계약, 프로세스, 실제 Git, 어댑터, 실패·복구 통합 테스트 |
| `docs/` | 아키텍처, 설정 계약, 최적화·MCP 판단, 운영 검증 |

## 스킬·서브에이전트·MCP의 역할

스킬은 수행 절차입니다. 에이전트는 그 절차와 제한된 문맥을 받은 새 모델 세션입니다.
스크립트는 Git, 테스트, 상태 저장, 배포 같은 결정적 실행을 담당합니다.
폴더만 놓아서 별도 컨텍스트가 자동 생성되는 것은 아닙니다. 이 런타임은 작업마다 실제로 새 CLI
프로세스를 시작하고 선택한 입력만 전달합니다. 병렬 작업에는 서로 다른 worktree를 배정합니다.

MCP는 필수가 아닙니다. 이 구현은 MCP 서버 없이 작동합니다. 로컬 파일·Git·빌드·테스트는
직접 스크립트가 적합합니다. 중앙 인증·여러 호스트 공유·원격 도구 발견이 필요한 경우 기존
MCP 서버를 사용하거나 command 어댑터 뒤에 연결할 수 있습니다. MCP 자체를 재구현하지 않습니다.
토큰 차이는 프로토콜 자체가 아니라 모델에 전달하는 도구 정의, 결과, 반복 횟수에 따라 달라집니다.

## 최적화 기능

| 기능 | 구현 | 효과와 한계 |
|---|---|---|
| 필요한 스킬만 로딩 | 현재 stage의 역할과 SKILL.md만 포함 | 공통 프롬프트 증가 억제 |
| 선택적 컨텍스트 | tracked 파일의 reads 패턴, 크기 예산, 누락 목록 | 전체 저장소·대화 재전송 방지; 누락 파일은 명시 |
| 요약 핸드오프 | 직접 의존 작업의 summary·acceptance·파일 경로 | 이전 대화 전체 복제 방지 |
| 모델 분리 | provider 기본 model + task별 model override | 단순 작업과 어려운 작업 모델을 운영자가 선택 |
| 응답 캐시 | prompt·provider·HEAD·계약 버전 해시 | 요구사항·설계만 캐시; 변경 시 무효화, 24h TTL |
| 병렬 실행 | DAG의 준비된 독립 작업 + max_workers | 임계 경로 단축; 기본 선형 workflow는 순차 실행 |
| 증분 재개 | 완료 체크포인트 재사용 | 재개 때 완료 작업의 모델 호출 생략 |
| 수정 범위 제한 | repair의 후속 작업만 무효화 | 검증을 건너뛰지 않고 재작업 범위 축소 |
| 전체 입력 예산 | SQLite 원자적 prompt bytes 예약 | 병렬 호출에도 동일 상한; 실제 과금 토큰 상한은 아님 |
| 출력 제한 | JSON 파일 수·크기, 프로세스 출력·시간 제한 | 폭주 방지, bounded retry |
| 측정 | 실제 provider usage, 추정 tokens, cache hit, p50/p95 | 실측과 추정 구분; 절감률은 workload별 비교 필요 |

안정적인 지침을 프롬프트 앞쪽에 둡니다. 제공자의 prefix cache는 제공자 정책에 따르며 런타임이
캐시 적중을 강제로 보장하지 않습니다. 로컬 응답 캐시와 제공자의 cached input tokens는 서로 다릅니다.

## 플러그인 사용

패키지를 먼저 설치합니다. 기본 실행은 위 CLI로 가능하며 플러그인은 호스트의 발견·호출 편의를 제공합니다.

```bash
# Claude Code
claude --plugin-dir ./plugins/claude

# 새 위치로 재생성; 기존 경로는 덮어쓰지 않음
sdlc-agent bundle --host codex --output /path/to/new-codex-plugin
sdlc-agent bundle --host claude --output /path/to/new-claude-plugin
```

Codex 번들은 `.codex-plugin/plugin.json`과 `skills/` 구조입니다. 사용하는 Codex 버전의 로컬
플러그인 등록 방식으로 `plugins/codex`를 등록합니다. 호스트 버전별 등록 UI/명령은 다를 수 있습니다.
Codex 번들은 native agent TOML 자동 설치를 수행하지 않으며, 별도 세션 배정은 Python 런타임이 담당합니다.
Claude 번들은 발견 가능한 native agent Markdown도 제공합니다. native agent만 개별 사용하면
SQLite 기록·경로 검사·배포 게이트는 자동 적용되지 않으므로 전체 실행에는 `run-sdlc`를 사용합니다.

## 검증과 운영 범위

```bash
python3 -m unittest discover -s tests -v
python3 -m pip wheel --no-deps .
```

자세한 검증 결과와 미검증 항목은 [검증 기록](docs/VALIDATION.md), 설정 상세는
[설정 계약](docs/CONFIGURATION.md), 실행 구조는 [아키텍처](docs/ARCHITECTURE.md)를 참조하세요.

Git worktree는 작업 충돌을 격리하지만 OS 보안 sandbox는 아닙니다. workflow 명령, 테스트 코드와
사용자 command provider는 신뢰된 코드로 취급합니다. 신뢰할 수 없는 저장소는 컨테이너/격리 runner에서
실행해야 합니다. Codex는 read-only sandbox로 호출하고 Claude는 도구를 비활성화하지만,
호스트의 인증·설정·확장 기능에 대한 보안 통제는 해당 CLI와 실행 환경의 책임입니다.
로그의 비밀 패턴 제거는 최선 노력이며 완전한 DLP가 아닙니다. 입력에 비밀값을 넣지 마세요.

현재 파일 생성·수정은 지원하며 파일 삭제·바이너리 산출물·스트리밍 UI는 지원하지 않습니다.
리뷰 결함은 `repair`로 다시 개발 작업에 연결합니다. 실제 운영 배포의 적합성은 프로젝트별
배포 스크립트, 대상 환경과 별도 운영 검증에 달려 있습니다.

## API 요구사항 수집과 성능 최적화

API 응답을 출처가 있는 필수 요구사항 입력으로 연결하려면 [수집 가이드](docs/REQUIREMENTS_INTAKE.md)를 참고하세요.
Prefill 캐시 활용 구조, 결과 캐시, 컨텍스트 선별, 실제 사용량 측정과 적용 계획은 [성능 가이드](docs/PERFORMANCE.md)에 있습니다.
`profile-context`는 모델 호출 전에 입력 크기를 확인하고, `report`는 결과 캐시와 제공자 캐시 사용량을 구분합니다.
