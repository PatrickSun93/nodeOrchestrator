# Orchestrator 项目 — Handoff 文档 v2

> **v2 改动(相对 v1)**:加入 LLM 层三层配置架构、model 选择策略、P0 实施细节(已完成接口冻结)、P1 重新拆分。
>
> 这是给 Claude Code 的**工作交接文档**。
> 同目录有 `chat-history.md` 记录设计推理过程。
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
4. **Structured uncertainty** — 不要"可能/大概",要 confidence + key_uncertainties
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
- **Model 选择**(基于 agent 配置 + capabilities + fallback chain)

LLM 只在以下场景调用:
- Agent 生成回应内容
- Snapshot 的语义字段(current_focus、key_uncertainties)
- 解读工具结果

**所有 LLM 调用必须带 `purpose: LLMPurpose` 字段**(见第 5.5 节)。

### 3.2 没有复合工具

**只做基础原语和领域原语**。不要做 `refactor_function()`、`research_topic()` 这种"做一切"的复合工具。Agent 通过组合小工具完成复杂任务。

### 3.3 Skills/MCP/Plugins 三层

- **MCP**: 外部世界的连接(GitHub、Postgres 等),作为插件不是核心
- **Skills**: SKILL.md 格式,Agent 的"心智剧本",兼容业界标准
- **Plugins**: 分发单元,打包 skills + tools + MCP 配置 + roles

### 3.4 LLM 层三层解耦(新增)

**Connection / Model / Agent 三层严格分开**。详见第 5.5 节。

核心:**Agent 配置只引用 model_id 字符串,不绑定 provider**。切换 LLM provider(DeepSeek → OpenAI → 本地)只改 Layer 2,不动 agent 配置。

---

## 4. 数据模型(关键数据结构)

### 4.1 Event(事件)

事件流是系统的**单一真相来源**。append-only,永不修改。

```python
class Event:
    id: str                       # evt_<32-hex>
    parent_id: Optional[str]      # 线程化,父消息 id
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
        # 后续可能增加:llm_call, user_callout_response 等
    ]
    
    author: str               # "user" / "agent:<id>" / "system"
    content: str
    metadata: dict            # type-specific schema(见下)
```

**Author 格式约定**:
- `user` — 用户输入
- `agent:<id>` — agent 输出,如 `agent:prober_01`
- `system` — 系统事件(状态切换、错误等)

### 4.2 Room(房间)

```python
class Room:
    id: str                   # room_<32-hex>
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
  
  # LLM 配置 — 见 5.5 节
  llm_config:
    default_model: str          # model profile id
    fallback_chain: list[str]   # model profile ids
    model_overrides: dict       # purpose → model id
    required_capabilities: list # 如 ["tools"]
    temperature: float
    max_tokens: int
  
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

每个 skill 用标准 SKILL.md 格式。

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

### 5.5 LLM 层(三层配置架构)— 详细设计

**这是 P1.1 的核心交付**。架构上 LLM 不是"换 provider 就行"的小事,而是整个系统的认知层。

#### Layer 1: Provider Connections(物理层)

```yaml
# config/llm_providers.yaml — top-level key is `providers:` (map form).
# Provider id is the map key; type-specific config goes under `params:`.
# Canonical reference: config/llm_providers.yaml.example.

providers:
  deepseek:
    type: openai_compatible
    params:
      base_url: https://api.deepseek.com/v1
      api_key_env: DEEPSEEK_API_KEY

  ollama_local:
    type: openai_compatible
    params:
      base_url: http://localhost:11434/v1
      api_key_env: ""        # local — no auth header

  mlx_local:
    type: openai_compatible
    params:
      base_url: http://localhost:8080/v1
      api_key_env: ""

  anthropic_via_claude_code:
    type: claude_code_cli
    params:
      cli_path: claude
      timeout_s: 600
