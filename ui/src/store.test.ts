import { describe, it, expect, beforeEach } from "vitest";
import { useRoomStore } from "./store.ts";
import type { Event } from "./api/client.ts";

function makePendingEvent(
  id: string,
  callId: string,
  tier: "countdown_confirm" | "hard_confirm" = "countdown_confirm",
  timestamp = 1,
): Event {
  return {
    id,
    room_id: "r1",
    type: "tool_call_pending",
    author: "agent:operator",
    timestamp,
    content: "",
    metadata: {
      tool_name: "apply_edit",
      call_id: callId,
      params: {},
      tier,
      initiating_agent: "operator",
    },
  };
}

function makeResolutionEvent(id: string, callId: string, type: Event["type"]): Event {
  return {
    id,
    room_id: "r1",
    type,
    author: "agent:operator",
    timestamp: 2,
    content: "",
    metadata: { call_id: callId },
  };
}

function makeEvent(id: string, timestamp = 1): Event {
  return { id, room_id: "r1", type: "utterance", author: "agent:senior", timestamp, content: "hi" };
}

describe("Zustand store", () => {
  beforeEach(() => {
    useRoomStore.getState().reset();
  });

  it("initial state is idle with no room", () => {
    const s = useRoomStore.getState();
    expect(s.phase).toBe("idle");
    expect(s.roomId).toBeNull();
    expect(s.events).toHaveLength(0);
  });

  it("setRoom resets events and seenIds", () => {
    useRoomStore.getState().applyEvent(makeEvent("e1"));
    useRoomStore.getState().setRoom("r2", "free_chat");
    const s = useRoomStore.getState();
    expect(s.roomId).toBe("r2");
    expect(s.events).toHaveLength(0);
    expect(s.seenIds.size).toBe(0);
  });

  it("applyEvent deduplicates by event.id", () => {
    const { applyEvent } = useRoomStore.getState();
    applyEvent(makeEvent("e1"));
    applyEvent(makeEvent("e1")); // dup
    applyEvent(makeEvent("e1")); // dup again
    expect(useRoomStore.getState().events).toHaveLength(1);
  });

  it("applyEvent inserts events ordered by timestamp", () => {
    const { applyEvent } = useRoomStore.getState();
    applyEvent(makeEvent("e3", 300));
    applyEvent(makeEvent("e1", 100));
    applyEvent(makeEvent("e2", 200));
    const ids = useRoomStore.getState().events.map((e) => e.id);
    expect(ids).toEqual(["e1", "e2", "e3"]);
  });

  it("applyEvent deduplicates replay/live overlap (seen in replay, arrives again live)", () => {
    const { applyEvent } = useRoomStore.getState();
    applyEvent(makeEvent("e1", 100)); // replay
    applyEvent(makeEvent("e2", 200)); // replay
    // Simulate replay_complete, then live events (e2 was in both replay and live overlap)
    applyEvent(makeEvent("e2", 200)); // live dup — should not render twice
    applyEvent(makeEvent("e3", 300)); // new live event
    const ids = useRoomStore.getState().events.map((e) => e.id);
    expect(ids).toEqual(["e1", "e2", "e3"]);
  });

  it("replayComplete sets phase to live", () => {
    useRoomStore.getState().replayComplete();
    expect(useRoomStore.getState().phase).toBe("live");
  });

  it("setPhase updates phase", () => {
    useRoomStore.getState().setPhase("reconnecting");
    expect(useRoomStore.getState().phase).toBe("reconnecting");
  });

  it("setError with stage:turn sets phase to error and records lastError", () => {
    useRoomStore
      .getState()
      .setError({ kind: "error", stage: "turn", appended_event_id: null, reason: "boom" });
    const s = useRoomStore.getState();
    expect(s.phase).toBe("error");
    expect(s.lastError).toEqual({ stage: "turn", reason: "boom" });
  });

  it("setError with stage:append does NOT set phase to error", () => {
    useRoomStore.getState().setPhase("live");
    useRoomStore
      .getState()
      .setError({ kind: "error", stage: "append", appended_event_id: null, reason: "append fail" });
    const s = useRoomStore.getState();
    expect(s.phase).toBe("live"); // phase unchanged for append errors
    expect(s.lastError?.stage).toBe("append");
  });

  it("setPendingIntent stores and clears pending intent", () => {
    useRoomStore.getState().setPendingIntent({ content: "hello", status: "sending" });
    expect(useRoomStore.getState().pendingIntent?.content).toBe("hello");
    useRoomStore.getState().setPendingIntent(null);
    expect(useRoomStore.getState().pendingIntent).toBeNull();
  });

  it("reset clears all state", () => {
    useRoomStore.getState().setRoom("r1", "free_chat");
    useRoomStore.getState().applyEvent(makeEvent("e1"));
    useRoomStore.getState().setPhase("live");
    useRoomStore.getState().reset();
    const s = useRoomStore.getState();
    expect(s.roomId).toBeNull();
    expect(s.events).toHaveLength(0);
    expect(s.phase).toBe("idle");
  });

  it("reconnect-replay deduplication: events seen in first connection are deduped across reconnect", () => {
    const { applyEvent } = useRoomStore.getState();
    // First connection replay
    applyEvent(makeEvent("e1", 100));
    applyEvent(makeEvent("e2", 200));
    // Disconnect + reconnect: server replays from the start
    applyEvent(makeEvent("e1", 100)); // dup
    applyEvent(makeEvent("e2", 200)); // dup
    applyEvent(makeEvent("e3", 300)); // new
    const ids = useRoomStore.getState().events.map((e) => e.id);
    expect(ids).toEqual(["e1", "e2", "e3"]);
  });
});

