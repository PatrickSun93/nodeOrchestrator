import type { Event } from "./client.ts";

// Hand-written WS message types (asyncapi.md sample shapes + wire.py StreamMessage).
// Not in openapi.json — codegen covers HTTP only.

export interface StreamEventMessage {
  kind: "event";
  event: Event;
}

export interface StreamReplayCompleteMessage {
  kind: "replay_complete";
}

export interface StreamErrorMessage {
  kind: "error";
  stage: "append" | "turn";
  appended_event_id: string | null;
  reason: string;
}

export interface PingMessage {
  kind: "ping";
}

export type StreamMessage =
  | StreamEventMessage
  | StreamReplayCompleteMessage
  | StreamErrorMessage
  | PingMessage;

export type StreamPhase = "loading" | "live" | "reconnecting";

export interface StreamCallbacks {
  onEvent: (event: Event) => void;
  onReplayComplete: () => void;
  onError: (error: StreamErrorMessage) => void;
  onPhaseChange: (phase: StreamPhase) => void;
}

const BACKOFF_BASE_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;

export function connectStream(
  roomId: string,
  callbacks: StreamCallbacks,
  signal: AbortSignal,
): () => void {
  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;

  function connect() {
    if (signal.aborted) return;
    callbacks.onPhaseChange("loading");

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${window.location.host}/rooms/${roomId}/stream`;
    ws = new WebSocket(url);

    ws.onmessage = (ev: MessageEvent<string>) => {
      let msg: unknown;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!msg || typeof msg !== "object" || !("kind" in msg)) return;

      const m = msg as StreamMessage;
      if (m.kind === "event") {
        callbacks.onEvent(m.event);
      } else if (m.kind === "replay_complete") {
        attempt = 0;
        callbacks.onReplayComplete();
        callbacks.onPhaseChange("live");
      } else if (m.kind === "error") {
        callbacks.onError(m);
      }
      // kind === "ping": no-op
    };

    ws.onclose = () => {
      if (signal.aborted) return;
      callbacks.onPhaseChange("reconnecting");
      const delay = Math.min(BACKOFF_BASE_MS * 2 ** attempt, BACKOFF_MAX_MS);
      attempt += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws?.close();
    };
  }

  signal.addEventListener("abort", () => {
    if (reconnectTimer !== null) clearTimeout(reconnectTimer);
    ws?.close();
  });

  connect();

  return () => {
    if (reconnectTimer !== null) clearTimeout(reconnectTimer);
    ws?.close();
  };
}