```

**Provider type 只有两种**(P1):`openai_compatible` 和 `claude_code_cli`,加上测试用的 `mock`。其他 backend(DeepSeek、Ollama、MLX、未来 OpenAI/OpenRouter)都通过 `openai_compatible` + 不同 base_url 实现。

#### Layer 2: Model Profiles(逻辑层)

```yaml
# config/llm_models.yaml — top-level key is `models:` (map form).
# Model id is the map key; fields are flat (no `params:` sub-map).
# Canonical reference: config/llm_models.yaml.example.
# Capability values come from `Capability` enum: tools / effort /
# vision / json_mode (vision and json_mode are P2+ placeholders).

models:
  # === Claude Code via Max subscription quota ===
  claude_code_opus_47:
    provider: anthropic_via_claude_code
    provider_model_id: claude-opus-4-7      # passed to --model
    capabilities: [effort]
    default_effort: xhigh                    # honored by EFFORT capability
    context_window: 1000000
    # Subscription quota — pricing not exposed at the API surface,
    # so cost_per_1m_input / cost_per_1m_output are omitted.

  claude_code_sonnet_46:
    provider: anthropic_via_claude_code
    provider_model_id: claude-sonnet-4-6
    capabilities: [effort]
    default_effort: high
    context_window: 1000000

  claude_code_haiku_45:
    provider: anthropic_via_claude_code
    provider_model_id: claude-haiku-4-5
    capabilities: []                         # no effort, no tools
    context_window: 200000

  # === DeepSeek (OpenAI-compatible API) ===
  deepseek_v4_flash:
    provider: deepseek
    provider_model_id: deepseek-v4-flash
    capabilities: [tools]
    context_window: 128000
    cost_per_1m_input: 0.07
    cost_per_1m_output: 0.27

  deepseek_v4_pro:
    provider: deepseek
    provider_model_id: deepseek-v4-pro
    capabilities: [tools]
    context_window: 128000
    cost_per_1m_input: 0.27
    cost_per_1m_output: 1.10

  # === Local (MLX or Ollama) ===
  qwen_mlx_30b:
    provider: mlx_local
    provider_model_id: qwen2.5-30b-instruct
    capabilities: [tools]
    context_window: 32000
    # No cost — local hardware.
```

**关键设计**:`capabilities` 是必填字段。Router 用它做约束求解。

#### Layer 3: Agent llm_config

每个 agent 的 yaml 文件包含 `llm_config`:

```yaml
# config/agents/prober.yaml.example
llm_config:
  default_model: claude_code_sonnet_46
  fallback_chain: [deepseek_v4_flash]   # default 不重复列入(ADR-002 §3)
  temperature: 0.5

# config/agents/skeptic.yaml.example
llm_config:
  default_model: claude_code_opus_47    # Opus 4.7 给最难的角色
  fallback_chain: 
    - claude_code_sonnet_46
    - deepseek_v4_pro
  temperature: 0.3                       # 稳定输出

# config/agents/divergence_mapper.yaml.example
llm_config:
  default_model: claude_code_sonnet_46
  fallback_chain: [deepseek_v4_flash]

# config/agents/logger.yaml.example
llm_config:
  default_model: claude_code_haiku_45    # 浓缩日志,要快
  fallback_chain: [deepseek_v4_flash]
  temperature: 0.2

# config/agents/operator.yaml.example
llm_config:
  default_model: deepseek_v4_flash       # 必须 API,Claude Code 不能调 orchestrator tools
  fallback_chain: [qwen_mlx_30b]
  required_capabilities: [tools]         # 启动时校验 fallback 全部支持 tools
```

#### Layer 4: 全局覆盖(P2,**不在 P1 实施**)

未来支持"省钱模式"、"高质量模式"全局覆盖,P1 不做。

#### LLMPurpose Enum(必须)

每次 LLM 调用必须带 `purpose` 字段:

```python
# src/orchestrator/llm/purposes.py — canonical list lives in code.
# Per-agent role discrimination uses LLMRequest.caller_agent_id, not
# separate enum values — adding a new agent role does not require
# extending the enum.
from enum import StrEnum

