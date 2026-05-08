# Orchestrator 项目 — Handoff 文档

> 这是给 Claude Code 的**工作交接文档**。
> 同目录有 `chat-history.md`,记录了整个设计推理过程。
> 遇到本文档不清晰的地方,**先查 chat-history.md**,再问用户。
> 不要"自由发挥"——这个项目的所有架构决策都是有原因的。

---

## 1. 项目是什么

一个面向独立开发者的 **AI 研究与决策助手**。核心承诺:

> "想清楚一件事,和能挑战你想法的助手一起。"

**关键差异化**:不是 ChatGPT 那种"helpful assistant",而是会 **push back、问问题、不替你做决定** 的助手。设计目标不是"完成任务",是"让用户的判断更准"。

**底层架构**:多 agent orchestrator(用户看不到),通过房间(rooms)、事件流(event stream)、跨房间记忆来组织协作。

---

## 2. 必读:12 条设计原则(系统宪法)

**所有架构决策必须遵守这 12 条**。如果某段代码违反其中一条,就是错的。

1. **Honest interlocutor > obedient executor** — Agent 目标是让人判断更准,不是完成任务
2. **Dissent 必须显式设计进去** — LLM 默认 helpful,要刻意让它会 push back
3. **Forced ranking, never menus** — 多选项必须 ranked + 理由,不是平铺让用户选
4. **Structured uncertainty** — 不要 "可能/大概",要 confidence + key_uncertainties
5. **"问回去" 是 first-class output** — Agent 可以反弹问题给用户,不是失败
6. **Multi-perspective by default** — 不要 average 成 consensus,显式呈现分歧
7. **Continuity of thinking** — 维持长 arc 思考,不只是 task 衔接
8. **跨域迁移是工具** — Agent 可以从其他 domain 借经验
9. **术语审计** — 模糊术语要拆开定义,不在歧义上累积复杂设计
10. **环境塑造 agent,agent 不塑造自己** — 改进在环境层,不让 agent 自我修改
11. **没有 ground truth → 所有"improvement" 都是 drift** — 必须 anchor 在客观信号
12. **Stable agents in evolving environments** — Agent 稳定可预测,环境可演化

---

## 3. 核心架构原则

### 3.1 决策路径用代码,内容生成用 LLM

**这是最重要的架构原则**。前面 12 条的工程化推论。

- "什么时候做"、"是否允许"、"召唤谁"、"切到什么状态"、"喂什么上下文" → **代码**
- "写什么"、"怎么思考"、"如何回应" → **LLM**

具体来说,这些**必须用代码**实现,**不要用 LLM 判断**:
- 自治度评分(risk_score)
- 操作放行规则
- 状态机切换
- Agent 发言权决策(should_agent_speak)
- 召唤决策
- 摘要触发时机
- 关键节点提升(从事件 type 自动转换)
- 关系提取(结构性关系)
- 上下文窗口构建
- 决策日志维护
- 跨房间记忆调取
- 晋升资格判定
- 角色绑定与约束验证

LLM 只在以下场景调用:
- Agent 生成回应内容
- Snapshot 的语义字段(current_focus、key_uncertainties)
- 解读工具结果

### 3.2 没有复合工具

**只做基础原语和领域原语**。不要做 `refactor_function()`、`research_topic()` 这种"做一切"的复合工具。Agent 通过组合小工具完成复杂任务。

理由见 chat-history.md 中"复合工具"讨论。

### 3.3 Skills/MCP/Plugins 三层

- **MCP**: 外部世界的连接(GitHub、Postgres 等),作为插件不是核心
- **Skills**: SKILL.md 格式,Agent 的"心智剧本",兼容业界标准
- **Plugins**: 分发单元,打包 skills + tools + MCP 配置 + roles

---

## 4. 数据模型(关键数据结构)

### 4.1 Event(事件)

事件流是系统的**单一真相来源**。append-only,永不修改。

```python
class Event:
    id: str
    parent_id: Optional[str]    # 线程化,父消息 id
    room_id: str
    timestamp: datetime
    
    # 核心:type 字段决定语义
    type: Literal[
        "user_input",
        "utterance",          # 普通发言
        "hypothesis",         # 假设
        "decision",           # 决策
        "rejection",          # 否决
        "retraction",         # 撤销
        "observation",        # 观察 / 数据
        "tool_call",
        "tool_result",
        "tool_failed",
        "escalation",         # 问回去
        "summary_snapshot",
        "state_transition",
        "milestone",
        "term_definition",
        "decision_pivot",     # reframe
    ]
    
    author: str               # user 或 agent_id
    content: str
    metadata: dict
```

### 4.2 Room(房间)

