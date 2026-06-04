import { useState } from "react";
import type { ConfirmError, ConfirmResponse } from "../api/client.ts";
import { postConfirm } from "../api/client.ts";

export type ConfirmStatus = "idle" | "sending" | "confirmed" | "cancelled" | "error";

export interface UseConfirmResult {
  status: ConfirmStatus;
  error: ConfirmError | null;
  /** Send approve or cancel for a pending gated call. */
  confirm: (
    roomId: string,
    pendingEventId: string,
    decision: "approve" | "cancel",
  ) => Promise<ConfirmResponse | null>;
}

/**
 * Hook for the confirm-then-execute flow (ADR-030 D6).
 *
 * Partial-turn semantics (D5):
 *   stage:"execute" → mark confirmed; do not re-post (TOOL_CALL already landed).
 *   stage:"append"  → allow retry (nothing was persisted).
 */
export function useConfirm(): UseConfirmResult {
  const [status, setStatus] = useState<ConfirmStatus>("idle");
  const [error, setError] = useState<ConfirmError | null>(null);

  const confirm = async (
    roomId: string,
    pendingEventId: string,
    decision: "approve" | "cancel",
  ): Promise<ConfirmResponse | null> => {
    setStatus("sending");
    setError(null);
    try {
      const resp = await postConfirm(roomId, { pending_event_id: pendingEventId, decision });
      setStatus(decision === "approve" ? "confirmed" : "cancelled");
      return resp;
    } catch (err) {
      const ce = err as ConfirmError;
      setError(ce);
      if (ce.stage === "execute") {
        // TOOL_CALL already appended — treat as confirmed; do not allow re-post.
        setStatus("confirmed");
      } else {
        setStatus("error");
      }
      return null;
    }
  };

  return { status, error, confirm };
}
