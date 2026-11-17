# SDLC Agent Plugin

Codex·Claude Code가 직접 요구사항 분석 → 설계 → 개발 → 테스트 → 리뷰 → 요청된 배포를 수행하는 플러그인입니다.
별도 에이전트 런타임, Python 패키지, 모델 API 클라이언트, SQLite 저장소는 없습니다.

## 사용

Claude Code에서 저장소를 받은 뒤 `claude --plugin-dir ./plugins/claude`로 로컬 플러그인을 로드합니다.
Codex에서는 저장소의 마켓플레이스 항목으로 `plugins/codex`를 설치하거나 지원되는 로컬 플러그인 설치 UI를 사용합니다.
호스트별 설치 UI와 훅 지원은 버전에 따라 다릅니다. 훅을 검토하고 신뢰해야 실행되는 호스트에서는 해당 절차를 따릅니다.

설치 후 요청 예: “run-sdlc를 사용해 이 프로젝트의 검색 기능을 구현하고 테스트와 리뷰까지 진행해줘.”
Codex의 명명된 역할을 사용하려면 `adapters/codex/agents/*.toml`을 대상 프로젝트의 `.codex/agents/`에 기존 파일을 덮어쓰지 않고 복사합니다.
이 설정을 설치하지 않아도 스킬은 호스트의 기본 서브에이전트를 사용하거나 순차 수행합니다.

## 구성

| 경로 | 역할 |
|---|---|
| skills/ | 공통 작업 지침 원본 7개 |
| plugins/codex/ | Codex 배포용 스킬·매니페스트·훅 |
| plugins/claude/ | Claude 배포용 스킬·6개 에이전트·훅 |
| adapters/codex/agents/ | 프로젝트에 설치할 Codex 역할 정의 |
| scripts/ | 배포 파일 동기화·검증 보조 작업 |
| docs/ | 구조·전환·검증·외부 연동 설명 |

[설계와 제한](docs/ARCHITECTURE.md) · [검증](docs/VALIDATION.md) · [MCP](docs/MCP.md)

개발 검증: `python3 -m unittest discover -s tests -v`.
Python은 저장소 유지보수 테스트에만 사용하며 플러그인 사용에는 필요하지 않습니다. 훅에는 sh가 필요합니다.
