# where-were-we

[English](README.md) | **한국어**

git 밖에 두는 나만의 `STATUS.md`. 다음 코딩 에이전트 세션이 어디서 멈췄는지 바로 압니다.

에이전트는 세션이 바뀌면 모든 걸 잊습니다. 계속 불어나는 메모 파일은 금방 수천 토큰을 잡아먹고 실제와 어긋납니다. where-were-we는 지금 작업이 *어디까지 왔는지*만 적은 **짧은 파일 하나(최대 50줄)**를 유지합니다. 끝난 작업과 결정은 필요할 때만 여는 별도 파일로 보냅니다.

- **개인용.** 모든 파일이 내 컴퓨터에만 있습니다. `.git/info/exclude`에 등록되므로 커밋·머지·풀 리퀘스트에 섞이지 않고, 브랜치를 바꿔도 그대로 남습니다.
- **가벼움.** 파이썬 파일 하나, 표준 라이브러리만 씁니다. 서버도 데이터베이스도 설치도 필요 없습니다.
- **병렬 에이전트에 안전.** 여러 창과 서브에이전트가 동시에 써도 됩니다. 쓰기는 잠금으로 순서를 지키고 파일을 원자적으로 교체합니다.
- **Claude Code에서 자동.** 플러그인으로 설치하면 훅이 새 세션마다 `STATUS.md`를 보여주고, 커밋 뒤에는 에이전트에게 갱신하라고 알려줍니다.

> **베타 (v0.12.0).** 1.0 전에 실제 프로젝트에서 검증하는 중입니다. 그때까지 기능은 동결이고, 버그와 문서만 고칩니다.

## 무엇을 남기나

```
STATUS.md                       # 현재 상태만, 최대 50줄
.where-were-we/decisions.md     # 모든 결정, 한 줄씩
.where-were-we/log/YYYY-MM.md   # 끝난 작업, 월별
```

`STATUS.md`는 이렇게 생겼습니다. 항목은 사용자의 언어로, 제목은 영어로 둡니다.

```markdown
# Status
_updated: 2026-11-04_

## Goal
- 웹 앱에 OAuth 로그인 출시

## Now
- [ ] Google OAuth 콜백 — 캐시·잠금 문제 아님; handlers.py 의심

## Next
- GitHub OAuth
- 세션 만료 테스트

## Blocked
- [user] Fly.io 계정에 결제 카드 등록

## Decisions
- D-012: Redis 캐시, not 인메모리 — 인스턴스 여러 개 예정
- (+9 older: .where-were-we/decisions.md)
```

## 설치

### Claude Code 플러그인 (권장)

이 저장소가 그대로 플러그인 마켓플레이스입니다. Claude Code에서:

```
/plugin marketplace add jsha2217/where-were-we
/plugin install where-were-we@where-were-we
```

그다음 프로젝트에서 에이전트에게 설정해 달라고 하세요("where-were-we 설정해줘"). 에이전트가 `init`을 실행해 파일을 만들고 Goal을 물어봅니다.

플러그인은 훅 두 개를 추가합니다.

| 훅 | 하는 일 |
|---|---|
| `SessionStart` | 모든 세션(시작, 재개, clear, compact)에 `STATUS.md`를 넣어 줍니다. 에이전트가 읽기를 잊을 일이 없습니다. |
| `Stop` | 내 최신 커밋이 `STATUS.md`보다 새로우면, 커밋당 한 번 에이전트에게 갱신을 요청합니다. 다른 사람의 커밋은 무시합니다. |

`STATUS.md`가 없는 프로젝트에서는 훅이 아무것도 하지 않으며, 세션을 깨뜨리지 않습니다. 오류가 나면 조용히 넘어갑니다.

### 일반 스킬 (다른 에이전트, 또는 훅 없이)

`skills/where-were-we/`를 에이전트의 스킬 폴더에 복사하세요(Claude Code라면 `~/.claude/skills/where-were-we/`). 설정은 `init --link`로 합니다. 모든 세션이 `STATUS.md`를 먼저 읽도록 `CLAUDE.local.md`에 짧은 블록도 추가합니다.

## 사용법

대부분은 에이전트에게 말만 하면 됩니다. "어디까지 했지", "이어서 하자", "그거 끝났어", "Postgres로 가자" 같은 말을 하면 스킬이 에이전트에게 어떤 명령을 실행할지 알려줍니다. 프로젝트 안 어디서든 직접 실행할 수도 있습니다.

```sh
python3 skills/where-were-we/scripts/status.py <명령>
```

| 명령 | 하는 일 |
|---|---|
| `init [--link]` | 파일을 만들고 `.git/info/exclude`에 등록 (`--link`: `CLAUDE.local.md`가 `STATUS.md`를 가리키게 함) |
| `claim 2` / `claim "OAuth"` | 작업 시작: Next의 2번 항목(또는 글자가 맞는 항목)을 Now로 옮김; 없는 글자면 새로 추가 |
| `done` / `done "OAuth"` | Now 항목을 끝내고 `.where-were-we/log/`에 기록 |
| `decide "X로, not Y — 이유 Z"` | 결정 기록; `STATUS.md`에는 최근 5개만 표시 |
| `check` | `STATUS.md`가 50줄 이하이고 모든 섹션이 있는지 확인 |

Goal, Next, Blocked는 직접 편집합니다. Now는 `claim`과 `done`으로만 바꿉니다.

`STATUS.md`는 지시가 아니라 메모로 취급됩니다. 파일이 에이전트에게 무언가를 하라고 하면, 에이전트는 그 일을 하지 않고 사용자에게 알립니다. 모든 세션이 읽으니 비밀값이나 개인정보는 넣지 마세요.

## 프로젝트에서 제거

`STATUS.md`와 `.where-were-we/`(결정과 로그도 함께 지워지며, 커밋된 적이 없습니다), `CLAUDE.local.md`의 `where-were-we` 표시 사이 블록, `.git/info/exclude`의 `# where-were-we` 줄을 지우세요.

## 요구사항

- Python 3.9 이상, git
- macOS·Linux에서 테스트함 (Python 3.9, 3.12, 3.14). Windows는 아직 검증 전.

## 개발

```sh
bash tests/run.sh
```

각 테스트는 자기만의 임시 `HOME`과 git 저장소에서 돌기 때문에 임시 폴더 밖은 건드리지 않습니다.

```
.claude-plugin/        plugin.json, marketplace.json
hooks/hooks.json       SessionStart, Stop 훅
skills/where-were-we/  SKILL.md, scripts/status.py
tests/                 run.sh와 셸 테스트
```

## 라이선스

아직 없습니다(all rights reserved). 저장소를 공개하기 전에 정합니다.