class LLMPurpose(StrEnum):
    # Agent-driven content generation. Each agent role files responses
    # under this purpose; caller_agent_id discriminates.
    AGENT_RESPONSE = "agent_response"

    # Structural LLM uses — each one is a load-bearing trade-off.
    SNAPSHOT_SEMANTIC = "snapshot_semantic"
    HYPOTHESIS_CANDIDATE = "hypothesis_candidate"
    KEY_NODE_CANDIDATE = "key_node_candidate"
    TOOL_OUTPUT_INTERPRET = "tool_output_interpret"
    TERM_DEFINITION_PROPOSAL = "term_definition_proposal"

    # Adding a new value requires an ADR explaining why no code path
    # was sufficient. PR template Q1 enforces this at review time.
```

**好处**:
- 添加 purpose 是显性决定(改 enum + ADR)
- PR review 时 `grep "LLMPurpose\."` 列出所有 LLM 用法
- 每个 purpose 注释解释为什么必须用 LLM

#### Provider 能力声明

```python
class LLMProvider(Protocol):
    @property
    def provider_id(self) -> ProviderId: ...

    def can_use_orchestrator_tools(self) -> bool: ...

# 实现:
# OpenAICompatibleProvider: True
# ClaudeCodeCLIProvider: False
# MockProvider: 可配置
```

**重要含义**:
- prober、skeptic、divergence_mapper、logger 这种"纯思考"agent 可以用 Claude Code(它们不调工具)
- **operator 必须用 API**(它要调工具)
- 启动时验证:每个 agent 的 fallback_chain 至少有一个可用 model 满足 required_capabilities,否则 fail-fast

#### Tool calling 策略(策略 3 — purpose 决定)

需要 tools 的 purpose:由 `req.tools` 是否非空决定。Router 在 `req.tools` 不空时过滤掉 `can_use_orchestrator_tools=False` 的 provider。

#### Router 的工作

```python
async def select_model_and_provider(
    agent_config: AgentLLMConfig,
    request: LLMRequest,
    models: ModelRegistry,
    providers: ProviderRegistry,
) -> RouteResult:
    """
    完全代码决策,无 LLM 介入。
    
    1. agent.llm_config.model_overrides[req.purpose] 优先
    2. fallback to agent.llm_config.default_model
    3. (P2) 应用 global overrides
    4. 验证 capabilities(req.tools 不为空 → model 必须支持 tools)
    5. 验证 context window(estimated tokens < 80% window)
    6. 失败走 fallback_chain
    7. 全部失败 raise NoSuitableModelError
    """
