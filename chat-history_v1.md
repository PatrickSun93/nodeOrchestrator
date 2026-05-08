# Chat History — Orchestrator 设计推理过程

> 这是 handoff.md 的**配套文档**。
> 记录设计推理过程,帮助理解每个决策"为什么"是这样。
> Claude Code 读这个文档时,**不要把对话逐字当成需求**——这是讨论过程,有的方向被推翻、有的被精炼。
> 最终结论以 handoff.md 为准,这里是上下文。

---

## 文档结构

按主题组织,**不是按时间顺序**。每个主题包含:
- 问题 / 起点
- 关键讨论
- 最终决策
- 反 pattern(讨论过但被否决的)

主题列表:

1. [项目愿景与核心理念](#1-项目愿景与核心理念)
2. [12 条设计原则的来源与应用](#2-12-条设计原则)
3. [多 agent 架构](#3-多-agent-架构)
4. [Agent 之间如何通信](#4-agent-之间如何通信)
5. [线程化日志与事件系统](#5-线程化日志与事件系统)
6. [记忆系统(分层 + 跨房间)](#6-记忆系统)
7. [自治度评分系统](#7-自治度评分系统)
8. [决策路径代码化原则](#8-决策路径代码化原则)
9. [工具集设计](#9-工具集设计)
10. [Skills / MCP / Plugins 三层](#10-skills--mcp--plugins-三层)
11. [房间模板系统](#11-房间模板系统)
12. [用户体验流](#12-用户体验流)
13. [Design System](#13-design-system)
14. [端到端场景走查](#14-端到端场景走查)
15. [反 pattern 汇总](#15-反-pattern-汇总)

---

## 1. 项目愿景与核心理念

### 起点

用户最初想做"AI agent orchestrator with GUI",目标用户是独立开发者。

### 关键讨论

**起点是"做什么样的 orchestrator"**。讨论过几种 orchestrator 类型:
- Graph/DAG-based(LangGraph、n8n)
- Hierarchical/supervisor(CrewAI)
- Code-first + 可视化层(Inngest、Temporal)
- Conversation-tree

用户选了"做研究类工作"的方向,具体场景:
- 任务型(明确目标)
- 长时间运行(几小时到几天)
- 研究类(探索性,路径不确定)
- 真正对话(碰撞产生想法)

### 最终决策

定位:**面向独立开发者的 AI 研究与决策助手**

核心承诺:**"想清楚一件事,和能挑战你想法的助手一起。"**

差异化:不是"helpful assistant",是"honest interlocutor"——会 push back、问问题、不替你做决定。

---

## 2. 12 条设计原则

### 来源

用户在某个时刻贴了一份他和另一个 LLM 讨论得到的 12 条原则文档。这份文档**重新校准**了整个设计方向。

### 12 条原则全文

#### 关于 agent 的定位

**1. Honest interlocutor > obedient executor**
Agent 设计目标不是"正确完成任务",是"让人的判断更准"。Helpful 不是最高优先级,calibrated honesty 才是。

**2. Dissent 必须显式设计进去**
LLM 默认 helpful,如果不显式 calibrate,push back 不会自然出现。每个 agent 的 persona 必须显式声明在哪些维度上是反对派。

#### 关于 output 的形状

**3. Forced ranking, never menus**
任何多选项输出必须排序并附理由。永远不是"here are 5 options, you pick"。

**4. Structured uncertainty,不要 prose hedging**
不要让 agent 用"可能"、"大概"、"也许"。要求结构化输出:置信度分数、命名的 key uncertainties、push back 的前提、需要 user 决策的具体问题。

**5. "问回去" 是 first-class output type**
"我需要 user 在 A 还是 B 之间做个判断" 是合法的完成状态,不是失败状态。

**6. Multi-perspective by default**
每个 analysis 默认是多个 analysis,有显式的 divergence points。单一视角是 degenerate case。

#### 关于 conversation 的形状

**7. Continuity of thinking**
Orchestrator 保留的应该是"思考线索"——多个 turn 之间的概念演化、争议解决、术语收敛——不只是"上一个 task 的 output"。

**8. 跨域迁移是 first-class 工具**
让 agent 能从一个 domain 借模式去另一个 domain,而不是死守自己的角色。

**9. 术语审计 / naming the trap**
很多词带着隐藏的假设——memory、self-evolution、intelligence、learning。用前要求显式定义。

#### 关于 system 的形状

**10. 环境塑造 agent,agent 不塑造自己**
改进发生在 input、工具、feedback 这些环境层。让 agent 自我修改 prompt 是陷阱。

**11. 没有 ground truth,所有 "improvement" 都是 calibration drift**
任何 evolution / 优化机制必须 anchor 在客观信号上。否则系统在向自己的偏见 drift。

**12. Stable agents in evolving environments**
Agent 应该稳定、可预测、可 reasoned-about。环境是会变的,agent 是工具不是 employee。

### 这 12 条对设计的影响

读到这份文档后,前面所有讨论都被**重新审视**:

**修正 1:发言权决策从 LLM 自评改为代码规则**
原设计让 Haiku 评估"我现在该不该说话"——违反第 11 条(无 ground truth)。改成事件触发 + 角色规则。

**修正 2:删除"综合者"角色**
违反第 6 条(multi-perspective by default,不要 average)。改成 divergence_mapper,只地图化分歧不综合。

**修正 3:摘要改名 "decision log + structured snapshots"**
"summary" 暗示无损压缩,违反第 9 条(术语审计)。改名诚实表达系统能做什么。

**修正 4:跨房间记忆要显式晋升**
LLM 自动入库违反第 11 条(drift)。改成 hypothesis pool → 显式晋升。

**修正 5:"问回去" 做成 first-class type**
原本只笼统说"人类介入",升级为结构化 escalation 事件类型。

**修正 6:每个角色显式声明 dissent 维度**
不只"做什么",还要"反对什么"、"禁止什么"。

**修正 7:加入术语审计机制**
当某词反复出现且开始承载重要含义时,触发"定义这个词"的 prompt。

### 用户的关键洞察

用户问了一句:"risk_score 这个完全可以用一个 python script 去计算或者更新 然后实现类似自动化的效果其实"。

**这一句话引出了整个项目最重要的架构原则**——决策路径代码化(见第 8 节)。

---

## 3. 多 agent 架构

### 核心决策:5 个内置角色

经过讨论,确定 5 个核心角色:

#### prober(探查者)

**职责**:问问题、拆解模糊、识别假设

**dissent dimensions**:
- 问题陈述的精确性
- 隐含假设的暴露
- 范围模糊
- 术语未定义

**cross domain borrowing**:
- 苏格拉底式提问法
- 心理学认知偏差研究
- 设计研究的"5 个为什么"

**forbidden behaviors**:
- 给方案(那是 operator 的事)
- 评判用户("这个想法不对")
- 一次问超过 3 个问题
- 重复用户已经回答过的问题

#### skeptic(质疑者)

**职责**:挑战、找漏洞、提供 dissent

**dissent dimensions**:
- 假设的合理性
- 证据的充分性(单例不够)
- 因果链的完整性(不允许跳步)
- 边界条件
- 复用旧结论时的边界
- 自我蒙蔽

**cross domain borrowing**:
- 实验心理学(认知偏差识别)
- 法律推理(证据规则、反方质疑)
- 软件工程(边界条件思维)
- 科学方法(可证伪性)

**forbidden behaviors**:
- 模糊质疑("我感觉不对")→ 必须给具体反例
- 帮腔("也对,但是...")→ 不允许 hedge
- 总结别人的观点(那是 averaging)
- 一次否定所有方向(要有具体的 reject 对象)

**特殊规则**:每个研究阶段强制至少发言 1 次(防 dissent 缺位)。

#### operator(执行者)

**职责**:调工具、找数据、做具体动作

**dissent dimensions**:
- 数据的时效性
- 数据来源的可信度
- 工具调用的成本/收益

**forbidden behaviors**:
- 编造数据(必须工具拿到或说"我不知道")
- 黑盒包装(必须显式说调什么工具)
- 跳过验证("我记得是..." → 必须 web_search 验证)

#### divergence_mapper(分歧地图)

**职责**:把分歧地图化,**不**做综合

**dissent dimensions**:
- 拒绝综合(永远不输出 average)
- 拒绝隐藏分歧

**forbidden behaviors**:
- 写"综合考虑"、"折中而言"这种 hedging
- 给最终答案
- 把多个 agent 的话压扁成"大家都说"

**输出 schema 强制**:不能有 synthesis 字段,只能有 synthesis_notes(观察,不是答案)。

#### logger(记录者)

**职责**:维护 decision log、生成 snapshot、追平摘要

**forbidden behaviors**:
- 转述化("大家讨论了...")
- 失真压缩(必须保留原话)
- 主观判断("小王同意")→ 应该 cite 具体消息

### 反 pattern(讨论过但被否决)

❌ **让用户配置 agent**:用户每次开房间都要选 5 个 agent → 没人会用

❌ **暴露 agent 名字给用户**:UI 显示 "skeptic"、"prober" → 增加心智负担

❌ **"综合者"角色**:违反第 6 条原则,被删除

❌ **角色可在运行时切换**:一个 agent 实例 = 一个固定 role,要不同视角实例化不同 agent

❌ **agent 自己决定要不要发言**:违反第 11 条原则,改为代码规则

### 用户视角

用户**完全看不到 agent 系统**。看到的是统一的"助手"(蓝色 ✨ 头像)。多视角通过**视觉差异**表达:
- 普通文本(prober 风格)
- 琥珀色 callout(skeptic 风格的挑战)
- 灰色 info card(operator 风格的数据)

---

## 4. Agent 之间如何通信

### 讨论过的方案

讨论了多种 agent 通信模式:

1. **函数调用 / 直接调用**(CrewAI 风格):简单但同步、层级僵化
2. **共享黑板**(LangGraph 风格):容易理解但失去 provenance
3. **消息邮箱**(AutoGen 风格):灵活但难调试
4. **接力交接**(Swarm 风格):线性、简单,但失去并行
5. **发布订阅**:松耦合但流程不可视化
6. **聊天室 / 频道**:用户熟悉的心智模型
7. **文档协作**:产物即协议
8. **市场竞标**:自组织
9. **契约 / 承诺**:明确边界
10. **蚁群信息素**:涌现协作
11. **追加式日志 + 分支**:类 git 历史

### 用户选择

用户喜欢"**聊天室**"模式作为基础。

### 最终设计

**聊天室 + 线程化日志 + 类型化事件**。

具体:
- Agent 在房间里"持续在场",不是轮流发言
- 通信通过事件流(append-only,有 type)
- 父消息关系形成线程树
- 可以从任何节点分叉

### 契约 vs 市场的讨论

用户问了"契约/承诺 与 市场竞标"的对比。

**结论**:
- 市场解决"谁来做"
- 契约解决"做什么、保证什么"
- 它们不对立,可以叠加
- **研究类系统不需要市场**(角色固定),契约用于子任务

最终选择:**契约作为骨架,市场作为可选层**。MVP 不做市场。


---

## 5. 线程化日志与事件系统

### 核心思想

**只能往上长、不能砍掉枝叶的对话树**。

每条事件有 `parent_id` 字段,形成树状结构。append-only,永不修改。

### 为什么这样设计

**因果关系可见**:每条消息明确指向"我是因为看到了哪条消息才说话的"。

**可分叉**:从任何节点开新分支,原分支保留。这是研究类系统的核心——可以并行尝试多个方向。

**时间回溯调试**:agent 输出怪异时,沿父链往回看。

**多 agent 并发不乱**:两个 agent 同时回复同一条消息?各自一条线程,互不干扰。

**上下文裁剪天然**:给 agent 的上下文只需"它所在的那条线程"(从根到当前),不是整个房间。

### 事件类型系统(关键决策)

最早设计是扁平 message。后来发现违反第 9 条(术语审计)——把 hypothesis、decision、observation 全叫"消息"是 sloppy。

**改成显式 type 字段**:
- utterance(普通发言)
- hypothesis(假设)
- decision(决策)
- rejection(否决)
- retraction(撤销)
- observation(观察)
- tool_call / tool_result / tool_failed
- escalation(问回去)
- summary_snapshot
- state_transition
- milestone
- term_definition
- decision_pivot(reframe)

**每种 type 有不同语义和 UI 呈现**:
- decision 自动进 decision log
- rejection 必须 cite 被否决的对象
- escalation 是 first-class 的"问回去"
- retraction 显式撤销但保留历史

### 关系提取(代码做,不是 LLM)

**结构性关系自动提取**:
- rejects → 来自 rejection 事件的 rejects 字段
- retracts → 来自 retraction 事件
- based_on → 来自 decision 事件
- replies_to → 来自 parent_id

**语义性关系候选(LLM 推断,标记为候选)**:
- supersedes
- derives_from  
- related_to

候选关系需要人类确认才"激活"。

---

## 6. 记忆系统

### 问题

用户问"分层记忆是什么?"——这是被严重低估的难题。

### 为什么记忆难

1. 上下文窗口爆炸(50 万 token 塞不进 200K 窗口)
2. "近因偏差"——agent 忘记 2 天前的关键决策
3. 成本爆炸(每次重读历史)
4. 上下文污染(早期错误方向影响判断)
5. 新加入 agent 怎么追平
6. 人类回来怎么追平

### 分层记忆架构(房间内)

#### 第 1 层:当前线程(工作记忆)

Agent 当前正在回应的那条线程(从根到最新)。**几千到几万 token**。直接从消息日志拉。

#### 第 2 层:房间摘要(短期记忆) — 后改名 "Snapshots"

定期生成的"过去 N 小时发生了什么"浓缩。**500-2000 token**。

**关键修正**(读 12 条原则后):
- 不叫 "summary",叫 **decision log + structured snapshots**
- decision log:只记录已发生的具体事件(高保真,代码维护)
- snapshots:当前状态截面(LLM 生成,显式带 confidence)

**重要**:snapshot 不递归。每次基于 decision_log 重新生成,不基于上一份 snapshot。避免 drift。

**结构字段代码生成**(event_count、duration、cost_so_far、confirmed_decisions、rejections、active_hypotheses)

**语义字段 LLM 生成**(current_focus、key_uncertainties、would_pushback_on、needs_user_decision)

#### 第 3 层:关键节点(中期记忆)

被显式标记为"重要"的消息。**几十到几百个,加起来几千 token**。

**晋升方式**(按可信度排序):
1. 人类显式标记(📌 按钮)→ confidence 1.0
2. 事件类型自动转换(decision/rejection/retraction)→ 自动晋升
3. LLM 候选 + 人类确认(进待确认队列)
4. ❌ **不允许 LLM 直接入库**

#### 第 4 层:外部知识(长期/参考记忆)

搜来的资料、引用的论文、代码片段。**向量数据库,按需检索**。

#### 第 5 层(可选):Agent 个人笔记

每个 agent 跨房间持续的"我学到了什么"私人笔记。

### 跨房间记忆系统

四类,**严格分开设计**:

#### 类别 1:领域知识(事实型)

- 跨域适用的事实和理解
- 例如:"RoPE base 调整可改善长上下文性能"
- 带证据链(source_rooms、source_msg_ids、external_refs)
- 带时效(last_validated)
- 带矛盾记录(不覆盖,append)

#### 类别 2:方法论(程序型)

- 怎么做事的模式
- 例如:"用户喜欢具体例子胜过抽象论证"
- 比领域知识更难提取,需要跨多房间观察
- 单次提取标 confidence: low,反复出现才晋升

#### 类别 3:实体(关系型)

- 关于具体"东西"的稳定信息
- 用户偏好、项目信息、读过的 paper
- 知识图谱式结构(实体 + 关系)
- 强烈跨房间通用

#### 类别 4:项目档案(叙事型)

- 每个房间的"身份证"
- room_id、title、duration、one_line_summary、decision_log、spinoff_questions
- 主要服务人类浏览

### 关键设计:晋升必须显式

**严重的修正**(读 12 条原则后):

**之前的设计**:LLM 自动从房间提取知识入库。
**问题**:违反第 11 条(drift)。错误知识被永久化、复用、复制。

**修正后**:
- 房间结束时只生成"候选 hypothesis 池"
- Hypothesis pool **不参与跨房间检索**
- 显式晋升流程:满足以下之一才晋升
  - 跨 N 个独立房间被独立得出
  - 用户显式确认
  - 外部 ground truth 验证(实验、引用)

### 修正后的整体架构

```
Hypothesis Pool(房间产物,未验证)
    ↓ 显式晋升
已验证知识库(参与跨房间检索)
    ↓ 降级路径
历史归档(被反驳的、超期的)
```

### 关键设计原则

1. **写入要刻意**:房间结束时明确问"加入知识库?"
2. **读取要透明**:新房间加载跨房间记忆时显式告诉用户
3. **作用域**:personal / team / project / global
4. **遗忘机制**:超期降级,不是删除
5. **可解释性链条**:每条记忆能追溯证据

### 用户偏好的特殊处理

**禁止 LLM 推断的偏好**(违反第 11 条):
- ❌ "agent 觉得用户喜欢具体例子"

**允许的偏好获取方式**:
- ✅ 用户显式声明
- ✅ 行为模式作为 metadata(不是偏好)
- 系统可以提议"是否要把这个习惯设为偏好",用户决定

### 渐进实施

不要一开始就做完整跨房间系统。建议:

**MVP**:实体记忆(用户偏好、项目基本信息)
**第二步**:领域知识库(房间结束时提取候选)
**第三步**:方法论提取
**第四步**:遗忘机制、可解释性、团队层

但**所有数据结构从第一天就预留 scope、evidence、entity_id 等扩展字段**。


---

## 7. 自治度评分系统

### 用户的核心想法

用户提出:**"score 或者 rule 去让什么可以自动执行 需要审批 需要拒绝等等 现在保守一点对我来说其实还行"**。

这是个产品级的好想法——不是所有事情都"全自动"或"全人工",按风险/重要性分级。

### 四级自治度

```
Level 0: 禁止  → 系统拒绝执行
Level 1: 需审批 → 待用户同意才执行
Level 2: 通知后执行 → 倒计时窗口可中断
Level 3: 自动执行 → 立即执行,事后报告
```

**为什么是 4 级而不是 3 级**:Level 2(可中断)是关键——给用户心理安全感但不增加大部分情况的负担。

### 决策方式:规则 + 评分

**规则是硬约束**:
- 黑名单(永远 Level 0)
- 白名单(永远 Level 3)
- 上下文规则(生产环境、用户离线、最近失败)
- 用户自定义规则

**评分是软判断**(规则未触发时):

6 个维度,每个 0-10:
1. **reversibility**:错了能撤销吗?(删数据库=0,搜索=10)
2. **blast_radius**:错了影响多大?(影响生产=0,影响这次对话=10)
3. **data_sensitivity**:涉及数据的敏感度
4. **cost_impact**:错了花多少钱
5. **decision_finality**:决策的持续影响
6. **user_intent**:是用户明确要的还是 agent 主动?

加权求和,映射到级别。

### 用户的关键洞察

用户:**"risk_score 这个完全可以用一个 python script 去计算或者更新 然后实现类似自动化的效果"**

这一句话引出了整个项目的核心设计原则——**决策路径代码化**(见第 8 节)。

把 risk_score 用纯 Python 函数实现,意味着:
- 0 LLM 调用
- 完全确定性
- 可单元测试
- 可审计(每个决策有 trace)
- 可演化(代码 review 流程)

### 评分函数的实现思路

每个维度独立函数,**这样可以单独测试、修改**:

```python
def score_reversibility(op: Operation) -> int:
    if op.op_type in {"send_email_external", "delete_data_permanently"}:
        return 0
    if op.op_type in {"modify_file", "commit_to_git"}:
        return 4
    if op.op_type in {"create_draft", "log_to_room"}:
        return 8
    if op.op_type in {"read_file", "search_web"}:
        return 10
    return 3  # 未知默认保守
```

(其他维度类似)

### 决策函数

```python
def determine_autonomy_level(
    op: Operation,
    context: Context,
    custom_rules: list = None,
) -> tuple[AutonomyLevel, dict]:
    """
    优先级:
    1. 硬规则(黑白名单)
    2. 上下文规则(生产环境等)
    3. 用户自定义规则
    4. 评分映射
    """
```

返回级别 + decision_trace(完全可解释)。

### 默认偏保守

新用户的默认配置应该**偏保守**:
- 60% 操作 Level 1
- 30% Level 2
- 10% Level 3

理由:错过自动化的成本(用户多点几次)< 错误自动化的成本(数据丢失、信任破坏)。

随用户使用,系统**提议**调整(不自动调):"你已经批准了 X 类操作 50 次,是否降级?"

### 紧急停止

UI 顶部要有**红色总开关**:
- 一键暂停所有 agent 活动
- 进行中的 Level 2 立刻取消
- 所有 agent 进入"等待"
- 待审批队列保留

这是信任的最后保障。

---

## 8. 决策路径代码化原则

### 起源

用户提出 risk_score 用 Python 实现后,我意识到这是个**通用模式**,不只 risk_score。

### 核心原则

> **决策路径优先用代码,模型只用于内容生成。**
> 
> "什么时候做"、"是否允许"、"召唤谁"、"切到什么状态"、"喂什么上下文"——**决策路径**,代码做。
> 
> "写什么"、"怎么思考"、"如何回应"——**内容生成**,LLM 做。

### 这条原则是 12 条原则的工程化推论

- 第 10 条(环境塑造 agent)→ 决策路径属于环境
- 第 11 条(无 ground truth → drift)→ 代码决策有 ground truth
- 第 12 条(stable agent)→ 代码决策让行为可预测
- 第 4 条(structured uncertainty)→ 代码决策天然结构化

### 全景边界

#### 100% 代码层(决策路径)

- 自治度评分(risk_score)
- 操作放行规则
- 状态机切换
- Agent 发言权决策(should_agent_speak)
- 召唤决策(哪些 agent 被激活)
- Snapshot 触发时机
- 关键节点提升(从事件 type 自动)
- 关系提取(结构性关系)
- 上下文窗口构建
- 决策日志维护
- 跨房间记忆调取
- 晋升资格判定
- 角色绑定与约束验证
- 用户偏好管理
- 权重调整建议
- 事件流的 append-only 写入

#### 半代码半 LLM(结构生成)

- Agent 输出(schema 强制 + 内容由 LLM 生成)
- Snapshot(结构字段代码 + 语义字段 LLM)
- Hypothesis 提取(LLM 提议 + 代码 schema 检查)
- 关键节点候选(LLM 候选 + 代码晋升)

#### 100% LLM 层(内容生成)

- Agent 发言内容
- Hypothesis 内容
- 批判和反驳的具体内容
- 跨域类比和洞察
- 自然语言摘要的语义部分
- 用户自然语言查询的理解

### 这个分层的好处

1. **系统可以"无 LLM 运行"** — 代码层完全不依赖 LLM 也能跑,LLM API 失败时不全崩
2. **成本和延迟降低** — 大量决策被代码替代,LLM 调用次数降低 60-80%
3. **调试可能性** — 代码可断点、可日志、可单元测试
4. **信任感** — 用户能 review 代码层的所有逻辑

### 设计哲学(可以写进系统的"宪法")

> 好的 LLM 系统不是"让 LLM 做更多",而是"让 LLM 做更少 + 让代码做更多"。
> 
> LLM 是昂贵的、不稳定的、不可审计的资源。每次调用都是一次承担风险的决定。
> 
> 工程艺术:识别哪些决策真的需要 LLM 的"理解",哪些是被 LLM 名声唬住的"伪 AI 任务"。
> 
> 大部分"看起来需要 AI"的决策其实只需要好的数据结构和清晰的规则。
> 
> 真正需要 LLM 的:生成自然语言内容、做语义理解、做跨域类比。


---

## 9. 工具集设计

### 用户的关键决策

用户:**"复合工具 其实我不想做 我想要把任务分散成小小的 非常具体的任务 不是一个宽泛的任务"**

这个决策**完全正确**,而且符合所有架构原则。

### 为什么"小而具体"是对的

**理由 1:可观察** — 复合工具内部黑盒;小工具组合每一步都是事件流里一条事件,可审计、可回放、可分叉。

**理由 2:可干预** — 复合工具中途几乎不能介入;小工具每步之间都能介入。

**理由 3:可组合** — 修 bug、理解代码、代码审查用不同工具序列,但底层小工具复用。

**理由 4:可推理** — Agent 在每步思考"下一步用什么",这种推理对人可见。可推理 = 可调试。

**理由 5:契合事件类型系统** — 一次小工具调用 = 一个 tool_call + 一个 tool_result(1:1),事件类型系统的好处全部保留。

### 设计哲学

> Agent 的智能体现在"如何组合工具完成任务",不是"调一个万能工具"。
> 
> 万能工具让 agent 不用思考——只是 dispatcher。
> 基础工具让 agent 必须规划、推理、迭代——才是真思考。

### 决策

**第三层(复合工具)从设计里删掉**。

需要"复杂工作流"时:Agent 用小工具组合 + 用户审批整个计划。展示层的复合,不是工具层的复合。

### 工具的设计原则

1. **粒度足够小,但不更小**(Unix 哲学)
2. **无状态,或状态显式**(不要藏内部缓存)
3. **输出自描述**(数据 + schema + 元信息 + 截断标志)
4. **诚实地失败**(不返回伪造数据,错误明确分类)
5. **避免"行动 + 查询"混合**(查询和行动分开)

### 错误分类(关键)

```python
class ToolError(Enum):
    TRANSIENT = "transient"        # 重试可能成功
    PERMANENT = "permanent"        # 重试无意义
    NEEDS_HUMAN = "needs_human"    # 需要人介入
    CRITICAL = "critical"          # 严重,停止流程
```

每类不同处理策略。**决定怎么处理错误是代码层的**,Agent 不应该自己"我要重试 3 次"——那是策略,是环境层。

### 工具发现的分层

不要把 50 个工具的 schema 全塞 system prompt:

```
启动时(system prompt):
  - 工具的"分类目录"(简要)
  - 第一层基础工具的简要 schema

用到时(动态加载):
  - Agent 想用某类工具时,加载该类工具详细 schema
```

### 工具按房间类型配置

不同房间不同工具集:

```yaml
research_room:
  basic: [read_file, search_text, web_search, web_fetch]
  domain: [search_papers, read_paper]
  forbidden: [edit_file, deploy, send_email]

bug_fix_room:
  basic: [read_file, search_text, search_code]
  domain: [find_references, propose_edit, apply_edit, run_tests]
  forbidden: [bash, send_email, deploy]
```

### 安全设计

**bash 工具默认不提供**(万能就万险)。
- 如果要,用受限版本 `run_safe_command(command, allowed_binaries, workspace)`
- 或者干脆不给 bash,只给具体 `run_tests`、`git_blame` 这些**意图明确**的工具

**沙盒边界是工具的属性**(不是 agent 的责任):

```python
def read_file(path, workspace):
    if not workspace.contains(path):
        return Err(SecurityError(...))
```

---

## 10. Skills / MCP / Plugins 三层

### 起点

用户说:**"MCP 协议其实已经有点过时了 现在更多的是 skill plugin 我们怎么兼容"**

### 校准(用户判断不完全准确)

通过 web search 校准事实(2026 年):

- **MCP 没过时**,但热度回落,进入"成熟基础设施"阶段
- **Skills 是新趋势**(Anthropic 2025 年 12 月发布规范,OpenAI/Google 跟进),采纳速度极快
- **Plugins 是分发单元**,打包多种东西

三者关系:
> MCP 处理系统集成,Skills 定义行为和执行逻辑,Plugins 打包分发。
> 不是替代关系,是分工协作。

### 三层在系统里的角色

#### Skills = "Agent 的心智剧本"

- Skills 是 task-level playbook(具体任务的步骤模板)
- 补充 role,不替代 role
- 文件格式(SKILL.md),进 git,人类策展
- **不允许 agent 自我修改**(违反第 10 条)

#### MCP = "外部世界的连接"

- 包装外部 API/数据源(GitHub、Slack、Postgres)
- 作为**插件不是核心**
- 每个 MCP 工具包装成本地 Tool 对象
- **所有 MCP 调用走自治度系统**

#### Plugins = "扩展的分发单元"

- 打包:skills + tools + MCP 配置 + roles
- 用户可安装/卸载
- 团队可分享

### Skills 的具体集成

```yaml
# SKILL.md 标准格式(兼容 Claude Code、Codex CLI 等)
---
name: debugging-workflow
description: Use when investigating a reported bug
triggers: ["bug", "error", "AttributeError"]
applies_to_roles: [operator, skeptic]
applies_to_room_types: [bug_fix]
priority: 8
---

# Debugging Workflow

## When to use this
...

## The workflow
### Step 1: Reproduce the bug
...

## Don't do
...
```

### Skill 加载逻辑(代码做)

```python
def select_skills_for_context(agent, current_event, room, available_skills):
    """决定加载哪些 skills。代码决定,不是 LLM。"""
    selected = []
    for skill in available_skills:
        if skill.applies_to_roles and agent.role not in skill.applies_to_roles:
            continue
        if not any(matches(t, current_event.content) for t in skill.triggers):
            continue
        if skill.room_types and room.type not in skill.room_types:
            continue
        selected.append(skill)
    return rank_by_relevance(selected, current_event)[:3]  # 限 3 个
```

### MCP 集成的关键设计

**每个 MCP 工具包装成本地 Tool**:

```python
class MCPToolAdapter(Tool):
    def __init__(self, mcp_client, mcp_tool_def):
        self.name = f"mcp_{server_name}_{tool_def.name}"
        # 你的系统赋予的元数据(MCP 不知道这些)
        self.danger_level = self._infer_danger_level(mcp_tool_def)
        self.default_autonomy_level = self._infer_autonomy(mcp_tool_def)
    
    async def call(self, **kwargs):
        # 调用前过自治度系统
        gate_result = gate_operation(op, current_context)
        if gate_result.level == AutonomyLevel.FORBIDDEN:
            return ToolResult.forbidden(gate_result)
        if gate_result.level == AutonomyLevel.APPROVAL_REQUIRED:
            approval = await wait_for_user_approval(op)
            if not approval:
                return ToolResult.rejected_by_user()
        # 真正调用
        return await self.mcp_client.call_tool(...)
```

**重要**:即使 Anthropic API 原生支持 MCP,**也要自己实现 MCP client**——否则绕过自治度系统,违背核心价值。

---

## 11. 房间模板系统

### 5 个核心模板

#### free_chat(自由对话)
- agents: prober, operator
- 工具: 基础工具
- 状态机: open(单状态)
- 自治度: 偏自动

#### bug_fix(修 bug)
- agents: operator(单 agent)
- 工具: 代码导航 + 编辑
- 状态机: DIAGNOSING → FIXING → VERIFYING → COMPLETED
- 自治度: edit 类要审批

#### research(研究)
- agents: 全部 5 个
- 工具: 搜索 + 论文阅读
- 状态机: DIVERGING → CONVERGING → DEEP_DIVING → STUCK → MILESTONE
- 自治度: web_search 自动

#### code_review(代码评审)
- agents: operator + skeptic + architect(可选)
- 工具: **完全只读**(没有 edit_file)
- 状态机: SCANNING → ANALYZING → REPORTING → COMPLETED

#### idea_validation(想法验证)
- agents: 全部 5 个 + market_analyst(可选)
- 工具: web_search + 商业数据
- 状态机: DIVERGING → REALITY_CHECK → CONVERGING → MILESTONE
- skeptic 敏感度调高(创业想法最易自我蒙蔽)

### 不要做太多模板

5-6 个覆盖 80% 场景就够。**模板越多用户越困惑**。

特殊需求:从"自由对话"开始 + 后续手动加载 agent/skill。

---

## 12. 用户体验流

### 核心原则

**Agent 隐形,价值可感**。用户看不到 agent/skill/autonomy 这些词,但感受到多视角、被挑战、有连续性。

### 95-4-1-0.1 的复杂度分层

- **L1 主界面(95% 用户)**:打字 → 对话 → 决策 → 关闭
- **L2 设置(4%)**:基本偏好、风格、自动化默认
- **L3 高级(1%)**:实验性功能、行为微调
- **L4 配置(0.1% 开发者)**:YAML、Plugin、API

如果 UI 强迫每个用户进 L4,只剩开发者用户。

### 用户体验关键时刻

#### 第一次打开:onboarding(3 屏可跳过)

第 1 屏:只问名字
第 2 屏:你做什么的(4 选项)
第 3 屏:**预期管理**——"我会挑战你不会一上来给答案,如果你想要快速答案可能会觉得我烦"

**这是反 marketing 的诚实**。

#### 主界面:极简

- 大输入框(主交互)
- 4 个场景按钮(辅助)
- 顶部只有 ⚙ 设置和 ◀ 返回
- 没有功能菜单栏

#### 对话中:多视角通过视觉表达

- 用户头像:浅灰"你"圆圈
- AI 头像:蓝色 ✨ 圆圈(**唯一一处用蓝色**)
- 普通文本:prober 风格(问问题、拆模糊)
- 琥珀色 callout:挑战 / 隐含假设
- 灰色 info card:数据 / 事实

#### 进展面板:右侧 280px

- 默认折叠(细窄条,可感知存在)
- 展开后 4 块:讨论中、已建立、待决定、我会 push back
- **不用 "snapshot" 这个词,用"进展"**

#### 关键时刻:明显但不打断

- **审批弹窗**:inline 在对话里,不模态阻塞,3 选项(同意/改/不要)
- **决策确认**:左右两栏(基于什么 vs trade-off)+ ✓ 标记
- **工具调用**:🔍 极简列表,✓ 完成感

#### 跨房间记忆晋升:友好包装

- **不用"memory"、"knowledge base"** → 用"经验"、"留给未来的我"
- 每条解释适用场景
- 可逐条选择保留/修改/跳过

#### 第二次使用:体现复利

- "上次我们讨论 X 时,你倾向 Y,我后来挑战了..."
- 不假装"忘记",显式说"你倾向..."
- 提供快捷路径:"如果还是这样,我们可以快进"

### 文案规范

**永远不出现**的术语:
- agent → "助手"
- snapshot → "进展"
- memory → "经验" / "学到的"
- skill → 不暴露
- autonomy level → "工具调用"
- dissent dimension → "挑战"
- divergence map → "分歧"
- state machine → 不暴露


---

## 13. Design System

### 设计哲学(5 条)

1. **隐形优先于明显** — 用户感受到价值但看不到架构
2. **克制优先于丰富** — 更少的颜色、字号、组件
3. **人话优先于术语** — "进展"不是 snapshot
4. **关键时刻优先于流畅** — 决策、审批、撤回必须明显
5. **视觉差异 ≠ 视觉噪音** — 多视角通过细微差异表达

### 色彩系统

**5 种语义色 + 中性色**。同界面 ≤ 3 种语义色。

| 用途 | 浅色(背景) | 深色(文本/边框) |
|------|-------------|------------------|
| AI 身份 | `#E6F1FB` | `#185FA5` |
| 已确认/完成 | `#E1F5EE` | `#0F6E56` |
| 挑战/留意 | `#FAEEDA` | `#BA7517` |
| 拒绝/错误 | `#FCEBEB` | `#A32D2D` |
| 关键节点(稀有) | `#EEEDFE` | `#534AB7` |

**红线**:
- 同界面色彩 ≤ 3 种(不算中性色)
- 色彩必须承载语义,不做装饰
- 不用 600+ 字重
- 不用渐变、阴影、霓虹

### 字号

只用 6 档:22 / 16 / 14 / 13 / 12 / 11px
字重只用:400 / 500

| 档 | 字号 / 字重 | 用途 |
|----|------------|------|
| heading-1 | 22 / 500 | 页面标题 |
| heading-3 | 16 / 500 | 区块标题 |
| body | 14 / 400 | 主对话内容 |
| body-sm | 13 / 400 | 辅助说明、卡片 |
| caption | 12 / 400 | 元信息、时间戳 |
| label | 11 / 500 | 区块标签(uppercase) |

### 间距

只用 5 档:4 / 8 / 12 / 16 / 24px

### 圆角

3 档:8px(按钮、输入)、12px(卡片、面板)、50%(头像、图标按钮)

### 核心组件

#### 消息气泡(4 种)

1. **user-message**:无背景框,左侧浅灰头像
2. **ai-message**:蓝色 ✨ 头像,内容有细分元素
3. **challenge-callout**:嵌入 ai-message,琥珀色,左边框 2px
4. **info-card**:嵌入 ai-message,灰色背景

#### 按钮(3 种)

- 主操作:深色背景 + 白字
- 次操作:透明背景 + 边框
- 弱操作:无边框,灰色文字

#### 状态标识(5 种)

✓ 已确认 / ⚠️ 待审批 / ✗ 已否决 / 📌 关键节点 / 🕐 进行中

#### 工具调用条

极简:🔍 + 简短描述 + ✓(完成)/...(进行中)

### 5 个核心 Pattern

**P1 - AI 多视角**

同一个 ✨ 头像 + 嵌入元素(challenge-callout、info-card)表达不同视角。**不分裂成多个头像**。

**P2 - 决策三段式**

排序 → trade-off → 确认。三步缺一不可。

**P3 - 进展面板**

右侧 280px 可折叠。4 块:讨论中、已建立、待决定、我会 push。

**P4 - 复杂度分层**

L1 主界面(95%)→ L2 设置(4%)→ L3 高级(1%)→ L4 配置(0.1%)

**P5 - 离开/回来对称**

离开生成简短摘要,回来时显式追平。研究类房间核心。

### 实施建议

如果做新界面:
1. 看 patterns 找匹配
2. 选 components
3. 用 tokens
4. 验证哲学(隐形?克制?关键时刻明显?)

任何一步出问题,倒退检查更上层。

---

## 14. 端到端场景走查

### Bug 修复场景(单 agent,~35 分钟)

完整流程见 chat-history 中的详细走查。关键点:

- 单 agent (operator) 模式
- 工具密集(read、search、find_references、git_blame、propose_edit、apply_edit、run_tests)
- 自治度系统:大部分 Lvl 3(读),propose_edit 是 Lvl 1(审批 diff)
- 11 次 LLM 调用,18 次工具调用
- 决策日志:1 个修复方案
- 跨房间记忆晋升:1 条

**关键学习**:
- LLM 只在"决定下一步"和"解读结果"工作,大量决策代码做
- 测试失败时 agent 重新调查→自我修正(LLM 的真正工作)
- 自治度系统恰好平衡(只在改文件时拦下,不每次工具调用都问)

### 研究场景(多 agent,跨 4 天)

完整流程见 chat-history 中的详细走查。关键点:

- 5 个 agent 真正协作(各司其职)
- 4 天累积 ~247 个事件,89 次 LLM 调用
- 状态机:DIVERGING → CONVERGING → DEEP_DIVING(还有 STUCK)
- 决策日志:5 个决策、8 个否决
- Decision_pivot(reframe)发生:从 "API vs self-host" 到 "多模型混合"
- Retraction 发生(Day 3 撤回供应商决策)
- 用户离开/回来 2 次,每次有追平摘要
- 跨房间记忆晋升:3 条洞察

**关键学习**:
- 多 agent 不是流水线,是真正的协作思考
- skeptic 主动挑战避免在错误问题上深入
- divergence_mapper 不综合是关键设计
- Logger 维护的 decision log 是用户回来的"灯塔"
- 跨房间记忆复利效应在第二次研究时显现

**研究 vs Bug fix 对比**:

| 维度 | Bug Fix | 研究 |
|------|---------|------|
| 持续 | 35 分钟 | 4 天 |
| 事件 | ~40 | ~247 |
| LLM 调用 | 11 | 89 |
| Agent 数 | 1 | 5 |
| 决策 | 1 | 5 |
| 否决 | 1 | 8 |

研究是 bug fix 的 3-6 倍复杂度。架构在两种场景都能跑,证明通用性。

### 核心区别

> Bug fix 系统帮你解决问题。研究系统帮你**想清楚问题本身是不是对的**。
> 
> 这是质的区别——很多产品决策的失败不是"答案错了",是"问题问错了"。
> 
> 多 agent 系统(skeptic + divergence_mapper + reframe 机制)就是为了让用户**避免在错误问题上深入**。

---

## 15. 反 pattern 汇总

### 系统行为

❌ 让 agent 自评要不要发言(用规则)
❌ 让 LLM 评估自己输出的质量(无 ground truth)
❌ 让 agent 自动修改 prompt / persona(违反第 10 条)
❌ 自动把 LLM 提取内容入跨房间记忆(必须显式晋升)
❌ 用 LLM 做意图分类、状态切换判断(用代码)
❌ 让用户每次都做"加载哪些 agent"(系统内置)
❌ 复合工具(让 agent 用小工具组合)
❌ 自由文本摘要(用 decision log + structured snapshots)
❌ 让用户读 247 条消息追平(用追平摘要)
❌ Snapshot 递归(基于上一份生成)→ drift

### UI / UX

❌ 暴露 "agent"、"skill"、"snapshot"、"memory" 等术语
❌ 让用户配置 5 个 agent 才能开始用
❌ 在主界面显示功能菜单栏
❌ 把审批做成模态阻塞弹窗
❌ 用渐变、阴影、霓虹、emoji 装饰
❌ 一个界面用 5+ 种颜色
❌ 字号 < 11px 或字重 600+
❌ 自动隐藏内容用 tabs / 折叠

### 工具

❌ 给 bash 这种万能工具
❌ 工具内部维护隐藏状态
❌ 工具失败时返回伪造数据
❌ 工具一次性返回大量数据(应该截断 + 提示)
❌ 让 agent 自己造工具
❌ 让 agent 修改工具的危险等级

### 通用

❌ "Agent 自己学会做得更好"(改进环境,不是 agent)
❌ 把 helpful 当最高优先级(应该是 calibrated honesty)
❌ "综合考虑"、"两边都有道理"这种 hedge
❌ Agent 互相吹捧 / 帮腔
❌ 一上来就给答案不问问题

---

## 一些用户原话(用作背景)

用户在不同时间说过的关键原话,帮助 Claude Code 理解语境:

> "我想要一些新的 也想要好管理"

> "聊天室 我喜欢这种"

> "在chinese explain pls"(用户主要用中文,但接受英文)

> "记忆其实很麻烦"(对记忆系统的真实态度)

> "如果我有一个project 已经有近10M行代码 我说有bug在某文件 需要修复 这种情况 怎么运行"(关心实际工程场景)

> "首先我们可以有一个score 或者something like rule 去让什么可以自动执行 需要审批 需要拒绝等等 现在保守一点对我来说其实还行"(自治度的来源)

> "risk_score 这个完全可以用一个python script 去计算或者更新 然后实现类似自动化的效果其实"(决策路径代码化的来源)

> "复合工具 其实我不想做 我想要把任务分散成小小的 非常具体的任务 不是一个宽泛的任务"(工具集设计)

> "MCP协议其实已经有点过时了 现在更多的是skill plugin 我们怎么兼容"(三层架构的来源)

---

## 给 Claude Code 的最后建议

1. **先读 handoff.md**,这是结构化的需求文档
2. **再读这个文档**,理解每个决策为什么是这样
3. **遇到不确定时,优先问用户**,不要假设
4. **代码做决策路径,LLM 做内容生成**——这是最重要的
5. **小工具组合,不要复合工具**
6. **用户文案不要硬编码**,都进 config/ui_strings/
7. **从 P0 开始**,不要一上来做完整产品
8. **每写一个模块,问自己违反 12 条原则的哪条**

---

**最后**:这个项目的核心价值不是"AI 多聪明",是"AI 让人想得更清楚"。如果代码让 AI 替用户做决定,就走错方向了。
