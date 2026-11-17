# SDLC Agent

Codex 또는 Claude Code CLI로 실행하는 범용 소프트웨어 개발 플러그인. 저장소를 분석하고, 요구사항과 설계를 기록하고, 별도의 Git worktree에서 코드와 테스트를 바꾼 다음 독립 리뷰와 프로젝트 검증 명령을 실행합니다. 배포 대상은 팀이 제공하는 명령으로 연결합니다.

## 단계별 우선 작업

| 단계 | 우선 실행 순서 | 완료 증거 |
|---|---|---|
| 요구사항 | 기존 동작·호출자 조사 → 범위·제약 정리 → 정상·경계·실패 동작 정의 → 블로커 추출 | 검증 가능한 `R1…Rn`, 저장소 근거, 필요한 질문 |
| 설계 | 데이터·인터페이스와 변경 파일 파악 → 대안 비교 → 작업 순서·호환성·마이그레이션·실패 복구 결정 | 설계 결정과 모든 `R` 항목에 대응하는 검증 계획 |
| 구현 | 기준 커밋에서 분리 → 실제 호출 경로 수정 → 회귀 테스트 작성 → 변경 및 미해결 사항 기록 | 실제 Git 변경, 테스트 코드, 구현 결과 |
| 테스트 | 설정된 단위·통합 테스트, lint, build 등 실행 → 실패 로그 확보 → 정해진 횟수까지 수정 후 재검증 | 명령별 종료 코드와 실행 로그, 검증된 Git tree |
| 리뷰 | 구현과 독립된 모델 세션에서 변경 파일 재검토 → 호환성·데이터 정합성·권한·회귀 확인 → 수용 기준별 증거 연결 | 파일·라인이 포함된 지적과 각 기준의 충족 판정 |
| 릴리스·배포 | 변경 영향과 롤백 계획 작성 → 검증한 tree와 배포할 커밋 대조 → 배포 및 smoke 실행 → 필요 시 롤백 | 배포·smoke·롤백 영수증, 동일 Git 서명값과 작업 ID |

## 프로젝트 구조

| 경로 | 역할 |
|---|---|
| `skills/` | 워크플로우 진입점 4개 |
| `agents/` | Claude Code 플러그인용 역할 5개 |
| `scripts/roles.mjs`, `install-agents.mjs` | 역할 지시·응답 스키마, Codex 프로젝트 TOML 설치 |
| `scripts/sdlc.mjs`, `flow.mjs` | CLI, 단계 전이, 상태, 재개와 품질 게이트 |
| `scripts/provider.mjs`, `process.mjs` | Codex·Claude Code 호출, 구조화 출력, 계측, 명령·로그 실행 |
| `scripts/repository.mjs`, `config.mjs` | Git worktree, 소스 스냅샷, 경로 캐시, 팀 설정 검증 |
| `scripts/release.mjs` | 검증 커밋 생성, 배포·smoke·롤백, 성능 비교 |
| `tests/` | 공급자 이벤트·CLI·Git·배포를 연결한 회귀 테스트 |

## 바로 실행하기

Node 20 이상, Git, 로그인된 `codex` 또는 `claude` CLI가 필요합니다. 아래 명령은 플러그인 디렉터리 기준이며 대상은 커밋이 있는 별도 체크아웃입니다.

```bash
node scripts/sdlc.mjs catalog
node scripts/sdlc.mjs plan --workspace /path/to/project --config /path/to/project/sdlc.json --request 'Add cursor pagination to the activity API'
node scripts/sdlc.mjs resume --workspace /path/to/project --run RUN_ID
node scripts/sdlc.mjs status --workspace /path/to/project --run RUN_ID
node scripts/sdlc.mjs metrics --workspace /path/to/project --run RUN_ID
```

`run`은 분석부터 릴리스 계획까지 진행합니다. `plan`은 설계에서 멈추며 `resume`으로 구현을 시작합니다. 실행은 입력 저장소의 **커밋된 HEAD**에서 시작합니다. 기존 작업 디렉터리의 수정은 읽지 않습니다. 결과에는 run ID와 worktree 경로가 포함됩니다. 전이 상태, 역할 응답, 모델 이벤트와 명령 로그는 `git rev-parse --git-common-dir`이 가리키는 디렉터리의 `sdlc-agent/runs/<id>/`에 저장됩니다. 보존할 작업을 커밋한 뒤 저장소에서 `git worktree remove <path>`로 worktree를 제거할 수 있습니다. 중단 후 살아 있는 프로세스가 없을 때 `unlock --run <id>`로 PID 잠금을 해제하고 재개하세요.

Claude Code에서 대화형 플러그인은 `claude --plugin-dir /path/to/repo/plugins/sdlc-agent`로 로드합니다. Codex에서는 저장소의 로컬 마켓플레이스에서 `sdlc-agent`를 선택합니다. Codex 프로젝트 안에서 대화형 서브에이전트 이름을 직접 쓰려면 `node scripts/sdlc.mjs install-agents --workspace /path/to/project`를 실행합니다. CLI 파이프라인은 별도 역할 세션을 직접 호출하므로 이 설치 없이 동작합니다.

