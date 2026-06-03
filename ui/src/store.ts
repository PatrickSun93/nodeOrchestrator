import { create } from "zustand";
import type { Event, RoomType, ToolCallRef } from "./api/client.ts";
import type { StreamErrorMessage } from "./api/stream.ts";

/** Internal pending call entry: ToolCallRef + call_id for resolution matching. */
export interface PendingCall extends ToolCallRef {
  call_id: string;
}

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
  /** Live pending set: TOOL_CALL_PENDING events awaiting confirm (ADR-030 D6). */
  pendingCalls: Map<string, PendingCall>;
  setRoom: (id: string, type: RoomType) => void;
  applyEvent: (event: Event) => void;
  replayComplete: () => void;
  setPhase: (phase: Phase) => void;
  setError: (error: StreamErrorMessage) => void;
  setPendingIntent: (intent: PendingIntent | null) => void;
  /** Seed pending set from snapshot on load/reconnect (ADR-030 D6). */
  seedPendingCalls: (refs: ToolCallRef[], events: Event[]) => void;
  reset: () => void;
}

function insertByTimestamp(events: Event[], event: Event): Event[] {
  // Insert maintaining ascending timestamp order; arrival order breaks ties.
  const idx = events.findIndex((e) => e.timestamp > event.timestamp);
  if (idx === -1) return [...events, event];
  return [...events.slice(0, idx), event, ...events.slice(idx)];
}

// Resolution event types that remove a call from the pending set (mirrors backend predicate).
const RESOLUTION_TYPES = new Set([
  "tool_call",
  "tool_result",
  "tool_failed",
  "tool_call_cancelled",
]);

function applyPendingCalls(state: RoomStore, event: Event): Partial<RoomStore> {
  const type = event.type as string;
  if (type === "tool_call_pending") {
    // A new pending call — add to the set keyed by event_id (ADR-030 D6).
    const meta = (event.metadata ?? {}) as {
      tool_name?: string;
      call_id?: string;
      tier?: string;
    };
    const pending: PendingCall = {
      event_id: event.id,
      tool_name: meta.tool_name ?? "",
      autonomy_tier: (meta.tier as ToolCallRef["autonomy_tier"]) ?? "countdown_confirm",
      call_id: meta.call_id ?? "",
    };
    const pendingCalls = new Map(state.pendingCalls);
    pendingCalls.set(event.id, pending);
    return { pendingCalls };
  }
  if (RESOLUTION_TYPES.has(type)) {
    // A resolution — remove any pending call whose call_id matches.
    const meta = (event.metadata ?? {}) as { call_id?: string };
    const resolvedCallId = meta.call_id;
    if (!resolvedCallId) return {};
    const pendingCalls = new Map(state.pendingCalls);
    for (const [eventId, p] of pendingCalls) {
      if (p.call_id === resolvedCallId) {
        pendingCalls.delete(eventId);
      }
    }
    return { pendingCalls };
  }
  return {};
}

export const useRoomStore = create<RoomStore>((set) => ({
  roomId: null,
  roomType: null,
  events: [],
  seenIds: new Set<string>(),
  phase: "idle",
  pendingIntent: null,
  lastError: null,
  pendingCalls: new Map<string, PendingCall>(),

  setRoom: (id, type) =>
    set({
      roomId: id,
      roomType: type,
      events: [],
      seenIds: new Set<string>(),
      phase: "idle",
      pendingIntent: null,
      lastError: null,
      pendingCalls: new Map<string, PendingCall>(),
    }),

  // Central dedup+order chokepoint — replay, live, and reconnect all funnel here.
  applyEvent: (event) =>
    set((state) => {
      if (state.seenIds.has(event.id)) return {};
      const seenIds = new Set(state.seenIds);
      seenIds.add(event.id);
      const pendingUpdate = applyPendingCalls(state, event);
      return {
        events: insertByTimestamp(state.events, event),
        seenIds,
        ...pendingUpdate,
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

  seedPendingCalls: (refs, events) =>
    set(() => {
      // Seed from snapshot on load/reconnect — keyed by event_id for dedup with live stream.
      // We look up call_id from the matching event to enable resolution tracking.
      const eventById = new Map(events.map((e) => [e.id, e]));
      const pendingCalls = new Map<string, PendingCall>();
      for (const ref of refs) {
        const evt = eventById.get(ref.event_id);
        const callId = evt ? ((evt.metadata as { call_id?: string }).call_id ?? "") : "";
        pendingCalls.set(ref.event_id, { ...ref, call_id: callId });
      }
      return { pendingCalls };
    }),

  reset: () =>
    set({
      roomId: null,
      roomType: null,
      events: [],
      seenIds: new Set<string>(),
      phase: "idle",
      pendingIntent: null,
      lastError: null,
      pendingCalls: new Map<string, PendingCall>(),
    }),
}));
