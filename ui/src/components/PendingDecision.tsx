import { useRoomStore } from "../store.ts";
import { useConfirm } from "../hooks/useConfirm.ts";
import { toolNameLabel } from "../uiStrings.ts";
import styles from "./PendingDecision.module.css";

/**
 * Displays each pending gated tool call and offers 确认/取消 affordances.
 * The autonomy_tier drives the affordance only — never shown as text (D-C 不暴露).
 * Sends only {pending_event_id, decision} to /confirm — no-forge (ADR-030 D6).
 */
export function PendingDecisionList() {
  const roomId = useRoomStore((s) => s.roomId);
  const pendingCalls = useRoomStore((s) => s.pendingCalls);
  const { confirm, status } = useConfirm();

  if (!roomId || pendingCalls.size === 0) return null;

  const pending = Array.from(pendingCalls.values());

  return (
    <div className={styles.list} data-testid="pending-decision-list">
      {pending.map((p) => {
        // tier drives affordance only — never rendered as text (D-C)
        const isCountdown = p.autonomy_tier === "countdown_confirm";

        return (
          <div
            key={p.event_id}
            className={`${styles.card} ${isCountdown ? styles.countdown : styles.hard}`}
            data-testid="pending-decision-card"
          >
            <p className={styles.description}>
              助手想要调用
              <strong data-testid="pending-tool-name"> {toolNameLabel(p.tool_name)}</strong>
              ，等待你确认
            </p>
            <div className={styles.actions}>
              <button
                className={`${styles.btn} ${isCountdown ? styles.primary : styles.primaryHard}`}
                data-testid="confirm-approve-btn"
                disabled={status === "sending"}
                onClick={() => confirm(roomId, p.event_id, "approve")}
              >
                确认
              </button>
              <button
                className={`${styles.btn} ${styles.secondary}`}
                data-testid="confirm-cancel-btn"
                disabled={status === "sending"}
                onClick={() => confirm(roomId, p.event_id, "cancel")}
              >
                取消
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
