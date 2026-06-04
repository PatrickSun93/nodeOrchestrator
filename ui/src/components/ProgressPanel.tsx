import { useState, useEffect } from "react";
import { getSnapshot } from "../api/client.ts";
import type { Snapshot } from "../api/client.ts";
import { toolNameLabel } from "../uiStrings.ts";
import styles from "./ProgressPanel.module.css";

interface Props {
  roomId: string;
}

/**
 * Collapsible right panel sourcing from GET /snapshot (§6.4 pattern 3).
 * 4 blocks: 讨论中 / 已建立 / 待决定 / 工具活动
 * Never exposes raw vocabulary (D-C).
 */
export function ProgressPanel({ roomId }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSnapshot(roomId)
      .then((snap) => {
        if (!cancelled) setSnapshot(snap);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [roomId]);

  if (collapsed) {
    return (
      <aside className={`${styles.panel} ${styles.collapsed}`} data-testid="progress-panel">
        <button
          className={styles.toggle}
          onClick={() => setCollapsed(false)}
          aria-label="展开进展面板"
          data-testid="panel-expand-btn"
        >
          ‹
        </button>
      </aside>
    );
  }

  return (
    <aside className={styles.panel} data-testid="progress-panel">
      <div className={styles.header}>
        <span className={styles.title}>进展</span>
        <button
          className={styles.toggle}
          onClick={() => setCollapsed(true)}
          aria-label="收起进展面板"
          data-testid="panel-collapse-btn"
        >
          ›
        </button>
      </div>

      {snapshot && (
        <div className={styles.blocks}>
          <section className={styles.block}>
            <h4 className={styles.blockTitle}>讨论中</h4>
            <p className={styles.blockValue} data-testid="event-count">
              {snapshot.event_count} 条消息
            </p>
          </section>

          <section className={styles.block}>
            <h4 className={styles.blockTitle}>已建立</h4>
            <p className={styles.blockValue} data-testid="decision-count">
              {snapshot.decision_count} 个决定
            </p>
          </section>

          {snapshot.tool_calls_pending_confirm.length > 0 && (
            <section className={styles.block}>
              <h4 className={styles.blockTitle}>待确认</h4>
              <ul className={styles.pendingList} data-testid="pending-list">
                {snapshot.tool_calls_pending_confirm.map((ref) => (
                  <li key={ref.event_id} data-testid="pending-item">
                    {toolNameLabel(ref.tool_name)}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {snapshot.participants.length > 0 && (
            <section className={styles.block}>
              <h4 className={styles.blockTitle}>参与者</h4>
              <p className={styles.blockValue} data-testid="participants">
                {snapshot.participants.length} 位助手
              </p>
            </section>
          )}
        </div>
      )}
    </aside>
  );
}
