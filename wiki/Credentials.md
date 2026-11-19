# DB 계정과 API 자격증명

AI는 업무 대상과 프로필을 선택하고 해당 스킬의 클라이언트를 실행한다. 운영자는 아래 예시를 사내 환경에 맞춰 등록한다. 운영 프로필의 role_access와 허용 쿼리·작업 목록을 함께 설정한다.

| 대상 | 프로필 예시 | 운영 설정에 넣을 참조 | 용도 |
|---|---|---|---|
| ITSM Oracle | itsm-read | user_ref = itsm-user, password_ref = itsm-password | 접수 뷰 조회 |
| iFlow | iflow-development | auth.token_ref = iflow-read-token | 요구사항 근거 조회 |
| Cube | cube-development | auth.token_ref = cube-read-token | 요구사항 근거 조회 |
| GitLab | 프로젝트별 동기화 설정 | token_ref = gitlab-sync-token | 이슈와 승인 댓글 처리 |

## 로컬 설정

참조 이름과 같은 JSON 파일을 설치된 플러그인의 wiki/credentials/ 폴더에 만든다. 예를 들어 `token_ref`가 `cube-read-token`이면 `wiki/credentials/cube-read-token.json`을 사용한다.

```json
{"value": "example-only"}
```

Oracle은 `user_ref`, `password_ref`, `dsn_ref`를 사용할 수 있다. iFlow와 Cube는 `auth.token_ref`, GitLab은 `token_ref`를 사용한다. 기존 환경변수 설정도 지원한다. 예전에 만든 암호문은 운영자가 보유한 원본 값으로 새 JSON 파일을 만든 뒤 교체한다.

AI는 이 문서의 프로필 이름을 참조해 도구를 호출한다. 클라이언트가 값을 읽어 접속에 사용한다. 실제 값을 담은 파일은 평문이며 로컬 Git 추적에서 제외된다. 같은 파일 권한을 가진 사용자나 에이전트는 직접 열어볼 수 있다.
