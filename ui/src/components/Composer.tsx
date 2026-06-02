import { useState } from "react";
import { useRoomStore } from "../store.ts";
import { useIntent } from "../hooks/useIntent.ts";
import styles from "./Composer.module.css";

export function Composer() {
  const [text, setText] = useState("");
  const pendingIntent = useRoomStore((s) => s.pendingIntent);
  const lastError = useRoomStore((s) => s.lastError);
  const { send } = useIntent();

  const isSending = pendingIntent?.status === "sending";
  // stage:turn error means intent already landed — do NOT offer re-send (HR#4)
  const turnErrorLanded = lastError?.stage === "turn";
  // pendingIntent.status === "failed" means stage:append (useIntent only marks failed on append error)
  const appendErrorRetry = pendingIntent?.status === "failed";

  async function handleSend() {
    const content = text.trim();
    if (!content || isSending) return;
    setText("");
    await send(content);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }

  return (
    <div className={styles.composer} data-testid="composer">
      {turnErrorLanded && (
        <div className={styles.turnError} data-testid="turn-error-notice">
          消息已发送，正在同步结果…（请勿重发）
        </div>
      )}
      {appendErrorRetry && (
        <div className={styles.appendError} data-testid="append-error-notice">
          发送失败，可以重试。
        </div>
      )}
      <div className={styles.row}>
        <textarea
          className={styles.textarea}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入消息… (Enter 发送, Shift+Enter 换行)"
          rows={2}
          disabled={isSending || turnErrorLanded}
          data-testid="composer-textarea"
        />
        <button
          className={styles.sendBtn}
          onClick={() => void handleSend()}
          disabled={isSending || !text.trim() || turnErrorLanded}
          data-testid="send-button"
        >
          发送
        </button>
      </div>
    </div>
  );
}