## 프로젝트별 설정

명령은 신뢰할 수 있는 대상 저장소의 기존 CI에 맞춥니다. 배열의 첫 요소는 실행 파일이고 나머지는 인자입니다. 셸 문법이 필요한 복합 명령은 검토된 프로젝트 스크립트로 관리하세요. `provider`를 `claude`로 바꾸면 Claude Code를 호출합니다. 프로젝트나 운영팀이 실제 사용하는 명령과 엔드포인트를 연결하세요.

```json
{
  "provider": "codex",
  "checks": [
    {"name": "unit", "argv": ["npm", "test"]},
    {"name": "lint", "argv": ["npm", "run", "lint"]},
    {"name": "build", "argv": ["npm", "run", "build"]}
  ],
  "repairAttempts": 2,
  "promptBytes": 24000,
  "contextBytes": 4000,
  "maxInputTokens": 0,
  "environments": {
    "staging": {
      "deploy": {"name": "deploy", "argv": ["node", "ops/deploy.mjs"]},
      "smoke": {"name": "smoke", "argv": ["node", "ops/smoke.mjs"]},
      "rollback": {"name": "rollback", "argv": ["node", "ops/rollback.mjs"]}
    }
  }
}
```

`environments`는 선택 항목입니다. `models`에서 `requirements`, `design`, `implement`, `review`, `release`별 모델을 지정할 수 있습니다. 값은 선택한 CLI가 지원하는 모델명으로 설정합니다. 개별 커맨드나 전체에 `timeoutMs`를 설정할 수 있습니다. 입력 토큰 한도는 공급자가 보고한 **이전 호출의 누계**로 다음 호출의 시작을 중지합니다. 현재 호출의 상한은 `promptBytes`가 관리하는 하네스 입력 범위이며 호스트에서 추가하는 컨텍스트나 도구 결과와 별개입니다.

## 배포 실행

```bash
node scripts/sdlc.mjs commit --workspace /path/to/project --run RUN_ID --message 'Add activity pagination'
node scripts/sdlc.mjs deploy --workspace /path/to/project --run RUN_ID --environment staging --commit FULL_SHA
node scripts/sdlc.mjs rollback --workspace /path/to/project --run RUN_ID --environment staging
```

배포 명령은 현재 worktree HEAD가 지정한 커밋이며 동일한 Git tree가 검증됐을 때 실행됩니다. 어댑터에는 `SDLC_RUN_ID`, `SDLC_OPERATION_ID`, `SDLC_ENVIRONMENT`, `SDLC_COMMIT`, `SDLC_TREE`, `SDLC_BASE_COMMIT`이 제공됩니다. 배포 시스템에서도 같은 작업 ID를 중복 방지에 사용하고, 검증 커밋을 빌드하거나 이전에 빌드한 해당 커밋의 버전으로 배포하세요. smoke와 외부 서비스 명령의 실제 의미는 환경 어댑터가 정의합니다. 같은 run ID와 환경의 배포는 한 번 시도하며, 불확실한 작업은 영수증과 배포 시스템을 확인한 후 대응합니다.

## MCP와 성능

기본 MCP 서버 없이 실행됩니다. Git 호출, 경로 선별, 테스트 실행, 로그 축약, 품질 게이트와 배포는 로컬 스크립트에서 처리합니다. 반복되는 대형 로그는 디스크에 보관하고 실패 요약만 이후 모델 호출에 넘깁니다. 같은 Git tree와 요청의 경로 목록은 캐시됩니다. 읽기 전용 리뷰와 프로젝트 검증이 동시에 진행되고, 검증 명령은 공유 산출물 충돌 방지를 위해 명시 순서대로 진행됩니다. Codex는 현재 사용자 설정에서 별도로 설치한 MCP를 로드할 수 있습니다. Claude 어댑터에는 빈 MCP 설정과 사용할 파일 도구 목록을 지정합니다.

원격 티켓과 사내 문서처럼 여러 호스트가 인증과 스키마를 공유할 때는 별도 MCP 연동을 추가할 수 있습니다. 토큰 영향은 도구 정의의 노출 방식과 호출 결과의 크기에 따라 달라집니다. 이 플러그인은 코드, 검증 로그와 외부 작업의 역할을 분리하고, 실제 수치는 모델 호출별 공급자 통계로 읽습니다.

`metrics`는 입력 바이트·입력/캐시/출력 토큰·첫 이벤트와 호출 시간을 구분합니다. 첫 이벤트는 호스트 이벤트 기준입니다. `compare --baseline RUN_ID --run RUN_ID`로 두 실행의 토큰, 캐시 비율, 모델 시간과 실제 파이프라인 실행 시간을 비교합니다. 동일한 기준 커밋·요청·품질 기준의 실행끼리 비교해야 합니다. 모델이 보고하지 않은 데이터는 null로 표시합니다.

공식 문서 [Codex Skills](https://developers.openai.com/codex/skills), [Codex 비대화형 실행](https://developers.openai.com/codex/noninteractive), [OpenAI Prompt Caching](https://developers.openai.com/api/docs/guides/prompt-caching), [Claude Code Plugins](https://code.claude.com/docs/en/plugins-reference).
