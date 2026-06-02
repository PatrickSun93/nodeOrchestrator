import { useCallback } from "react";
import { postIntent } from "../api/client.ts";
import type { IntentError } from "../api/client.ts";
import { useRoomStore } from "../store.ts";

export function useIntent() {
  const roomId = useRoomStore((s) => s.roomId);
  const setPendingIntent = useRoomStore((s) => s.setPendingIntent);

  const send = useCallback(
    async (content: string) => {
      if (!roomId) return;
      setPendingIntent({ content, status: "sending" });
      try {
        await postIntent(roomId, { type: "user_input", content });
        // On success: events arrive via WS; mark intent as sent.
        setPendingIntent({ content, status: "sent" });
      } catch (err) {
        const intentErr = err as IntentError;
        if (intentErr.stage === "turn") {
          // Intent landed — do NOT re-post. WS replay will reconcile.
          setPendingIntent({ content, status: "sent" });
        } else {
          // stage === "append" — nothing persisted, safe to retry.
          setPendingIntent({ content, status: "failed" });
        }
      }
    },
    [roomId, setPendingIntent],
  );

  return { send };
}