```python
class Room:
    id: str
    type: Literal["free_chat", "bug_fix", "research", 
                  "code_review", "idea_validation"]
    state: str                # 取决于 type 的状态机
    created_at: datetime
    
    agents: list[Agent]       # 在场的 agent
    tools: list[Tool]         # 可用工具(根据 type)
    skills: list[Skill]       # 加载的 skill
    
    user_id: str
    project_id: Optional[str]
```

### 4.3 自治度评分

```python
@dataclass
class Operation:
    op_type: str
    target: str
    params: dict
    initiating_agent: str
    user_explicit_request: bool
    estimated_cost_usd: float
    metadata: dict

class AutonomyLevel(Enum):
    FORBIDDEN = 0
    APPROVAL_REQUIRED = 1
    NOTIFY_AND_EXECUTE = 2  
    AUTO_EXECUTE = 3

# 6 个评分维度,各 0-10
# - reversibility
# - blast_radius
# - data_sensitivity
# - cost_impact
# - decision_finality
# - user_intent
```

完整实现见 chat-history.md "自治度评分"章节。

### 4.4 Agent

```yaml
# agent 通过 YAML 配置,运行时不可改
agent:
  id: str
  role: str
  persona: str
  
  dissent_dimensions: list[str]
  cross_domain_borrowing: list[str]
  forbidden_behaviors: list[str]
  
  # 发言权规则(代码层用,不喂给 LLM)
  speaking_triggers:
    - regex / event_type / state_change
  
  cooldown_seconds: int
  
  # 输出 schema 强制
  output_schema: JSONSchema
```

### 4.5 跨房间记忆

四类,**严格分开**:

```python
# 1. 待验证 pool
class Hypothesis:
    id: str
    content: str
    room_id: str
    confidence: float
    source_event_ids: list[str]
    status: Literal["pending", "verified", "rejected", "stale"]

# 2. 已验证(参与跨房间检索)
class VerifiedKnowledge:
    id: str
    content: str
    topic_tags: list[str]
    evidence: dict
    last_validated: datetime
    contradictions: list[str]
    scope: Literal["personal", "team", "global"]

# 3. 实体
class Entity:
    id: str
    type: Literal["person", "project", "concept", "paper"]
    attributes: dict

# 4. 项目档案
class ProjectArchive:
    room_id: str
    one_line_summary: str
    decision_log: list[DecisionLogEntry]
    spinoff_questions: list[str]
```

**晋升规则**:不自动晋升。需要满足一个:
- 跨 N 个独立房间被独立得出
- 用户显式确认
- 外部 ground truth 验证

---

## 5. 必须实现的组件

### 5.1 内置 Agent(5 个核心)

每个 agent 写一个 YAML 配置文件,放在 `config/agents/`。

| Agent | role | 何时在场 |
|-------|------|---------|
| prober | 探查者 | 所有房间默认 |
| skeptic | 质疑者 | 研究类、决策类 |
| operator | 执行者 | 所有房间默认 |
| divergence_mapper | 分歧地图 | 研究类、决策类 |
| logger | 记录者 | 所有房间默认(背景) |

详细的 dissent_dimensions、forbidden_behaviors 等,见 chat-history.md "内置 Agent 库"。

### 5.2 房间模板(5 个核心)

| 模板 | type | 默认 agents |
|------|------|------------|
| 自由对话 | free_chat | prober, operator |
| 修 bug | bug_fix | operator(单 agent) |
| 做研究 | research | 全部 5 个 |
| 评审代码 | code_review | operator, skeptic |
| 验证想法 | idea_validation | 全部 5 个 + 强 skeptic |

### 5.3 Skill 库(MVP 10 个)

```
skills/
├── general/
│   ├── research-decomposition.md
│   ├── comparative-analysis.md
│   ├── cost-modeling.md
│   └── assumption-audit.md
├── engineering/
│   ├── debugging-workflow.md
│   ├── null-safety-patterns.md
│   └── code-review-checklist.md
└── business/
    ├── idea-decomposition.md
    ├── willingness-to-pay-analysis.md
    └── competitor-analysis.md
```

每个 skill 用标准 SKILL.md 格式(详见 chat-history.md "Skill 库")。

### 5.4 工具集

**第一层(永远在场)**:
- read_file(path, range=None)
- list_files(directory, recursive=False)
- search_text(query, scope=None)
- search_code(pattern, scope=None)
- web_search(query)
- web_fetch(url)
- get_current_time()
- log_event(content, type)

**第二层(按房间类型加载)**:
- find_references, find_definition
- git_blame, git_log, git_diff
- propose_edit, apply_edit
- run_tests, run_lint
- search_papers, read_paper

**第三层(复合工具)**: ❌ **不做**

