import { describe, it, expect, beforeEach } from "vitest";
import { useRoomStore } from "./store.ts";
import type { Event } from "./api/client.ts";

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
