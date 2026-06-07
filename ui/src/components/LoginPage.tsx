import { useState } from "react";
import { IconSparkles } from "@tabler/icons-react";
import { login, AuthError } from "../api/client.ts";
import { useAuthStore } from "../authStore.ts";
import styles from "./LoginPage.module.css";

export function LoginPage() {
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const setAuthenticated = useAuthStore((s) => s.setAuthenticated);

  async function handleLogin() {
    const uid = userId.trim();
    if (!uid || !password) return;
    setError(null);
    setLoading(true);
    try {
      const res = await login(uid, password);
      setAuthenticated(res.user_id);
    } catch (err) {
      if (err instanceof AuthError) {
        setError("用户名或密码不正确");
      } else {
        setError("登录失败，请稍后重试");
      }
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") void handleLogin();
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.brand}>
          <div className={styles.avatar}>
            <IconSparkles size={18} />
          </div>
          <span className={styles.wordmark}>Orchestrator</span>
        </div>
        <div className={styles.form}>
          <label className={styles.label}>
            用户名
            <input
              type="text"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              onKeyDown={handleKeyDown}
              className={styles.input}
              placeholder="user_id"
              autoComplete="username"
              data-testid="login-userid"
            />
          </label>
          <label className={styles.label}>
            密码
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={handleKeyDown}
              className={styles.input}
              placeholder="••••••••"
              autoComplete="current-password"
              data-testid="login-password"
            />
          </label>
          {error && <div className={styles.error}>{error}</div>}
          <button
            onClick={() => void handleLogin()}
            disabled={loading || !userId.trim() || !password}
            className={styles.btn}
            data-testid="login-submit"
          >
            {loading ? "登录中…" : "登录"}
          </button>
        </div>
      </div>
    </div>
  );
}