每个工具必须有:
- input_schema(JSON Schema)
- output_schema
- base_danger_level (0-10)
- is_destructive
- side_effects
- typical_latency_ms
- estimated_cost_per_call

### 5.5 自治度系统

实现以下纯函数,**全部用代码**,不调 LLM:
- `score_reversibility(op) -> int`
- `score_blast_radius(op) -> int`
- `score_data_sensitivity(op) -> int`
- `score_cost_impact(op) -> int`
- `score_decision_finality(op) -> int`
- `score_user_intent(op) -> int`
- `compute_risk_score(op, weights) -> dict`
- `determine_autonomy_level(op, context, custom_rules) -> tuple`

加上规则集:
- 黑名单(永远禁止)
- 白名单(永远自动)
- 上下文规则(生产环境、用户离线、最近失败...)
- 用户自定义规则

### 5.6 状态机

每个房间类型一个状态机,定义在 `config/state_machines/`。

状态切换由**事件触发,不由 LLM 推断**。

### 5.7 持久化

**事件流**:append-only 表,SQLite 起步即可
**记忆系统**:四个独立的存储(hypothesis pool、verified knowledge、entities、project archives)
**配置**:YAML 文件,可 git 版本化

---

## 6. UI 设计规范(Design System)

详见 chat-history.md "Design System" 章节。这里只列出**核心约束**:

### 6.1 视觉约束

- **色彩**:5 种语义色 + 中性色,同界面 ≤ 3 种语义色
  - 蓝色(`#185FA5` / `#E6F1FB`):AI 身份,**仅此一处用**
  - 绿色(`#0F6E56` / `#E1F5EE`):已确认 / 完成
  - 琥珀(`#BA7517` / `#FAEEDA`):挑战 / 留意
  - 红色(`#A32D2D` / `#FCEBEB`):拒绝 / 错误
  - 紫色(`#534AB7` / `#EEEDFE`):关键节点(稀有)

- **字号**:只用 22/16/14/13/12/11px
- **字重**:只用 400 / 500
- **间距**:只用 4/8/12/16/24px
- **圆角**:8px(按钮、输入)、12px(卡片)、50%(头像)
- **不用**:渐变、阴影、霓虹、内联 emoji
- **图标**:Tabler Icons outline 版本

### 6.2 文案约束

**永远不出现的术语**(用人话替代):
- agent → "助手"
- snapshot → "进展"
- memory → "经验" / "学到的"
- skill → 不暴露
- autonomy level → "工具调用"
- dissent dimension → "挑战"
- divergence map → "分歧"
- state machine → 不暴露
- key node → "关键节点"

**所有 UI 文案统一在 `config/ui_strings/` 中管理**,不要硬编码在组件里。

### 6.3 交互约束

- **进入即工作**:打开到能打字 ≤ 5 秒
- **关键时刻明显**:决策 / 审批 / 撤回 / 错误必须有视觉强调
- **复杂度渐进暴露**:高级功能折叠,默认隐藏
- **可逆**:决策可撤回,设置可重置

### 6.4 5 个核心 Pattern

1. **AI 多视角**:同一个 ✨ 头像 + 嵌入式 callout 表达不同视角
2. **决策三段式**:排序 → trade-off → 确认
3. **进展面板**:右侧 280px 可折叠,4 块结构(讨论中/已建立/待决定/我会push)
4. **复杂度分层**:L1 主界面(95%) → L2 设置(4%) → L3 高级(1%) → L4 配置(0.1%)
5. **离开/回来对称**:离开生成摘要,回来显式追平

---

## 7. 实施优先级(MVP → 完整产品)

### P0 — 最小可用(目标:能跑起来)

1. 单 agent (operator) + free_chat 模板
2. 5 个基础工具(read、search、web_search、web_fetch、log)
3. 事件流 + 简单 GUI(只有对话)
4. 自治度最简版(只有黑白名单,没有评分)
5. 持久化用 SQLite

**验收**:能开房间、能打字、AI 能回应、能看到工具调用、能保存历史。

### P1 — 有差异化(目标:能展示价值)

6. 加 prober 和 skeptic
7. 加 research 模板
8. 实现 5 个 skill
9. 完整的自治度评分系统
10. 进展面板(snapshot)

**验收**:能跑研究类对话、能感受到 push back、能看到结构化进展。

### P2 — 有粘性(目标:用户愿意回来)

11. 跨房间记忆系统(hypothesis pool + verified knowledge)
12. 状态机
13. 用户偏好系统
14. 离开/回来追平体验

**验收**:第二次使用能看到"AI 记得我"。

### P3 — 完整产品

15. 加更多 agent / 模板
16. 加更多 skill
17. Plugin 系统
18. MCP 集成

---

## 8. 关键反 pattern(不要做)

