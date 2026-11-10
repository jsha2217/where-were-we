# where-were-we

[English](README.md) | **한국어**

**코딩 에이전트는 세션이 끝나면 모든 걸 잊습니다. where-were-we는 다음 세션이 처음부터 다시 시작하지 않게 합니다.**

![version](https://img.shields.io/badge/version-0.13.0_beta-blue)
![python](https://img.shields.io/badge/python-3.9%2B-3776AB)
![dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-D97757)
![license](https://img.shields.io/badge/license-MIT-green)

작업이 *지금* 어디까지 왔는지 적은 짧은 `STATUS.md` 하나(최대 50줄)입니다. 진행 중인 일, 이미 확인하고 아니었던 것, 막힌 것, 정한 것이 들어갑니다. 새 세션은 이 파일부터 읽습니다.

```
나:       어디까지 했지?

에이전트:  어제 토스 결제 콜백을 연결하던 중이었어요.
          - 결제창은 정상이고, 승인 콜백에서 401이 나요.
          - 시크릿 키 인코딩은 이미 확인했고 문제가 아니었어요.
          - 테스트 키가 만료된 것 같아서 재발급을 부탁드렸었어요.
          새 키 받으셨어요?
```

에이전트는 어제를 전혀 기억하지 못합니다. `STATUS.md`의 세 줄을 읽었을 뿐입니다. 그래서 어제 한 디버깅을 반복하지 않고, 이미 정한 걸 다시 뒤집지 않고, 기다리던 일부터 물어봅니다.

---

## 빠른 시작

Claude Code에서:

```
/plugin marketplace add jsha2217/where-were-we
/plugin install where-were-we@where-were-we
```

그다음 프로젝트 안에서:

```
where-were-we 설정해줘
```

에이전트가 한 가지(기록을 이 컴퓨터에만 둘지, Git에 커밋할지)를 묻고, 파일을 만들고, 목표를 물어봅니다. 끝입니다. 이후로는 그냥 작업하면 됩니다.

---

## 동작 방식

```mermaid
flowchart LR
    A[새 세션] -->|훅이 STATUS.md 전달| B[에이전트가 멈춘 지점을 앎]
    B --> C[작업: claim / done / decide]
    C -->|STATUS.md가 최신으로 유지됨| D[세션 종료]
    D --> A
```

평범한 마크다운 파일 세 개가 전부입니다.

```
STATUS.md                       # 지금 상태 — 최대 50줄, 매 세션 읽음
.where-were-we/decisions.md     # 모든 결정, 한 줄씩 — 필요할 때 검색
.where-were-we/log/YYYY-MM.md   # 끝난 작업, 월별 — 필요할 때만 열람
```

매 세션 읽는 건 `STATUS.md` 하나뿐이라, 프로젝트가 아무리 길어져도 토큰 비용은 그대로입니다. 끝난 작업은 로그로 옮겨지고, 오래된 결정은 한 줄로 접힙니다. 쌓이는 게 없습니다.

### STATUS.md 예시

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
- D-002: Postgres, not SQLite — 동시 쓰기 필요
- D-003: 서버 세션, not JWT — 즉시 로그아웃 필요
- D-004: Redis 캐시, not 인메모리 — 인스턴스 여러 개 예정
- D-005: Google 먼저, 그다음 GitHub — 사용자 대부분이 Google
- D-006: Redis는 세션에만 사용 — replaces D-004
- (+1 older: .where-were-we/decisions.md)
```

항목은 사용자의 언어로, 섹션 제목은 영어로 둡니다.

| 섹션 | 내용 | 바꾸는 방법 |
|---|---|---|
| **Goal** | 프로젝트가 지금 이루려는 것 | 직접 편집 |
| **Now** | 진행 중인 작업과 이미 확인하고 아니었던 것 | `claim` / `done` |
| **Next** | 다음에 할 일 | 직접 편집, `claim`이 여기서 꺼냄 |
| **Blocked** | 누군가를 기다리는 일: `[user]`, `[external]`, `[agent]` | 직접 편집 |
| **Decisions** | 최근 결정 5개 | `decide` |

---

## 말만 하면 됩니다

명령을 직접 실행할 필요가 없습니다. 상황을 말하면 스킬이 에이전트에게 무엇을 기록할지 알려줍니다.

| 이렇게 말하면 | 에이전트가 실행 |
|---|---|
| "어디까지 했지?" / "이어서 하자" | `STATUS.md` 읽기 |
| "GitHub OAuth 시작하자" | `claim "GitHub OAuth"` |
| "그거 끝났어" | `done` → 항목을 로그로 옮김 |
| "SQLite 말고 Postgres로 가자" | `decide "Postgres, not SQLite — 동시 쓰기 필요"` |
| "다시 SQLite로 바꾸자" | `decide "SQLite, not Postgres — 혼자 씀; replaces D-002"` |

디버깅 중에는 에이전트가 이미 확인한 것을 Now 줄에 덧붙입니다. 세션이 갑자기 끊겨도 같은 한 시간을 두 번 쓰지 않습니다.

---

## 로컬 또는 Git 포함

처음 설정할 때 한 번 고릅니다.

| | 로컬 (`init --local`) | Git 포함 (`init --git`) |
|---|---|---|
| Git | 제외 (`.git/info/exclude`) | 포함, 다른 파일처럼 커밋 |
| 이어받는 쪽 | 이 컴퓨터의 다음 세션 | 클론·포크한 누구든, 어느 컴퓨터든 |
| 이럴 때 | 내 메모용, 커밋을 깔끔하게, 브랜치를 바꿔도 유지 | 사람과 컴퓨터 사이의 인수인계 |

`--git`에서는 저장소를 푸시하는 것 자체가 인수인계입니다. 클론한 사람의 세션은 이미 작업이 어디서 멈췄는지 압니다. 스스로 스테이징·커밋·푸시하지는 않습니다. 나중에 `--local`로 바꿀 수 있고, 과거 커밋은 그대로 남습니다.

---

## 이렇게 만든 이유

- **일부러 작게.** 50줄은 이어서 하기에 충분하고, 낡기에는 짧습니다. 제한은 에이전트가 지키는 지침이고 `check`가 알려줍니다. 자동으로 자르지 않으니 아직 필요한 내용이 사라지지 않습니다.
- **지시가 아니라 메모.** `STATUS.md`가 에이전트에게 무언가를 시키면, 에이전트는 따르지 않고 사용자에게 알립니다. 커밋된 파일이 프롬프트 인젝션 통로가 되지 않습니다.
- **병렬 에이전트에 안전.** 여러 창과 서브에이전트가 동시에 써도 됩니다. 쓰기는 잠금으로 순서를 지키고 파일을 원자적으로 교체합니다.
- **중단돼도 안전.** `done`이나 `decide`가 중간에 끊기면 다음 명령이 마무리합니다. 중복도 누락도 없습니다.
- **결정의 이력이 남음.** 번복된 결정은 지우지 않습니다. 새 결정에 무엇을 대체하는지 적으니, "이거 왜 이렇게 했지?"에 언제나 답이 있습니다.
- **의존성 0.** 파이썬 파일 하나, 표준 라이브러리만 씁니다. 서버도, 데이터베이스도, 계정도 없습니다.

---

## 다른 방법과 비교

| 방법 | 부족한 점 |
|---|---|
| 이전 대화 이어가기 | 길어지면 무겁고, 다른 컴퓨터나 사람에게 넘길 수 없음 |
| `CLAUDE.md`에 메모 | 규칙과 상태가 섞이고, 계속 불어나 낡음 |
| 에이전트 자체 메모리 | 사람을 기억하지 작업 상태를 관리하지 않음, 저장소에 남지 않음 |
| `git log` | 끝난 일만 있음. 진행 중·막힘·다음 할 일은 없음 |

---

## 다른 에이전트

| | Claude Code (플러그인) | 다른 에이전트 (일반 스킬) |
|---|---|---|
| 명령 (`status.py`) | ✅ | ✅ 파이썬이 있으면 어디서나 |
| 스킬 지침 (`SKILL.md`) | ✅ | ✅ Agent Skills를 읽는 에이전트에서 |
| 세션 시작 때 `STATUS.md` 자동 읽기 | ✅ 훅 | ❌ 아직. "어디까지 했지"라고 물으면 스킬이 읽음 |
| 커밋 후 갱신 알림 | ✅ 훅 | ❌ |

일반 스킬로 쓰려면 `skills/where-were-we/`를 에이전트의 스킬 폴더에 복사하세요. 플러그인 없이 Claude Code에서 쓴다면 `init`에 `--link`를 붙이세요. `CLAUDE.local.md`에 "먼저 읽어" 블록을 추가합니다. 다른 에이전트를 위한 `AGENTS.md` 자동 연결은 계획 중입니다.

---

## 명령

프로젝트 안 어디서든 실행합니다.

```sh
python3 skills/where-were-we/scripts/status.py <명령>
```

| 명령 | 하는 일 |
|---|---|
| `init [--local \| --git] [--link]` | 설정. 직접 실행하면 모드를 묻고, 에이전트는 옵션으로 지정. `--link`: `CLAUDE.local.md`가 `STATUS.md`를 가리키게 함 |
| `claim 2` / `claim "OAuth"` | 작업 시작: Next의 2번(또는 글자가 맞는 항목)을 Now로; 없는 글자면 새로 추가 |
| `done` / `done "OAuth"` | Now 항목을 끝내고 로그에 기록 |
| `decide "X로, not Y — 이유 Z"` | 결정 기록; `STATUS.md`에는 최근 5개만 표시 |
| `check` | 50줄 이하이고 섹션이 다 있는지 확인 |

Goal, Next, Blocked는 직접 편집합니다. Now는 `claim`과 `done`으로만 바꿉니다.

---

## 자주 묻는 질문

**STATUS.md가 50줄을 넘으면?**
고장 나지 않습니다. `check`가 알려주고, 에이전트가 줄입니다. 끝난 항목은 완료 처리하고, Next를 정리하고, 해결된 Blocked를 지웁니다.

**결정은 정리되나요?**
`STATUS.md`에는 늘 최근 5개만 보입니다. `decisions.md`는 전부 보관합니다. 통째로 읽지 않고 검색만 하기 때문입니다. 결정을 뒤집을 때는 무엇을 대체하는지 적은 새 결정을 남깁니다. 같은 주제라면 번호가 큰 쪽이 유효합니다.

**`done`이나 `decide`가 중간에 끊겼어요.**
`claim`, `done`, `decide` 중 아무거나 다시 실행하세요. 끊긴 작업을 먼저 마무리하고, 중복으로 기록하지 않습니다. 그사이 `STATUS.md`나 로그를 직접 고쳤다면 덮어쓰지 않고 멈춥니다. 파일을 확인한 뒤 `.where-were-we/.done-pending.json` 또는 `.decide-pending.json`을 지우면 계속됩니다.

**비밀값을 넣어도 되나요?**
안 됩니다. 매 세션이 읽고, `--git`에서는 커밋됩니다.

**프로젝트에서 제거하려면?**
`STATUS.md`와 `.where-were-we/`, `CLAUDE.local.md`의 `where-were-we` 표시 사이 블록, `.git/info/exclude`의 표시된 블록을 지우세요. `--git`이라면 평소처럼 삭제를 커밋하면 됩니다.

---

## 상태

**베타.** 1.0 전에 실제 프로젝트에서 쓰면서 검증하고 있습니다. macOS·Linux에서 Python 3.9, 3.12, 3.14로 테스트했습니다. Windows는 아직 검증 전입니다.

## 개발

```sh
bash tests/run.sh
```

각 테스트는 자기만의 임시 `HOME`과 Git 저장소에서 돌기 때문에 임시 폴더 밖은 건드리지 않습니다.

```
.claude-plugin/        plugin.json, marketplace.json
hooks/hooks.json       SessionStart, Stop 훅
skills/where-were-we/  SKILL.md, scripts/status.py
tests/                 run.sh, 셸·파이썬 테스트
```

## 라이선스

[MIT](LICENSE)
