import type { Phase } from "../store.ts";
import styles from "./ConnectionStatus.module.css";

interface Props {
  phase: Phase;
}

const PHASE_LABEL: Record<Phase, string> = {
  idle: "空闲",
  loading: "加载中…",
  live: "实时",
  reconnecting: "重连中…",
  error: "错误",
};

export function ConnectionStatus({ phase }: Props) {
  return (
    <div className={`${styles.status} ${styles[phase]}`} data-testid="connection-status">
      <span className={styles.dot} />
      {PHASE_LABEL[phase]}
    </div>
  );
}