❌ 让 agent 自己决定要不要发言(用规则)
❌ 让 LLM 评估自己输出的质量(没有 ground truth)
❌ 让 agent 自动修改 prompt / persona(环境由人塑造)
❌ 自动把 LLM 提取的内容入跨房间记忆(必须显式晋升)
❌ 用 LLM 做意图分类、状态切换判断(用代码)
❌ 把 agent 名字暴露给用户(用统一"助手"声音)
❌ 让用户配置 5 个 agent(系统内置,用户选房间模板)
❌ 复合工具(让 agent 用小工具组合)
❌ 自由文本摘要(用 decision log + structured snapshots)
❌ 让用户从头读 247 条消息追平(用追平摘要)

---

## 9. 测试场景(必须能跑通)

### Scenario 1: Bug 修复(单 agent)

用户报告 bug → operator 诊断计划 → 工具调用链 → 提议修复方案(ranked) → 审批 diff → 应用修改 → 跑测试 → 决策日志。

详见 chat-history.md "修 bug 走查"。

### Scenario 2: 研究(多 agent,跨多天)

用户提问 → prober 拆解 → skeptic 挑战 → operator 找数据 → divergence_mapper 地图化 → snapshot → 用户离开 → 回来追平 → reframe → 决策 → 跨房间记忆晋升。

详见 chat-history.md "做研究走查"。

---

## 10. 项目结构建议

```
your-orchestrator/
├── config/
│   ├── agents/                  # 5 个 agent YAML
│   ├── room_templates/          # 5 个房间模板
│   ├── skills/                  # SKILL.md 文件
│   ├── autonomy/
│   │   ├── operation_classification.yaml
│   │   ├── context_rules.yaml
│   │   ├── defaults.yaml
│   │   └── scoring.py           # 评分函数
│   ├── state_machines/
│   ├── ui_strings/              # 文案库
│   └── user_preferences/
├── src/
│   ├── core/                    # Event store、Room、State machine
│   ├── agents/                  # Agent loader、execution
│   ├── tools/                   # 工具实现
│   ├── memory/                  # 跨房间记忆
│   ├── autonomy/                # 自治度系统
│   ├── skills/                  # Skill 加载
│   └── ui/                      # GUI(React 推荐)
├── tests/
│   ├── agents/
│   ├── tools/
│   ├── scenarios/               # 端到端场景
│   └── fixtures/
└── docs/
    ├── architecture.md
    ├── 12-principles.md
    └── extending.md
```

---

## 11. 技术栈建议

- **后端**:Python(LLM 生态成熟)
- **数据库**:SQLite(MVP)→ Postgres(规模)
- **前端**:React + TypeScript
- **UI 库**:不要用 Material UI 之类(太重),自己实现轻量组件
- **LLM API**:Anthropic Claude(通过官方 SDK)
- **图标**:Tabler Icons
- **状态管理**:Zustand 或 Jotai(不要 Redux,太重)

---

## 12. 给 Claude Code 的工作建议

1. **先读 chat-history.md** — 至少读一遍,了解每个决策为什么是这样
2. **从 P0 开始** — 不要一开始就做完整功能
3. **遵守反 pattern** — 第 8 节的红线不要碰
4. **保持 12 条原则** — 每写一个模块,问自己违反了哪条
5. **用代码做决策** — 看到任何"可以让 LLM 判断 X"的冲动,先想能不能用代码做
6. **小工具组合** — 不要做万能工具
7. **UI 文案别硬编码** — 都进 config/ui_strings/
8. **写测试** — 自治度评分、状态机、Skill 加载这些纯函数必须有测试
9. **不确定时问用户** — 这个项目的设计有非常多 deliberate trade-offs,不要假设

---

## 13. 已知未解决的问题

这些问题在 chat-history.md 里讨论过但没定论,需要后续决定:

1. **agent 是否完全隐藏 vs 显示"模式切换"** — 当前倾向完全隐藏,但可能影响多视角的视觉冲击
2. **跨 agent 上下文一致性** — 5 个 agent 看到不同上下文,可能有不一致
3. **术语审计的 false positive** — 某些词出现频率高是因为是讨论主题,不是模糊
4. **Retraction 的级联** — 撤回早期决策可能影响多个后续决策,UI 怎么处理
5. **长时间运行的成本** — 4 天研究 ~$2,如果用户跑 100 个项目就是 $200,需要长期优化

---

## 14. 联系信息

设计者:用户(独立开发者)
推理过程:见同目录 chat-history.md
设计语境:2026 年,LLM 生态已成熟(MCP、Skills、Plugins 三层架构成型)

---

**最后一句话**:这个项目的核心价值不在"AI 多聪明",在"AI 让人更清楚"。如果你写的代码让 AI 替用户做决定,你就走错方向了。