```

#### CLI Provider 实施要点

1. **录像测试基础设施**:每个 Claude Code 版本录"标准输出"作 fixture,parser 改动跑录像比对
   ```
   tests/llm/providers/claude_code_cli/recordings/
     v2.1.131/
       simple_response.txt
       simple_response.expected.json
       with_thinking.txt
       with_thinking.expected.json
   ```
2. **`max_concurrent=1`**(P1 完全串行,后续优化)
3. **接受 200-500ms subprocess 启动开销**(P1 不优化)
4. **认证不管**(假设用户已经 `claude login`)
5. **不暴露 `ANTHROPIC_BASE_URL`**(P1 仅支持 Claude Code 接 Anthropic 自家 model,不接 Ollama 等。这是 P2 功能)

### 5.6 自治度系统

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
- 上下文规则
- 用户自定义规则

### 5.7 状态机

每个房间类型一个状态机,定义在 `config/state_machines/`。
状态切换由**事件触发,不由 LLM 推断**。

### 5.8 持久化

**事件流**:append-only 表,SQLite 起步即可
**记忆系统**:四个独立的存储
**配置**:YAML 文件,可 git 版本化

---

## 6. UI 设计规范(Design System)

详见 chat-history.md "Design System" 章节。这里只列**核心约束**:

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

## 7. 实施优先级(更新版)

### P0 — 事件流地基 ✅ 已完成接口冻结

完成的部分(commit 1):
- Event dataclass + 16 种 type 枚举
- Relation dataclass + 4 种 type
- 6 种 typed metadata schema
- 异常类(EventError、InvalidParentError 等)
- ID 生成器、author 校验、metadata 校验(纯函数已实现)
- EventStore 11 个公开方法签名(NotImplementedError)
- extract_structural_relations 签名
- SCHEMA 常量 + append-only TRIGGERS

待完成(commit 2):
- EventStore 11 方法实现
- relations 提取实现
- conftest.py 双 fixture(in_memory + populated)
- test_event.py、test_event_store.py、test_relations.py
- test_constitution.py(test_constitution_append_only_at_schema_level)
- 边角覆盖:parent_not_found、cross_room_parent、self_parent、多 retraction
- 性能基线:test_perf_baseline_get_thread_depth_100

接口 review 中**已确定的修正**:
- `IF NOT EXISTS` 只用于 CREATE TABLE,TRIGGER 用 `DROP IF EXISTS + CREATE`
- `get_thread(unknown_id)` 改为 raise `EventNotFoundError`(不返回 [])
- `InvalidParentError` 加 `reason: Literal["cross_room", "self_parent", "not_found"]` 字段
- 索引改为 `(room_id, timestamp, id)` 三列(让 ORDER BY 完全走索引)
- Fixture 加 retraction 节点(8 节点),retraction 是 **decision** 的 child(详见 ADR-001 §8;接口冻结期我倾向 hypothesis 的 child 演示 fork 语义,实现期被反向 push back —— `get_thread(retraction)` 必须包含被 retract 的 decision 才让上下文完整)

待完成(commit 3,独立 PR):
- ADR-001-event-store-foundation.md

### P1 — 完整研究类房间(重新拆分)

**P1 拆成 6 个连续 PR,不是一次合大的**:

```
P1.0  端到端骨架            3-4 天   一个 prober + free_chat + mock LLM,垂直切片
P1.1  LLM provider 抽象     1.5-2 周  三层配置 + openai_compatible + claude_code_cli + Router + 录像测试
P1.2  自治度评分系统         1 周    1 维评分 + 规则引擎 + decision_trace
P1.3  Skill loader          3-5 天   读 SKILL.md + 加载逻辑(代码决定加载哪些)
P1.4  Skeptic + 多 agent     1.5 周   should_agent_speak、召唤决策(代码,不是 LLM)
P1.5  Research room + 状态机  3-5 天   状态由事件触发,非 LLM 推断
P1.6  Snapshot + decision log + 完整 E2E  1 周
```
#### P1.2 详细设计(2026-05-19 land,6-day distance test passed)

P1.2 设计经过两周收敛,从原 handoff "6 维评分" 大幅简化到 "1 维 + Hard Guards 分层" 架构。

**Dimensions: 1 维**

只在 P1.2 score 系统内的维度:
- `reversibility` —— action 能否撤回(continuous 0-10)

剥离到 P1.3 Hard Guards 层(sibling layer,不在 score 内):
- `cost_impact` —— 难以加权,binary trigger 更诚实
- `external_visibility` —— action 离开本地机器
- `destructive` —— 删除 / DROP / rm -rf
- `blast_radius` —— 影响范围(per-parameter,P1.2 type-only 设计无法表达)

剥离到 P1.4+ agent 层(prober/skeptic 处理):
- `model_confidence` —— output quality 问题,不是 action risk

**Score → 行为映射: 3 档 enum**

```AUTO_EXECUTE        : score >= threshold_auto
COUNTDOWN_CONFIRM   : threshold_confirm <= score < threshold_auto
HARD_CONFIRM        : score < threshold_confirm

**user_intent: threshold modifier**(不是 dimension,不是 binary routing)

- user 明确指令 → 两个 threshold 各减去 `user_intent_modifier`
- score 本身不变 → Hard Guards 仍能拦下 "user 一时冲动要删数据库"

