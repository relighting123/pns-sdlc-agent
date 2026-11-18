# 용어와 이름 규칙

| 용어 | 의미 | 현재 예 |
|---|---|---|
| Plugin | 설치·배포 단위 전체 | pns-sdlc-agent |
| Agent | 담당 역할 | sdlc-develop |
| Skill | 작업 절차 | read-iflow-data |
| Client | 접속·통신 코드 | http_client, oracle_client |
| Executor | 등록 명령 실행 | query_executor, write_executor |
| Operation | 호출 가능한 개별 기능 | 사내에서 등록한 operation ID |
| Policy | 허용 범위·실행 제한 | effect, allow_write, allowed_operations |
| Result | 반환 데이터·상태 | ok, outcome, truncated |

스킬은 소문자·숫자·단일 하이픈, 1~64자, 디렉터리와 name 일치를 따른다. read/modify-서비스-data는 프로젝트 내부 관례이며 공식 예약 명칭이 아니다. Python 모듈은 snake_case를 사용한다. plugin_http처럼 배포 단위와 통신 모듈을 혼동시키는 이름은 쓰지 않는다.

- read-oracle-data / modify-oracle-data
- read-iflow-data / modify-iflow-data
- read-cube-data / modify-cube-data

읽기와 변경은 실제 effect로 판단한다. POST 조회도 read일 수 있다. 작업 취소·재처리·시작 등 업무 명령은 실API가 정해지면 cancel/retry/start 같은 별도 행동 스킬로 정의하고 기존 HTTP client를 재사용한다. 현재는 임의의 업무 명령을 만들어 등록하지 않았다.

이전 query-oracle 이름은 read-oracle-data로 교체했다. 기존 프롬프트·설치 스킬 이름·경로를 갱신해야 한다. 중복 별칭 스킬을 제공하지 않는다.

공식 스킬 형식: https://agentskills.io/specification
