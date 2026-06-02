import { create } from "zustand";
import type { Event, RoomType } from "./api/client.ts";
import type { StreamErrorMessage } from "./api/stream.ts";

export type Phase = "idle" | "loading" | "live" | "reconnecting" | "error";
export type IntentStatus = "sending" | "sent" | "failed";

export interface PendingIntent {
  content: string;
  status: IntentStatus;
}

export interface LastError {
  stage: "append" | "turn";
  reason: string;
}

export interface RoomStore {
  roomId: string | null;
  roomType: RoomType | null;
  events: Event[];
  seenIds: Set<string>;
  phase: Phase;
  pendingIntent: PendingIntent | null;
  lastError: LastError | null;
  setRoom: (id: string, type: RoomType) => void;
  applyEvent: (event: Event) => void;
  replayComplete: () => void;
  setPhase: (phase: Phase) => void;
  setError: (error: StreamErrorMessage) => void;
  setPendingIntent: (intent: PendingIntent | null) => void;
  reset: () => void;
}

function insertByTimestamp(events: Event[], event: Event): Event[] {
  // Insert maintaining ascending timestamp order; arrival order breaks ties.
  const idx = events.findIndex((e) => e.timestamp > event.timestamp);
  if (idx === -1) return [...events, event];
  return [...events.slice(0, idx), event, ...events.slice(idx)];
}

export const useRoomStore = create<RoomStore>((set) => ({
  roomId: null,
  roomType: null,
  events: [],
  seenIds: new Set<string>(),
  phase: "idle",
  pendingIntent: null,
  lastError: null,

  setRoom: (id, type) =>
    set({
      roomId: id,
      roomType: type,
      events: [],
      seenIds: new Set<string>(),
      phase: "idle",
      pendingIntent: null,
      lastError: null,
    }),

  // Central dedup+order chokepoint — replay, live, and reconnect all funnel here.
  applyEvent: (event) =>
    set((state) => {
      if (state.seenIds.has(event.id)) return {};
      const seenIds = new Set(state.seenIds);
      seenIds.add(event.id);
      return {
        events: insertByTimestamp(state.events, event),
        seenIds,
      };
    }),

  replayComplete: () => set({ phase: "live" }),

  setPhase: (phase) => set({ phase }),

  setError: (error) =>
    set({
      lastError: { stage: error.stage, reason: error.reason },
      ...(error.stage === "turn" ? { phase: "error" as Phase } : {}),
    }),

  setPendingIntent: (intent) => set({ pendingIntent: intent }),

  reset: () =>
    set({
      roomId: null,
      roomType: null,
      events: [],
      seenIds: new Set<string>(),
      phase: "idle",
      pendingIntent: null,
      lastError: null,
    }),
}));
