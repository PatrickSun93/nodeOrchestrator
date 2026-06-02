import type { EventType, RoomType } from "./api/client.ts";

// GUI-owned humanization layer (ADR-026 D3, HR#3).
// Maps raw wire vocabulary → Chinese human terms. Never returns the raw key.
// Unknown values fall back to a safe generic — never the raw string.
// Internal-only vocabulary (skill / state machine / autonomy / dissent) is 不暴露.

// Event type labels — exhaustive over the 19 constitutional EventType values.
const EVENT_TYPE_LABELS: Record<EventType, string> = {
  user_input: "用户消息",
  utterance: "发言",
  hypothesis: "假设",
  decision: "决定",
  rejection: "拒绝",
  retraction: "撤回",
  observation: "观察",
  tool_call: "工具调用",
  tool_result: "工具结果",
  tool_failed: "工具失败",
  escalation: "升级",
  summary_snapshot: "摘要",
  state_transition: "状态更新",
  milestone: "里程碑",
  term_definition: "术语定义",
  decision_pivot: "决策转向",
  autonomy_decision: "自主决策",
  autonomy_refusal: "拒绝执行",
  external_validation: "外部验证",
};

// Agent id → display name. Keys on the product agents from config/agents/.
// Unknown agents fall back to "助手".
const AGENT_NAME_MAP: Record<string, string> = {
  prober: "探查者",
  skeptic: "质疑者",
  operator: "执行者",
  divergence_mapper: "分歧梳理者",
  logger: "记录者",
  facilitator: "引导者",
};

// Room type labels
const ROOM_TYPE_LABELS: Record<RoomType, string> = {
  free_chat: "闲聊",
  bug_fix: "修复问题",
  research: "研究",
  code_review: "代码评审",
  idea_validation: "想法验证",
};

// Room state labels — covers all states from the Python state machine.
// Maps raw state strings to human-readable progress descriptions.
const ROOM_STATE_LABELS: Record<string, string> = {
  open: "进行中",
  setup: "准备中",
  active: "进行中",
  // free_chat
  // bug_fix
  reproduced: "已复现",
  diagnosed: "已诊断",
  fix_proposed: "方案已提出",
  // research
  exploration: "探索中",
  divergence: "发散中",
  convergence: "收敛中",
  snapshot_pending: "整理中",
  // code_review
  reviewing: "评审中",
  changes_requested: "需要修改",
  approved: "已通过",
  // idea_validation
  pitching: "呈现想法",
  validating: "验证中",
  decided: "已决策",
  // common terminal
  closed: "已结束",
};

export function eventTypeLabel(type: EventType): string {
  return EVENT_TYPE_LABELS[type] ?? "消息";
}

export function authorLabel(author: string): string {
  if (author === "user") return "你";
  if (author === "system") return "系统";
  if (author.startsWith("agent:")) {
    const agentId = author.slice("agent:".length);
    return AGENT_NAME_MAP[agentId] ?? "助手";
  }
  // Unknown author — do not surface raw string
  return "助手";
}

export function roomTypeLabel(type: RoomType): string {
  return ROOM_TYPE_LABELS[type] ?? "房间";
}

export function roomStateLabel(state: string): string {
  return ROOM_STATE_LABELS[state] ?? "进行中";
}
