import { useState, useEffect, useCallback } from "react";
import {
  getPlugins,
  enablePlugin,
  disablePlugin,
  admitPlugin,
  deletePlugin,
  AuthError,
} from "../api/client.ts";
import type { PluginInfo } from "../api/client.ts";
import { useAuthStore } from "../authStore.ts";
import styles from "./PluginsPage.module.css";

export function PluginsPage() {
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showRestartBanner, setShowRestartBanner] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showAdmit, setShowAdmit] = useState(false);
  const [admitId, setAdmitId] = useState("");
  const [admitUrl, setAdmitUrl] = useState("");
  const [admitDigest, setAdmitDigest] = useState("");
  const [admitVersion, setAdmitVersion] = useState("");
  const [admitting, setAdmitting] = useState(false);
  const setUnauthenticated = useAuthStore((s) => s.setUnauthenticated);

  const loadPlugins = useCallback(async () => {
    setFetchError(null);
    try {
      const list = await getPlugins();
      setPlugins(list);
    } catch (err) {
      if (err instanceof AuthError) {
        setUnauthenticated();
        return;
      }
      setFetchError("加载插件列表失败");
    } finally {
      setLoading(false);
    }
  }, [setUnauthenticated]);

  useEffect(() => {
    void loadPlugins();
  }, [loadPlugins]);

  async function runAction(pluginId: string, action: () => Promise<unknown>) {
    setActionError(null);
    setBusyId(pluginId);
    try {
      await action();
      setShowRestartBanner(true);
      await loadPlugins();
    } catch (err) {
      if (err instanceof AuthError) {
        setUnauthenticated();
        return;
      }
      const msg = (err as { reason?: string }).reason ?? "请稍后重试";
      setActionError(`操作失败：${msg}`);
    } finally {
      setBusyId(null);
    }
  }

  async function handleAdmit() {
    const pid = admitId.trim();
    const url = admitUrl.trim();
    const digest = admitDigest.trim();
    if (!pid || !url || !digest) return;
    setAdmitting(true);
    setActionError(null);
    try {
      await admitPlugin(pid, {
        source_url: url,
        digest,
        version: admitVersion.trim() || null,
      });
      setShowRestartBanner(true);
      setShowAdmit(false);
      setAdmitId("");
      setAdmitUrl("");
      setAdmitDigest("");
      setAdmitVersion("");
      await loadPlugins();
    } catch (err) {
      if (err instanceof AuthError) {
        setUnauthenticated();
        return;
      }
      const msg = (err as { reason?: string }).reason ?? "请稍后重试";
      setActionError(`添加失败：${msg}`);
    } finally {
      setAdmitting(false);
    }
  }

  function provenanceLabel(p: string): string {
    if (p === "operator_placed") return "本地";
    if (p === "fetched") return "远程";
    return "待同步";
  }

  if (loading) {
    return (
      <div className={styles.page}>
        <p className={styles.emptyMsg}>加载中…</p>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>插件管理</h1>
        <button className={styles.addBtn} onClick={() => setShowAdmit((v) => !v)}>
          {showAdmit ? "取消" : "+ 添加插件"}
        </button>
      </div>

      {showRestartBanner && (
        <div className={styles.restartBanner}>
          ⚠️ 操作已记录，将在下次重启后生效
          <button onClick={() => setShowRestartBanner(false)}>✕</button>
        </div>
      )}

      {showAdmit && (
        <div className={styles.admitForm}>
          <p className={styles.admitTitle}>添加远程插件</p>
          <div className={styles.admitGrid}>
            <label className={styles.formField}>
              插件 ID *
              <input
                type="text"
                value={admitId}
                onChange={(e) => setAdmitId(e.target.value)}
                placeholder="my_plugin"
              />
            </label>
            <label className={styles.formField}>
              版本（可选）
              <input
                type="text"
                value={admitVersion}
                onChange={(e) => setAdmitVersion(e.target.value)}
                placeholder="1.0.0"
              />
            </label>
            <label className={styles.formField}>
              来源 URL *
              <input
                type="text"
                value={admitUrl}
                onChange={(e) => setAdmitUrl(e.target.value)}
                placeholder="https://example.com/plugin.zip"
              />
            </label>
            <label className={styles.formField}>
              Digest *
              <input
                type="text"
                value={admitDigest}
                onChange={(e) => setAdmitDigest(e.target.value)}
                placeholder="sha256:abc123..."
              />
            </label>
          </div>
          <div className={styles.admitActions}>
            <button
              className={styles.admitSubmitBtn}
              onClick={() => void handleAdmit()}
              disabled={admitting || !admitId.trim() || !admitUrl.trim() || !admitDigest.trim()}
            >
              {admitting ? "提交中…" : "提交"}
            </button>
            <button className={styles.admitCancelBtn} onClick={() => setShowAdmit(false)}>
              取消
            </button>
          </div>
        </div>
      )}

      {fetchError && <div className={styles.errorMsg}>{fetchError}</div>}
      {actionError && <div className={styles.errorMsg}>{actionError}</div>}

      {plugins.length === 0 ? (
        <div className={styles.emptyMsg}>暂无已注册的插件</div>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th style={{ width: "22%" }}>插件 ID</th>
              <th style={{ width: "12%" }}>来源</th>
              <th style={{ width: "10%" }}>版本</th>
              <th style={{ width: "10%" }}>取回</th>
              <th style={{ width: "10%" }}>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {plugins.map((p) => (
              <tr key={p.plugin_id}>
                <td className={styles.idCell}>{p.plugin_id}</td>
                <td>
                  <span className={`${styles.badge} ${styles.provBadge}`}>
                    {provenanceLabel(p.provenance)}
                  </span>
                  {p.provenance_kind && (
                    <span
                      className={`${styles.badge} ${styles.provBadge}`}
                      style={{ marginLeft: 4 }}
                    >
                      {p.provenance_kind}
                    </span>
                  )}
                </td>
                <td>{p.version ?? "—"}</td>
                <td>
                  {p.fetched ? (
                    <span className={`${styles.badge} ${styles.badgeFetched}`}>已取回</span>
                  ) : (
                    <span className={`${styles.badge} ${styles.badgeDisabled}`}>否</span>
                  )}
                </td>
                <td>
                  <span
                    className={`${styles.badge} ${
                      p.enabled ? styles.badgeEnabled : styles.badgeDisabled
                    }`}
                  >
                    {p.enabled ? "已启用" : "已禁用"}
                  </span>
                </td>
                <td>
                  <div className={styles.actionGroup}>
                    {p.enabled ? (
                      <button
                        className={styles.actionBtn}
                        disabled={busyId === p.plugin_id}
                        onClick={() =>
                          void runAction(p.plugin_id, () => disablePlugin(p.plugin_id))
                        }
                      >
                        禁用
                      </button>
                    ) : (
                      <button
                        className={styles.actionBtn}
                        disabled={busyId === p.plugin_id}
                        onClick={() => void runAction(p.plugin_id, () => enablePlugin(p.plugin_id))}
                      >
                        启用
                      </button>
                    )}
                    <button
                      className={`${styles.actionBtn} ${styles.removeBtn}`}
                      disabled={busyId === p.plugin_id}
                      onClick={() => void runAction(p.plugin_id, () => deletePlugin(p.plugin_id))}
                    >
                      移除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