**Schema placement**

Reversibility = tool 的物理性质(客观 ground truth)→ `tools.yaml`(project-level)

```yamltools:
web_search:
reversibility: 10
send_email:
reversibility: 3
git_push:
reversibility: 1

约束:
- Per-tool, per-type(P1.2 不支持 per-parameter,per-parameter risk → P1.3)
- 不能 per-agent override(agent 不能 "撒谎" 说 send_email 是 reversible)
- "If reversibility cannot be measured, treat as irreversible" → 默认 conservative low

Threshold = agent 的风险偏好(主观 per-agent)→ `agent.yaml`

```yamlagents:
prober:
threshold_auto: 8        # TODO: tune P1.5+
threshold_confirm: 5     # TODO: tune P1.5+
user_intent_modifier: 2  # TODO: tune P1.5+

Placeholder defaults 全部标 TODO,真值通过 P1.5+ 实际使用 tune 出来。Threshold profile presets(solo_developer / cautious / conservative)defer 到 P1.5 UX 工作。

**P1.2 implementation sub-tasks**

1. `tools.yaml` schema + reversibility loading
2. `agent.yaml` threshold schema + loading
3. `AutonomyScore` 数据结构(continuous + 3 档 enum output)
4. Score 计算函数(action-time / deterministic / type-only)
5. Threshold decision 函数(score + threshold + user_intent_modifier → 3 档)
6. Integration with event stream(emit 决策 event)
7. Tests(test-coverage-standard 6 categories)
8. `#3`: `COUNTDOWN_CONFIRM` 的 UI 接口契约(state machine,backend authoritative)
9. `#4`: P1.3 Hard Guards framework placeholder(架构占位,不实现)

**P1.2 design 集中决策(6-day distance test 通过)**

- ✅ Dimensions = 1(architecture converge,6/7 维度推到 P1.3 / P1.4+)
- ✅ Reversibility 在 tools.yaml(物理性质,project-level ground truth)
- ✅ Threshold 在 agent.yaml(per-agent 风险偏好)
- ✅ user_intent = threshold modifier(不是 dimension,不是 binary routing)
- ✅ 3 档 enum 输出(AUTO / COUNTDOWN / HARD)
- ✅ Hard Guards 是 sibling layer(P1.3,独立于 score 系统)
- ✅ Per-type only(per-parameter risk → P1.3)
- ✅ Constitutional principle: "If cannot reliably quantify, prefer binary trigger over continuous score"

**关键调整**(相对原 P1):
- 加入 P1.0 垂直切片(端到端骨架),避免 big bang integration
- LLM 层提前到 P1.1(原是 P1.2 后半),因为是核心基础设施
- E2E 测试每个 PR 都做(不是 P1.6 一次做)

**P1 验收**:能跑研究类对话、能感受到 push back、能看到结构化进展。

### P2 — 跨房间记忆 + 状态机演化

跨房间记忆系统、状态机切换、用户偏好系统、离开/回来追平体验。
**P2 验收**:第二次使用能看到"AI 记得我"。

P2 还包括:
- LLM 层 Layer 4(全局覆盖,省钱/质量模式)
- Claude Code 接 alt backend(`ANTHROPIC_BASE_URL` 配置)
- 友好版启动错误信息

### P3 — 完整产品

加更多 agent / 模板 / skill,Plugin 系统,MCP 集成,GUI 完整。

---

## 8. 关键反 pattern(不要做)

### 系统行为

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

### LLM 层(新增)

❌ Hardcode model 名字(`"deepseek-v4-flash"` 这种字符串字面量)
❌ Router 用 LLM 决定路由(必须代码)
❌ Agent 配置直接绑 provider(只引用 model_id)
❌ 跳过 `LLMPurpose` 字段(每次调用必须显式)
❌ Claude Code 给 operator 当 default model(不支持 orchestrator tools)
❌ 启动时不校验 fallback chain capabilities(P1 必须 fail-fast)
❌ 没有录像测试就改 CLI parser(parser 易碎,必须有录像)