// ---------------------------------------------------------------------------
// F1: pending calls set (ADR-030 D6)
// ---------------------------------------------------------------------------

describe("pendingCalls store (F1 — ADR-030 D6)", () => {
  beforeEach(() => {
    useRoomStore.getState().reset();
  });

  it("applyEvent adds TOOL_CALL_PENDING to pendingCalls", () => {
    useRoomStore.getState().applyEvent(makePendingEvent("p1", "call_abc"));
    const { pendingCalls } = useRoomStore.getState();
    expect(pendingCalls.size).toBe(1);
    const p = pendingCalls.get("p1");
    expect(p?.tool_name).toBe("apply_edit");
    expect(p?.call_id).toBe("call_abc");
    expect(p?.autonomy_tier).toBe("countdown_confirm");
  });

  it("TOOL_CALL_PENDING deduplicates (same event_id not added twice)", () => {
    useRoomStore.getState().applyEvent(makePendingEvent("p1", "call_abc"));
    useRoomStore.getState().applyEvent(makePendingEvent("p1", "call_abc")); // dup
    expect(useRoomStore.getState().pendingCalls.size).toBe(1);
  });

  it("applyEvent removes pending call on TOOL_CALL resolution", () => {
    useRoomStore.getState().applyEvent(makePendingEvent("p1", "call_abc"));
    useRoomStore
      .getState()
      .applyEvent(makeResolutionEvent("r1", "call_abc", "tool_call"));
    expect(useRoomStore.getState().pendingCalls.size).toBe(0);
  });

  it("applyEvent removes pending call on TOOL_CALL_CANCELLED", () => {
    useRoomStore.getState().applyEvent(makePendingEvent("p1", "call_abc"));
    useRoomStore
      .getState()
      .applyEvent(makeResolutionEvent("r1", "call_abc", "tool_call_cancelled"));
    expect(useRoomStore.getState().pendingCalls.size).toBe(0);
  });

  it("applyEvent removes pending call on TOOL_RESULT", () => {
    useRoomStore.getState().applyEvent(makePendingEvent("p1", "call_abc"));
    useRoomStore
      .getState()
      .applyEvent(makeResolutionEvent("r1", "call_abc", "tool_result"));
    expect(useRoomStore.getState().pendingCalls.size).toBe(0);
  });

  it("resolution for unknown call_id does not crash or modify set", () => {
    useRoomStore.getState().applyEvent(makePendingEvent("p1", "call_abc"));
    useRoomStore
      .getState()
      .applyEvent(makeResolutionEvent("r1", "call_other", "tool_call"));
    // "call_abc" pending call remains since "call_other" doesn't match
    expect(useRoomStore.getState().pendingCalls.size).toBe(1);
  });

  it("seedPendingCalls seeds from snapshot refs", () => {
    const pendingEvt = makePendingEvent("p_seed", "call_seed", "hard_confirm");
    const ref = {
      event_id: "p_seed",
      tool_name: "apply_edit",
      autonomy_tier: "hard_confirm" as const,
    };
    useRoomStore.getState().seedPendingCalls([ref], [pendingEvt]);
    const p = useRoomStore.getState().pendingCalls.get("p_seed");
    expect(p?.call_id).toBe("call_seed");
    expect(p?.autonomy_tier).toBe("hard_confirm");
  });

  it("setRoom resets pendingCalls", () => {
    useRoomStore.getState().applyEvent(makePendingEvent("p1", "call_abc"));
    useRoomStore.getState().setRoom("r2", "free_chat");
    expect(useRoomStore.getState().pendingCalls.size).toBe(0);
  });
});
