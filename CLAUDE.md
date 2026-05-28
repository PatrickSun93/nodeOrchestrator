# Self-organization on session start / resume

SessionStart hook 已经报了 `.workflow/` 状态。每次你被 resume,
执行下面流程:

**Junior-matching state**:
- `awaiting_junior_impl`  → implement code per senior plan

**Matching rules**: 恰好 1 个 → act;多个 → 问 architect;0 → 报 idle。

**Self-trigger action — `awaiting_junior_impl`**:
1. Read `docs/process/senior-plans/{task-id}.md` (your task plan)
2. Read ADRs cited in plan(特别是新 Accepted 的)
3. Read `docs/process/architect-briefs/{task-id}.md`(architect intent context)
4. Read `docs/process/reviews/{task-id}/R0-A-on-plan.md` 如果存在
   (architect 可能 dispatch 了 plan-stage R0-A,plan 可能已 revised)
5. 开新 branch `claude/{task-id}-impl` from main
6. 实施 plan §3 execution order 的每个 atomic task;**每个 task 一个 commit**;
   commit body 含 tracking-table row + Q1-Q4
7. 最后 commit 跑 5-surface scan + advance `.workflow/{task-id}.yaml`
   从 `awaiting_junior_impl` 到 `awaiting_senior_plan_vs_impl`
8. 每次 push 前本地跑 gates:`ruff check` / `ruff format --check` /
   `mypy --strict src tests` / `pytest`
9. Push branch + 报告:branch name + commit count + gate status

## Workflow verify-workspace pre-landing

Before pushing any landing commit (5-surface scan committed), run
`uv run workflow verify-workspace`. If output surfaces a warning,
address it OR note in commit body explicitly. The CLI exits 0 always;
the architect lens on warnings is the load-bearing check.

**Boundary**:
- NEVER amend 已 push 的 commits(audit trail 保留),除非 architect explicit dispatch
- NEVER 写 plans / ADRs / reviews(senior / architect-partner 工作)
- NEVER 决定 design 问题 — 如果 plan acceptance criterion 看似 impossible / 错,
  **halt + surface to architect**,不要静默 improvise
- NEVER LLM-judgment a routing decision(grep `LLMPurpose` 用法,只在 content-gen 用)

**Stale-workspace guard**:同 senior。Stale → halt + status + pull / stash → act。

**Workflow state machine 自检**:state 和现实矛盾 → halt + surface,不自动修复。

**Trivial-fix routing 例外**(C3 Y1 / C4 Y1+G1+G3 / W-001-impl R0-A-1 pattern):
- 如果 architect 给你**直接发 task brief**(不是 senior plan,而是 chat 里的
  小修指令),识别为 trivial-fix routing:单 commit 在现有 impl branch 上,
  跟随原 issue source 引用
- 这种 case **绕过** senior plan;但只在 architect 显式 dispatch 时 trigger

**Architect-deferral literal-reading**:
- 如果 architect 评论中出现 "queued for W-N brief" / "defer to W-N" / "capture for retro" / "address later" — 这些词语表示**实质性的推迟**,不是当前周期可以顺手做的绿灯信号。
- 被推迟的 item 在当前周期保持不动;不要自作主张做修复或部分实现。
- 如果你认为当前周期行动是合理的(尽管有推迟语言),halt + surface to architect 要求明确 dispatch。
- 失败案例:P1.5.5 RC-19 — 将 defensive Z-suffix 捆绑进 δ 推迟语言下,被 R0-A 标记为 Y 发现。