### UI / UX

❌ 暴露 "agent"、"skill"、"snapshot"、"memory" 等术语
❌ 让用户配置 5 个 agent 才能开始用
❌ 在主界面显示功能菜单栏
❌ 把审批做成模态阻塞弹窗
❌ 用渐变、阴影、霓虹、emoji 装饰
❌ 一个界面用 5+ 种颜色

### 工具

❌ 给 bash 这种万能工具
❌ 工具内部维护隐藏状态
❌ 工具失败时返回伪造数据
❌ 工具一次性返回大量数据(应该截断 + 提示)

---

## 9. 测试场景(必须能跑通)

### Scenario 1: Bug 修复(单 agent)

用户报告 bug → operator 诊断计划 → 工具调用链 → 提议修复方案(ranked) → 审批 diff → 应用修改 → 跑测试 → 决策日志。

详见 chat-history.md "修 bug 走查"。

### Scenario 2: 研究(多 agent,跨多天)

用户提问 → prober 拆解 → skeptic 挑战 → operator 找数据 → divergence_mapper 地图化 → snapshot → 用户离开 → 回来追平 → reframe → 决策 → 跨房间记忆晋升。

详见 chat-history.md "做研究走查"。

### Scenario 3(新增): LLM provider fallback

用户停止 Ollama → operator 工具调用触发 → router 检测到 ollama_local 不可用 → fallback 到 deepseek_v4_flash → 工具调用成功 → 事件流记录 fallback 事件。

---

## 10. 项目结构

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
│   │   └── scoring.py
│   ├── state_machines/
│   ├── ui_strings/
│   ├── user_preferences/
│   ├── llm_providers.yaml       # NEW
│   └── llm_models.yaml          # NEW
├── src/orchestrator/
│   ├── core/                    # Event store(P0)、Room、State machine
│   ├── llm/                     # NEW — LLM 层(P1.1)
│   │   ├── types.py
│   │   ├── purposes.py
│   │   ├── protocol.py
│   │   ├── exceptions.py
│   │   ├── router.py
│   │   ├── config_loader.py
│   │   ├── health_check.py
│   │   ├── providers/
│   │   │   ├── openai_compatible.py
│   │   │   ├── claude_code_cli.py
│   │   │   └── mock.py
│   │   └── parsers/
│   │       └── claude_code_output.py
│   ├── agents/                  # Agent loader、execution(P1.4)
│   ├── tools/                   # 工具实现
│   ├── memory/                  # 跨房间记忆(P2)
│   ├── autonomy/                # 自治度系统(P1.2)
│   ├── skills/                  # Skill 加载(P1.3)
│   └── ui/                      # GUI(P3)
├── tests/
│   ├── core/
│   ├── llm/
│   │   ├── conftest.py
│   │   ├── providers/
│   │   └── recordings/          # 录像测试
│   │       └── claude_code_cli/
│   │           └── v2.1.131/
│   ├── agents/
│   ├── tools/
│   ├── scenarios/
│   └── fixtures/
└── docs/
    ├── architecture/
    │   ├── event-model.md       # P0
    │   ├── llm-layer.md         # P1.1
    │   └── autonomy.md          # P1.2
    ├── decisions/
    │   ├── ADR-001-event-store-foundation.md     # P0
    │   ├── ADR-002-llm-three-layer-config.md     # P1.1
    │   └── ADR-003-claude-code-no-orchestrator-tools.md  # P1.1
    └── contributing.md          # PR 模板("有没有 LLM 调用?为什么不用代码做?")
