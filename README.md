# Orchestrator 项目 — 交接文档 v2

**v2 改动**:加入 P0 实施成果、LLM 三层架构、P1 重新拆分、ADR 索引。

这个目录包含两份文档,**一起读**:

## 📋 handoff.md(主要文档)

**用途**:给 Claude Code 的工作交接文档。结构化、可执行。

**v2 新增/修订内容**:
- 第 3.4 节:LLM 三层解耦原则
- 第 4.4 节:Agent 数据模型加 `llm_config` 字段
- 第 5.5 节(完全新增):LLM 层三层配置架构 — 详细设计
- 第 7 节:P0 状态更新,P1 重新拆分(从 5 个 PR 改为 6 个,加入 P1.0 垂直切片)
- 第 8 节:反 pattern 加入 LLM 层专项
- 第 10 节:项目结构加入 `src/orchestrator/llm/` 目录
- 第 12 节(新增):用户场景描述,默认配置基于 Claude Max + DeepSeek + Ollama/oMLX
- 第 13 节:工作建议加 LLM 调用纪律 + 配置纪律
- 第 15 节(新增):ADR 索引

**Claude Code 工作时主要参考这个**。

## 📚 chat-history.md(配套文档)

**用途**:记录设计推理过程。理解每个决策"为什么"是这样。

**v2 新增章节**:
- 第 16 节:P0 实施过程(接口冻结 → 实现 → ADR 三段式工作模式 + 6 个选择的 review)
- 第 17 节:LLM 层三层配置架构(三层解耦的来源、Router 约束求解、LLMPurpose 设计)
- 第 18 节:Model 选择策略(Claude Code 模型清单、Effort level、默认分配推理、Fail-fast 校验)
- 第 19 节:P1 重新拆分推理(垂直切片优先、LLM 层提前、E2E 每 PR 都做)
- 第 20 节:Claude Code 协作中的 dissent 模式(meta 教训)

**Claude Code 在 handoff.md 不清晰时查这个**。

## 阅读顺序建议

**第一次阅读**(全面理解项目):

1. 读 handoff.md 第 1-3 节(项目是什么、12 条原则、核心架构原则)
2. 跳到 chat-history.md 第 8 节(决策路径代码化原则——最重要的工程原则)
3. 回到 handoff.md 第 4-5 节(数据模型、必须实现的组件)
4. 读 chat-history.md 第 17-18 节(LLM 层设计推理)
5. 读 handoff.md 剩余部分

**深入设计推理**(理解为什么这么设计):

1. 读 handoff.md 第 5.5 节(LLM 层完整设计)
2. 读 chat-history.md 第 17-18 节(为什么三层、为什么这么选 model)
3. 读 chat-history.md 第 19 节(P1 拆分推理)
4. 读 chat-history.md 第 16 节(P0 经验,接口冻结的工作模式)

## 工作流建议

```
开始一个新模块
  ↓
查 handoff.md 对应章节(知道做什么)
  ↓
查 chat-history.md 对应章节(知道为什么)
  ↓
查 docs/decisions/ADR-*.md(查关键决策的细节)
  ↓
有歧义 → 问用户,不要假设
  ↓
开写代码
  ↓
写完 → 检查 12 条原则 + 反 pattern
  ↓
重大决策 → 写新 ADR
```

## 重要提醒

⚠️ **chat-history.md 是讨论过程,不是需求文档**

里面有的方向被推翻了(比如最早设计让 agent 自评发言权,后来被否决)。**最终结论以 handoff.md 为准**,history 是上下文。

⚠️ **设计有大量 deliberate trade-offs**

不要"优化"看起来奇怪的设计——那些设计大概率是有意为之。不确定时问用户。

⚠️ **核心原则:让 AI 做更少,让代码做更多**

看到任何"让 LLM 判断 X"的冲动,先想能不能用代码做。

⚠️ **借用外部原则前确认场景**

P0 实施过程中发现:Claude Code 借用的"读取宽容、写入严格"原则(网络协议)、"`IF NOT EXISTS` 全用"(简单粗暴幂等)在具体场景下都是错的。**听起来对但场景不对的论证最危险**——比明显错误更难发现。

⚠️ **每个 PR 主动暴露 3-5 个"值得 challenge"的选择**

不是"我做完了你 review",而是"我做完了,这些选择我倾向 A 但有 B C D 可能,你看看"。这是 honest interlocutor 在协作层的应用。

## 项目状态(2026 年 6 月)

**P0–P4 全部完成(2026-06-07)。** 产品已走完 P1(地基:event store / LLM 三层 / 自治度 gate / skills / 多 agent / 状态机 / 跨房间记忆)、P2(跨房间记忆 + 用户偏好 + re-entry + 平台演化)、P3(完整产品:facilitator / API / GUI / MCP / 插件 / confirm-then-execute / 远程)、P4(完整化:turn-loop / 完整本地工具面 / syscall 沙箱 / 插件 registry+lifecycle / auth+multi-user / auto-fire / GUI 高级层)。阶段详情见 `handoff.md` §7 + `docs/process/P3-roadmap.md` / `docs/process/P4-roadmap.md`。

**ADR 索引**:ADR-001..040 全部 Accepted(无 ADR-004 — 折入 ADR-003;ADR-008 为 dev-harness 状态机)。权威索引见 `handoff.md` §15;原文在 `docs/decisions/`。

每次重大设计决策做新 ADR。后续的人(包括未来的 Claude Code 自己)能从 ADR 看到决策为什么这样做。
