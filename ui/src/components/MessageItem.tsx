import type { Event, EventType } from "../api/client.ts";
import { authorLabel, eventTypeLabel, toolNameLabel } from "../uiStrings.ts";
import styles from "./MessageItem.module.css";

interface Props {
  event: Event;
}

// Event types that display a humanized tool name as part of their affordance.
const TOOL_ACTIVITY_TYPES = new Set<EventType>([
  "tool_call",
  "tool_result",
  "tool_failed",
  "tool_call_pending",
  "tool_call_cancelled",
]);

// Event types that are decision-class affordances.
const DECISION_CLASS_TYPES = new Set<EventType>([
  "decision",
  "rejection",
  "retraction",
  "decision_pivot",
]);

// Event types that are read-only system affordances.
const SYSTEM_AFFORDANCE_TYPES = new Set<EventType>([
  "escalation",
  "summary_snapshot",
  "state_transition",
  "milestone",
  "term_definition",
  "autonomy_decision",
  "autonomy_refusal",
  "external_validation",
  "hypothesis",
  "observation",
]);

function toolActivityDescription(event: Event): string {
  const meta = (event.metadata ?? {}) as { tool_name?: string };
  const name = meta.tool_name ? toolNameLabel(meta.tool_name) : "一个工具";
  if (event.type === "tool_call") return `调用: ${name}`;
  if (event.type === "tool_result") return `结果: ${name}`;
  if (event.type === "tool_failed") return `失败: ${name}`;
  if (event.type === "tool_call_pending") return `等待确认: ${name}`;
  if (event.type === "tool_call_cancelled") return `已取消: ${name}`;
  return name;
}

export function MessageItem({ event }: Props) {
  const author = authorLabel(event.author);
  const typeChip = eventTypeLabel(event.type);
  const isUser = event.author === "user";
  const isToolActivity = TOOL_ACTIVITY_TYPES.has(event.type);
  const isDecision = DECISION_CLASS_TYPES.has(event.type);
  const isSystem = SYSTEM_AFFORDANCE_TYPES.has(event.type);

  let itemClass = styles.item;
  if (isUser) itemClass += ` ${styles.user}`;
  else if (isDecision) itemClass += ` ${styles.decision}`;
  else if (isSystem) itemClass += ` ${styles.system}`;
  else if (isToolActivity) itemClass += ` ${styles.toolActivity}`;
  else itemClass += ` ${styles.agent}`;

  return (
    <div className={itemClass} data-testid="message-item" data-event-type={event.type}>
      <div className={styles.header}>
        {!isSystem && <span className={styles.author}>{author}</span>}
        <span className={styles.chip}>{typeChip}</span>
      </div>
      {isToolActivity ? (
        <div className={styles.toolDesc} data-testid="tool-activity-desc">
          {toolActivityDescription(event)}
        </div>
      ) : (
        <div className={styles.content}>{event.content}</div>
      )}
    </div>
  );
}