```

---

## 11. 技术栈(已确定)

- **Python 3.12** + **uv** + **ruff** + **pytest** + **mypy**
- **数据库**:stdlib `sqlite3`(MVP)→ Postgres(规模)
- **YAML**:Pydantic 模型加载(不是裸 dict)
- **前端**:React + TypeScript(P3)
- **图标**:Tabler Icons outline
- **LLM SDK**:
  - OpenAI Python SDK(走 openai_compatible providers)
  - subprocess(走 claude_code_cli provider)
- **状态管理**:Zustand 或 Jotai(不要 Redux)

---

## 12. 用户场景(默认配置基于此)

**主用户**(也是设计者):
- 独立开发者
- 用 Mac(Apple Silicon)
- LLM 资源:
  - Claude **Max** 订阅(Claude Code CLI)
  - DeepSeek API(v4 flash + v4 pro)
  - Local model:Ollama + oMLX

默认 agent → model 分配反映这个场景:
- 思考型 agent(prober/skeptic/divergence_mapper/logger)→ Claude Code(订阅已付,质量高)
- 动手型 agent(operator)→ DeepSeek(必须 API,支持 tools)
- 全部 agent 都有 fallback 到 local model

**其他 setup 的用户**改 `config/llm_models.yaml` 适配,**不需要改 agent 配置**。

---

## 13. 给 Claude Code 的工作建议

1. **先读 chat-history.md** — 至少读一遍
2. **从 P0 commit 2 开始**(接口冻结已 review,直接做实现)
3. **遵守反 pattern** — 第 8 节红线不要碰
4. **保持 12 条原则** — 每写模块问自己违反了哪条
5. **用代码做决策** — "让 LLM 判断 X" 的冲动先想能不能代码做
6. **小工具组合** — 不做万能工具
7. **UI 文案别硬编码** — 都进 config/ui_strings/
8. **写测试** — 自治度评分、状态机、Skill 加载、Router 这些纯函数必须有测试
9. **不确定时问用户** — 这个项目设计有大量 deliberate trade-offs
10. **每个 PR 写 ADR**(如果有重要决策)— P0 之后的所有 PR 推荐写

### LLM 调用纪律(新增)

- 每次 LLM 调用必须有 `LLMPurpose` 字段
- 添加新 purpose 必须 ADR 解释为什么不能代码做
- PR review 时必查:`grep "anthropic\|openai\|llm.complete"` 找所有 LLM 用法
- 自治度模块 grep 不能出现 LLM import(用 `test_constitution_no_llm_calls_in_autonomy_module` 强制)

### 配置纪律

- 任何 model 名字不能 hardcode 在 src/ 代码里(测试 fixtures 例外)
- 用 `test_constitution_no_hardcoded_model_names` 强制 grep
- 所有 model 引用通过 model_profile id

---

## 14. 已知未解决的问题

1. **agent 是否完全隐藏 vs 显示"模式切换"** — 当前倾向完全隐藏
2. **跨 agent 上下文一致性** — 5 个 agent 看到不同上下文,可能不一致
3. **术语审计的 false positive** — 出现频率高 ≠ 模糊
4. **Retraction 的级联效应** — 撤回早期决策可能影响多个后续决策,UI 怎么处理
5. **长时间运行的成本累积** — 4 天研究 ~$2,100 个项目 = $200
6. **录像测试的维护成本** — Claude Code 升级频繁,录像需要更新
7. **Local model 质量参差** — 用户换 7B 模型可能质量崩,需要 P2 的"模型质量警告"机制

---

## 15. ADR 索引

- ADR-001: Event store 地基(P0,待写)
- ADR-002: LLM 三层配置架构(P1.1,待写)
- ADR-003: Claude Code 不能给 operator(P1.1,待写)
- ADR-004: Tool calling 策略 3(P1.1,待写)

每次重大设计决策做新 ADR。后续的人(包括未来的 Claude Code 自己)能从 ADR 看到决策为什么这样做。

---

**最后一句话**:这个项目的核心价值不在"AI 多聪明",在"AI 让人更清楚"。如果你写的代码让 AI 替用户做决定,你就走错方向了。

LLM 层的复杂性不是"为了支持更多 backend"——是为了让用户**控制**用什么 model、不被 hardcode 锁住、不被 vendor 决定。这是产品哲学的延伸。
