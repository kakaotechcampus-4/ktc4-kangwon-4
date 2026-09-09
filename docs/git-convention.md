# Git 컨벤션

> 커밋 메시지 prefix, 브랜치 전략, PR·리뷰 흐름을 정리합니다. `/CLAUDE.md` "레포 운영"의 브랜치 종류·PR 본문 원칙은 여기서 다시 풀어서 설명합니다(모순 시 이 문서 기준).

## 브랜치 전략

- `main`/`develop` 둘 다 **직접 커밋하지 않습니다** — 로컬에서 작업을 시작할 때는 항상 `develop` 기준으로 새 브랜치를 먼저 만듭니다.
- `feature/{branch-name}`: 기능 단위 작업, 새 기능 개발 시 생성
- `refactor/{내용}`: 멘토 리뷰 피드백을 반영할 때 생성
- PR 본문에는 구현 내용 요약 / 리뷰받고 싶은 포인트 / 고려한 설계·예외 상황을 기재합니다.

## Git 명령어

```bash
# 팀원: develop 브랜치에서 feature 브랜치 생성 및 개발 (머지는 PR로 develop에 머지)
git pull origin develop
git checkout -b feature/{branch-name}
git push -u origin feature/{branch-name}

# 팀 내 리뷰 후 develop에 merge

# 팀장(PM): develop -> main PR 생성 (수요일 리뷰요청, 토요일 재리뷰요청)
git fetch origin
git checkout develop
git pull origin develop
gh pr create --base main --head develop --web
# 또는 GitHub 웹에서 develop -> main PR 직접 생성

# 멘토: develop -> main PR 코드리뷰 진행

# 피드백 반영: develop에서 refactor 브랜치 생성
git checkout develop
git pull origin develop
git checkout -b refactor/{내용}
git push -u origin refactor/{내용}

# refactor -> develop merge는 팀 내 리뷰 후 진행

# 팀원: 최신 변경사항 받기
git pull origin develop

# 멘토님 Approve를 받고 그 주 일요일까지 main 으로 merge
```

## 커밋 메시지 prefix

커밋 메시지는 아래 prefix로 시작합니다: `<prefix>: <내용>`

| prefix | 의미 |
|---|---|
| `feat:` | 새로운 기능 추가 |
| `fix:` | 버그 수정 |
| `docs:` | 문서 수정 |
| `style:` | 코드 포맷팅, 세미콜론 누락 등 코드 변경이 없는 경우 |
| `refactor:` | 코드 리팩토링 |
| `test:` | 테스트 코드, 리팩토링 테스트 코드 추가 |
| `chore:` | 빌드 업무 수정, 패키지 관리 |
| `design:` | CSS 등 사용자가 UI 디자인을 변경했을 때 |
| `rename:` | 파일명(또는 폴더명)을 수정한 경우 |
| `remove:` | 코드(파일)의 삭제가 있을 때 |
| `add:` | 코드나 테스트, 예제, 문서 등의 추가 생성이 있는 경우 |
| `improve:` | 향상이 있는 경우 — 호환성, 검증 기능, 접근성 등 |
| `move:` | 코드의 이동이 있는 경우 |

아래 컨벤션은 예시이며, 팀 내에서 논의하여 변경할 수 있습니다.
