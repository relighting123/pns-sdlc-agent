# API 응답에서 소스 개발까지

수집 계층은 원격 데이터를 실행 지시와 분리한다. MCP나 LLM 없이 Python 표준 라이브러리로 수집한다.

| 위치 | 역할 |
|---|---|
| `examples/intake/source.json` | API URL, 토큰 환경변수 이름, JSON Pointer 매핑 예시 |
| `sdlc_agent/intake.py` | HTTPS GET/저장 응답 로딩, 크기 제한, 필드 추출, 중복 검사 |
| `inputs/requirements/<digest>.json` (대상 프로젝트) | 출처·원본 해시·요구사항 ID가 있는 불변 입력 |
| `workflow.json` (대상 프로젝트) | 입력 파일을 requirements/design/develop/test/review의 필수 컨텍스트로 연결 |
| `artifacts/requirements.md`, `artifacts/design.md` | 에이전트가 작성하는 분석·설계 |
| `src/`, `tests/` | 기존 실행 엔진이 생성·검증하는 구현 결과 |

실행 예시(설치한 저장소에서):

```bash
sdlc-agent --repo TARGET intake examples/intake/source.json --response examples/intake/response.json
# 출력된 artifact 경로의 내용을 검토하고 TARGET 저장소에 커밋한다.
sdlc-agent --repo TARGET init --goal "CSV export 구현" --requirements inputs/requirements/RETURNED_DIGEST.json
# workflow의 소스 경로·테스트 명령을 실제 프로젝트에 맞게 편집하고 커밋한다.
sdlc-agent validate TARGET/workflow.json
sdlc-agent --repo TARGET run TARGET/workflow.json
```

실제 API를 사용할 때는 source.json의 URL을 변경하고 해당 환경변수로 인증 토큰을 제공한 뒤 `--response`를 생략한다. 토큰 자체를 설정 파일에 쓰지 않는다. 리다이렉트는 차단한다. 사용자 지정 HTTPS endpoint의 단일 응답만 수집하며 페이지네이션은 자동 추측하지 않는다. API가 페이지를 나누면 완전한 응답을 명시적으로 확보하거나 별도 수집 어댑터를 추가해야 한다.

`items_pointer`는 배열까지의 JSON Pointer이고 fields의 경로는 각 레코드 기준이다. id/title/description은 필수, acceptance는 선택이지만 수용 기준이 없으면 후속 분석에서 구체화해야 한다. 동일 출처와 원본 ID는 같은 REQ ID를 유지하며 내용 변경은 새 snapshot을 만든다. 완전히 같은 중복은 합치고, 같은 ID에 내용이 다르면 실패한다. 원본 응답 전문은 복제하지 않고 해시만 남긴다. 추출된 텍스트에 일반적인 비밀 패턴을 마스킹하지만 범용 개인정보 탐지 기능은 아니다. 커밋 전 검토가 필요하다.

실제 모델을 실행해야 소스가 생성된다. 수집만 수행했다고 개발이나 수용 기준 검증이 완료된 것으로 처리하지 않는다.
