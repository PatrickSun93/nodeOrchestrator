import styles from "./ConfigPage.module.css";

interface ConfigSection {
  title: string;
  desc: string;
}

const CONFIG_SECTIONS: ConfigSection[] = [
  {
    title: "自主性层级",
    desc: "工具调用的确认策略（countdown_confirm / hard_confirm）。由 config/autonomy.yaml 管理。",
  },
  {
    title: "MCP 服务器",
    desc: "Model Context Protocol 服务器列表及连接参数。由 config/mcp_servers.yaml 管理。",
  },
  {
    title: "代理配置",
    desc: "房间内代理的角色、提示和参与规则。由 config/agents/ 目录管理。",
  },
  {
    title: "模型",
    desc: "LLM 模型定义（provider、id、温度等参数）。由 config/llm_config.yaml 管理。",
  },
  {
    title: "LLM 覆盖",
    desc: "全局 LLM 覆盖配置，可为所有代理替换默认模型。由 config/llm_config.yaml 的 override 字段管理。",
  },
];

export function ConfigPage() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>配置</h1>
        <p className={styles.subtitle}>系统配置概览</p>
      </div>

      <div className={styles.note}>
        以下配置项由服务端 YAML 文件管理。如需修改，请直接编辑对应文件并重启服务器。
        当前版本暂无配置读取 API，所有项目均为只读展示。
      </div>

      <div className={styles.grid}>
        {CONFIG_SECTIONS.map((s) => (
          <div key={s.title} className={styles.card}>
            <div className={styles.cardHeader}>
              <h2 className={styles.cardTitle}>{s.title}</h2>
              <span className={styles.roTag}>只读</span>
            </div>
            <p className={styles.cardDesc}>{s.desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
