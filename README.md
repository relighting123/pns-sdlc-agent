# SDLC Agent Plugin

저장소 루트가 Codex·Claude Code 플러그인입니다. skills/ 한 곳에서 지침을 관리하며 배포용 복사본이나 동기화 과정이 없습니다. 별도 모델 실행 엔진은 없습니다.

## 구조

| 경로 | 역할 |
|---|---|
| skills/ | SDLC 단계·워크트리·위키 검색 스킬 9개 |
| agents/ | Claude 서브에이전트 정의 6개 |
| .codex/agents/ | Codex 프로젝트 역할 설정 6개 |
| hooks/ | 공통 SessionStart 안내와 이벤트 설정 |
| .claude-plugin/ | Claude 매니페스트와 마켓플레이스 |
| .codex-plugin/ | Codex 호환 매니페스트 |
| .agents/plugins/ | Codex 마켓플레이스: 저장소 루트를 가리킴 |
| templates/wiki/ | 대상 프로젝트에 복사할 위키 양식 |
| docs/ | 구조·개발·확장 가이드 |
| tests/ | 플러그인 구조와 훅 검사 |

## 사용

Claude Code 로컬 설치: 저장소 루트에서 `claude --plugin-dir .`.
마켓플레이스 등록: `/plugin marketplace add relighting123/pns-sdlc-agent` 후 `/plugin install sdlc-agent@pns-sdlc-agent`.
Codex는 지원되는 플러그인 설치 UI에서 이 저장소의 루트 패키지를 설치합니다. 명명된 Codex 역할은 대상 프로젝트의 `.codex/agents/`에 제공 파일을 복사해야 하며 기존 파일을 덮어쓰지 않습니다. 플러그인 설치가 프로젝트 설정을 자동 설치하지는 않습니다.
훅에는 sh와 호스트의 훅 신뢰 설정이 필요합니다. 호스트별 실제 설치 및 모델 작업 수행은 별도 확인이 필요합니다.

요청 예: “run-sdlc로 검색 기능을 구현하고 테스트·리뷰까지 진행해줘. 설계 근거가 부족하면 wiki를 검색하고 병렬 수정은 worktree로 격리해줘.”

## 개발

skills/ 원본을 직접 수정합니다. 호스트별 에이전트 정의는 agents/와 .codex/agents/에서 각각 관리합니다.
`python3 -m unittest discover -s tests -v`로 구조를 검사합니다. Python은 개발 검증에만 사용됩니다.

[개발가이드](docs/DEVELOPER_GUIDE.md) · [소스 구조](docs/SOURCE_STRUCTURE.md) · [추가 개발 체크리스트](docs/EXTENSION_CHECKLIST.md) · [위키·워크트리](docs/WIKI_WORKTREES.md)
