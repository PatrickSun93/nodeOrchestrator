import { useEffect } from "react";
import { connectStream } from "../api/stream.ts";
import type { StreamCallbacks } from "../api/stream.ts";
import { useRoomStore } from "../store.ts";

export function useRoomStream(roomId: string | null) {
  const applyEvent = useRoomStore((s) => s.applyEvent);
  const replayComplete = useRoomStore((s) => s.replayComplete);
  const setPhase = useRoomStore((s) => s.setPhase);
  const setError = useRoomStore((s) => s.setError);

  useEffect(() => {
    if (!roomId) return;
    const ctrl = new AbortController();

    const callbacks: StreamCallbacks = {
      onEvent: applyEvent,
      onReplayComplete: replayComplete,
      onPhaseChange: (phase) => setPhase(phase),
      onError: setError,
    };

    connectStream(roomId, callbacks, ctrl.signal);
    return () => ctrl.abort();
  }, [roomId, applyEvent, replayComplete, setPhase, setError]);
}
