import { IconSparkles } from "@tabler/icons-react";
import styles from "./NavBar.module.css";

export type NavView = "lobby" | "plugins" | "config";

interface NavBarProps {
  view: NavView;
  onView: (v: NavView) => void;
  userId: string | null;
  onLogout: () => void;
}

export function NavBar({ view, onView, userId, onLogout }: NavBarProps) {
  return (
    <nav className={styles.nav} role="navigation">
      <div className={styles.brand}>
        <div className={styles.avatar}>
          <IconSparkles size={14} />
        </div>
        <span className={styles.wordmark}>Orchestrator</span>
      </div>

      <button
        className={`${styles.navBtn} ${view === "lobby" ? styles.navBtnActive : ""}`}
        onClick={() => onView("lobby")}
      >
        聊天
      </button>
      <button
        className={`${styles.navBtn} ${view === "plugins" ? styles.navBtnActive : ""}`}
        onClick={() => onView("plugins")}
      >
        插件
      </button>
      <button
        className={`${styles.navBtn} ${view === "config" ? styles.navBtnActive : ""}`}
        onClick={() => onView("config")}
      >
        配置
      </button>

      <div className={styles.spacer} />

      {userId && <span className={styles.userChip}>{userId}</span>}
      <button className={styles.logoutBtn} onClick={onLogout}>
        退出
      </button>
    </nav>
  );
}
