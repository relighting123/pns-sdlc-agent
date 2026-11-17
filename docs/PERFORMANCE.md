# 토큰·응답속도 최적화 계획 및 구현

## 구분과 적용 계획

| 순서 | 기능 | 구현 | 검증 방법 |
|---|---|---|---|
| 1 | API 응답 정규화 | `intake.py`: 지정 필드만 추출, 출처와 안정적인 요구사항 ID 유지 | 저장 JSON 및 모의 HTTPS 응답 테스트 |
| 2 | 컨텍스트 선별 | `context.py`: 제외/우선 경로, 필수 입력 누락 시 차단 | 입력 바이트 감소, 필수 파일 미포함 실패 테스트 |
| 3 | Prefill 캐시 친화적 배치 | 규칙·스킬·스키마 → 소스 → 작업/의존성/피드백 순서 | 피드백 변경 전후 prefix 바이트 동일성 |
| 4 | 결과 재사용 제어 | 요구사항·설계 응답 캐시 TTL, namespace | 만료/무효화 및 기존 통합 테스트 |
| 5 | 비용·속도 관측 | 실제 사용량 정규화, 캐시 읽기/생성, 모델 호출 수, 지연 p50/p95 | 제공자별 의미 차이와 누락값 테스트 |
| 6 | 호출 전 점검 | `profile-context` CLI | 모델 호출 없이 입력 크기·누락 수 확인 |

기존 단계별 스킬 지연 로딩, 독립 작업 병렬 처리(`max_workers`), 작업별 `model`, 전체 입력 예산(`max_prompt_bytes`)은 유지한다. 모델은 사용자가 작업별로 지정한다. 자동으로 저가 모델을 선택하거나 필수 검증을 건너뛰지 않는다.

## 캐시 2종

**결과 캐시:** 모델 호출을 생략한다. 동일 프롬프트, 제공자 설정, Git HEAD, 캐시 namespace, 계약 버전일 때 요구사항·설계 단계만 재사용한다. 캐시 적중 후에도 결과 계약, 파일 범위, 실행 검증은 통과해야 한다. 개발·테스트·리뷰는 결과 캐시를 사용하지 않는다. 외부 의존성이나 도구 버전이 바뀌면 namespace를 올리거나 캐시를 끈다.

**제공자 prefill 캐시:** 같은 앞부분을 다시 계산하는 부담을 줄이는 데 목적이 있다. 프롬프트 길이 자체는 줄지 않는다. 현재 Codex/Claude CLI 어댑터는 제공자가 보고한 사용량을 읽는다. 캐시를 강제로 생성하거나 서버의 TTL·라우팅을 보장하지 않는다. 호스트가 추가하는 프롬프트, 모델, 최소 길이, 서버 정책에 따라 실제 적중은 달라진다. `stable_prefix_bytes`는 재사용 가능한 구조의 크기이며 실제 캐시 적중 토큰이 아니다.

Codex의 `cached_input_tokens`는 `input_tokens` 안에 포함된 것으로 계산한다. Claude의 `input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`는 별도 항목으로 더한다. 필드가 없으면 0으로 추정하지 않고 null 및 reporting_calls로 표시한다. 원본 usage도 보존한다.

## 설정

workflow.json 루트:

```json
{"cache":true,"cache_ttl_seconds":86400,"cache_namespace":"project-v1","context_bytes":48000,"max_prompt_bytes":2000000,"max_workers":2}
```

작업별 설정:

```json
{"reads":["src/*","tests/*","inputs/requirements/*"],"exclude_reads":["*.log","src/generated/*"],"priority_reads":["inputs/requirements/*","src/exports/*"],"required_reads":["inputs/requirements/EXACT_SNAPSHOT.json"]}
```

`required_reads`는 glob이 아닌 정확한 경로다. 제외 설정보다 우선하고, Git 추적 파일이어야 한다. 필수 파일이 예산에 안 들어가거나 읽을 수 없으면 실행을 차단한다. 소스를 잘라 넣거나 검증 기준을 임의 요약하지 않는다. 선택 후 파일 순서를 정렬하여 입력을 안정화한다. 재시도 때 예산 변화로 파일 선택이 바뀌면 prefix도 달라질 수 있다.

```bash
sdlc-agent --repo TARGET profile-context TARGET/workflow.json --task develop
sdlc-agent --repo TARGET report RUN_ID
```

profile-context는 현재 체크아웃 기준이며 실행 시 생성되는 의존 작업 요약·재시도 피드백은 포함하지 않는다. 토큰 추정치는 UTF-8 바이트/4이므로 한국어 등에서는 오차가 클 수 있다. 실제 과금 및 비교에는 provider usage를 사용한다.

## 성능 확인 절차

1. 같은 저장소 커밋·모델·작업으로 기준 실행과 경로 선별 실행을 비교한다.
2. 결과 캐시를 끈 상태에서 동일 요청을 반복하여 제공자 캐시 읽기 토큰을 확인한다.
3. 결과 캐시를 켠 상태에서 반복 실행하여 model_calls 감소를 확인한다.
4. 동일 수용 기준·테스트가 통과했는지 비교하고, submitted_prompt_bytes와 지연 p50/p95를 기록한다.
5. 충분한 반복 없이 개선율을 일반화하지 않는다. 서로 다른 모델·환경 결과를 직접 비교하지 않는다.

현재 지연은 CLI 프로세스 전체 시간이다. TTFT와 prefill만의 지연은 측정하지 않으며 `ttft_ms=null`로 표시한다. 스트리밍 TTFT 측정, 직접 API의 cache-control, 의미 기반 응답 캐시는 이번 범위에 포함되지 않는다. 의미 캐시는 서로 다른 요구사항을 잘못 재사용할 위험 때문에 적용하지 않는다.
