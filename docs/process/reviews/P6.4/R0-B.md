---
task_id: P6.4
round: R0-B
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 1
---

# R0-B 跨族审查 — P6.4 (descriptive doc-pin: E+F egress residuals → ADR-037 D5)

## 视角

纯 doc-pin，零行为变更。跨族视角聚焦**inscription 诚实性**：ADR/D5 描述是否与代码已执行的表面对齐——不夸大、不缩小——以及 F pin 测试在代理被松绑（fail-open-for-http）时是否会失败。

---

## 发现

### 🟢 G1 — 零 egress 行为变更；inscription 诚实；F pin 正确地在松绑时告警

**证据：**

1. **`egress_proxy.py` 零可执行代码变更。** Diff 仅触及模块 docstring。`_handle:140-141`（`parts[0].upper() != "CONNECT"` → 405）逐字节未变。Allowlist 检查 `:159`、`_send_response`、`_relay`、`_serve`——全部未动。

2. **`spawn.py` 零变更。** `_create_network:226-230` 仍创建不带 `--internal` 的 bridge。未添加任何 `--internal` 标志。

3. **脊柱零 diff。** `git diff origin/main...origin/claude/P6.4-impl -- src/orchestrator/{core,autonomy,llm,rooms}/` 为空。`_execute_local_call`、gate、`LLMPurpose`、`run_pipeline`、COUNTDOWN spine——全部未动。

4. **Docstring 修正是诚实的。** 旧 docstring 声称 `http(s): … → CONNECT` 适用于 plain-http 和 https。`_handle:140-141` 处的代码对任何非 CONNECT 方法返回 405——plain-http 从未被支持。新 docstring 正确分离了 https（CONNECT → 隧道）和 plain http（绝对形式 GET → 405 → fail-closed）。该更正移除了一个 over-claim；并未引入一个。

5. **E bullet 诚实**（ADR-037 D5）：声称 bridge 不带 `--internal` 创建；代理是执行点而非 bridge 防火墙；残差受 DNS-disabled + `--cap-drop=ALL` + `nobody` + 操作员控制镜像约束；`--internal` 被保留因其可能破坏代理可达性。五项声明均已对照代码验证。既未 under-claim（承认 bridge 通过 NAT 可达互联网）也未 over-claim（未声称 bridge 已防火墙化——而是说代理是执行点）。

6. **F bullet 诚实**（ADR-037 D5）：声称代理仅 CONNECT；in-container urllib 对 `http://` 发送绝对形式 GET → 405；fetch fail-closed（TOOL_FAILED，无 exfil）；https 不受影响；与 D4 默认 fail-closed 一致。全部声明已验证。

7. **F pin 测试 (`test_f_plain_http_fails_closed_405`)** 发送 `GET http://allowed.internal/ HTTP/1.1\r\nHost: allowed.internal\r\n\r\n`——即 in-container `urllib` 对 plain-http URL 通过 `HTTP_PROXY` 路由时发出的确切绝对形式 GET。代理的 `_handle:140` 解析 method=`GET` ≠ `CONNECT` → 返回 405。测试断言 `b"405" in response`。若任何人松绑代理以转发非 CONNECT 方法（移除 `!= "CONNECT"` 检查或添加 CONNECT 前的 GET 处理器），响应将从 405 变为其他内容 → 断言 **FAIL**。该 pin 正确放置在执行 fail-closed 的确切代码路径上。

8. **ADR Amendment 2 诚实。** 明确指出"没有行为变更，没有语义变更"和"descriptive doc-pin — `plan_has_adr=false`"。两项陈述均为真。

9. **门禁全绿。** ruff 通过。ruff format：2 文件已格式化。`mypy --strict src tests`：310 源文件零问题。`pytest tests/sandbox/test_egress_proxy.py`：8/8 通过（7 个已有 + 1 个新 F pin 测试）。

---

## 综合

无待上报发现。跨族视角确认：执行表面未变（代理仍仅 CONNECT，bridge 仍不带 `--internal`，脊柱未动），inscription 诚实（既未 under-claim 也未 over-claim），F pin 测试在松绑时正确告警（对 urllib 发出的确切请求断言 405）。

**Verdict：clean。**
