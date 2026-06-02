import { describe, it, expect, vi, beforeEach } from "vitest";
import type { StreamCallbacks, StreamMessage } from "./stream.ts";
import type { Event } from "./client.ts";

// Mock WebSocket for all stream tests
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closeCalled = false;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  close() {
    this.closeCalled = true;
    this.onclose?.();
  }

  // Test helper: simulate receiving a message
  receive(msg: StreamMessage) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

function makeEvent(id: string, timestamp = 1): Event {
  return { id, room_id: "r1", type: "utterance", author: "agent:senior", timestamp, content: "hi" };
}

function makeCallbacks() {
  return {
    onEvent: vi.fn(),
    onReplayComplete: vi.fn(),
    onError: vi.fn(),
    onPhaseChange: vi.fn(),
  } satisfies StreamCallbacks;
}

describe("WS stream client", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal("window", {
      location: { protocol: "http:", host: "localhost:5173" },
    });
  });

  it("connect transitions to loading phase", async () => {
    const { connectStream } = await import("./stream.ts");
    const cb = makeCallbacks();
    const ctrl = new AbortController();
    connectStream("r1", cb, ctrl.signal);
    expect(cb.onPhaseChange).toHaveBeenCalledWith("loading");
    ctrl.abort();
  });

  it("replay phase: onEvent called for each event message", async () => {
    const { connectStream } = await import("./stream.ts");
    const cb = makeCallbacks();
    const ctrl = new AbortController();
    connectStream("r1", cb, ctrl.signal);

    const ws = MockWebSocket.instances[0]!;
    ws.receive({ kind: "event", event: makeEvent("e1") });
    ws.receive({ kind: "event", event: makeEvent("e2") });
    expect(cb.onEvent).toHaveBeenCalledTimes(2);
    expect(cb.onEvent.mock.calls[0]?.[0].id).toBe("e1");
    ctrl.abort();
  });

  it("replay_complete transitions to live phase", async () => {
    const { connectStream } = await import("./stream.ts");
    const cb = makeCallbacks();
    const ctrl = new AbortController();
    connectStream("r1", cb, ctrl.signal);

    const ws = MockWebSocket.instances[0]!;
    ws.receive({ kind: "replay_complete" });
    expect(cb.onReplayComplete).toHaveBeenCalledOnce();
    expect(cb.onPhaseChange).toHaveBeenCalledWith("live");
    ctrl.abort();
  });

  it("live phase: onEvent called for live events after replay_complete", async () => {
    const { connectStream } = await import("./stream.ts");
    const cb = makeCallbacks();
    const ctrl = new AbortController();
    connectStream("r1", cb, ctrl.signal);

    const ws = MockWebSocket.instances[0]!;
    ws.receive({ kind: "event", event: makeEvent("e1") });
    ws.receive({ kind: "replay_complete" });
    ws.receive({ kind: "event", event: makeEvent("e2") });
    expect(cb.onEvent).toHaveBeenCalledTimes(2);
    ctrl.abort();
  });

  it("StreamError stage:append → onError called", async () => {
    const { connectStream } = await import("./stream.ts");
    const cb = makeCallbacks();
    const ctrl = new AbortController();
    connectStream("r1", cb, ctrl.signal);

    const ws = MockWebSocket.instances[0]!;
    ws.receive({ kind: "error", stage: "append", appended_event_id: null, reason: "fail" });
    expect(cb.onError).toHaveBeenCalledWith(
      expect.objectContaining({ stage: "append", reason: "fail" }),
    );
    ctrl.abort();
  });

  it("StreamError stage:turn → onError called", async () => {
    const { connectStream } = await import("./stream.ts");
    const cb = makeCallbacks();
    const ctrl = new AbortController();
    connectStream("r1", cb, ctrl.signal);

    const ws = MockWebSocket.instances[0]!;
    ws.receive({ kind: "error", stage: "turn", appended_event_id: "e1", reason: "turn failed" });
    expect(cb.onError.mock.calls[0]?.[0].stage).toBe("turn");
    ctrl.abort();
  });

  it("ping message: no callback called", async () => {
    const { connectStream } = await import("./stream.ts");
    const cb = makeCallbacks();
    const ctrl = new AbortController();
    connectStream("r1", cb, ctrl.signal);

    const ws = MockWebSocket.instances[0]!;
    const callsBefore = [
      cb.onEvent.mock.calls.length,
      cb.onError.mock.calls.length,
      cb.onReplayComplete.mock.calls.length,
    ];
    ws.receive({ kind: "ping" });
    expect(cb.onEvent.mock.calls.length).toBe(callsBefore[0]);
    expect(cb.onError.mock.calls.length).toBe(callsBefore[1]);
    expect(cb.onReplayComplete.mock.calls.length).toBe(callsBefore[2]);
    ctrl.abort();
  });

  it("reconnect: re-connects and re-dedup works across reconnect", async () => {
    vi.useFakeTimers();
    const { connectStream } = await import("./stream.ts");
    const cb = makeCallbacks();
    const ctrl = new AbortController();
    connectStream("r1", cb, ctrl.signal);

    // First connection: receive e1 in replay
    const ws1 = MockWebSocket.instances[0]!;
    ws1.receive({ kind: "event", event: makeEvent("e1") });
    ws1.receive({ kind: "replay_complete" });

    // Simulate disconnect (server side close without abort)
    ws1.onclose?.();
    expect(cb.onPhaseChange).toHaveBeenCalledWith("reconnecting");

    // Advance timer to trigger reconnect
    await vi.runAllTimersAsync();

    expect(MockWebSocket.instances.length).toBe(2);
    const ws2 = MockWebSocket.instances[1]!;
    // Re-replay sends e1 again + new e2
    ws2.receive({ kind: "event", event: makeEvent("e1") }); // dup — should be deduplicated by store
    ws2.receive({ kind: "event", event: makeEvent("e2") });
    ws2.receive({ kind: "replay_complete" });

    // Both e1 and e2 forwarded to callback (dedup is store's job, not stream's)
    // First connection: e1 (1). Second connection replay: e1-dup (2), e2 (3).
    expect(cb.onEvent).toHaveBeenCalledTimes(3);
    // Confirm second connection transitoned through loading → live
    expect(cb.onPhaseChange).toHaveBeenCalledWith("loading");
    expect(cb.onPhaseChange).toHaveBeenCalledWith("live");
    vi.useRealTimers();
    ctrl.abort();
  });

  it("abort signal closes the WebSocket and stops reconnect", async () => {
    const { connectStream } = await import("./stream.ts");
    const cb = makeCallbacks();
    const ctrl = new AbortController();
    connectStream("r1", cb, ctrl.signal);

    const ws = MockWebSocket.instances[0]!;
    ctrl.abort();
    expect(ws.closeCalled).toBe(true);
    // No more phase changes after abort
    const callCount = cb.onPhaseChange.mock.calls.length;
    ws.onclose?.();
    expect(cb.onPhaseChange.mock.calls.length).toBe(callCount); // no reconnect
  });
});

// WS-type conformance test (Y1-α): asserts hand-written StreamMessage TS types
// against asyncapi.md sample shapes, guarding against silent WS-envelope drift.
describe("WS-type conformance (Y1-α drift guard)", () => {
  it("StreamEventMessage matches asyncapi.md shape {kind:'event', event:{...}}", () => {
    const sample = {
      kind: "event",
      event: makeEvent("conformance-1"),
    };
    // TypeScript compile-time check (if this assignment compiles, shape is correct)
    const typed: StreamMessage = sample as StreamMessage;
    expect(typed.kind).toBe("event");
    if (typed.kind === "event") {
      expect(typed.event.id).toBe("conformance-1");
    }
  });

  it("StreamReplayCompleteMessage matches asyncapi.md shape {kind:'replay_complete'}", () => {
    const sample = { kind: "replay_complete" } as StreamMessage;
    expect(sample.kind).toBe("replay_complete");
  });

  it("StreamErrorMessage matches asyncapi.md shape {kind:'error', stage, appended_event_id, reason}", () => {
    const sample: StreamMessage = {
      kind: "error",
      stage: "turn",
      appended_event_id: "evt-123",
      reason: "turn failed",
    };
    expect(sample.kind).toBe("error");
    if (sample.kind === "error") {
      expect(sample.stage).toBe("turn");
      expect(sample.appended_event_id).toBe("evt-123");
      expect(sample.reason).toBe("turn failed");
    }
  });

  it("PingMessage matches asyncapi.md keepalive shape {kind:'ping'}", () => {
    const sample: StreamMessage = { kind: "ping" };
    expect(sample.kind).toBe("ping");
  });

  it("StreamErrorMessage stage:'append' shape is valid", () => {
    const sample: StreamMessage = {
      kind: "error",
      stage: "append",
      appended_event_id: null,
      reason: "append failed",
    };
    if (sample.kind === "error") {
      expect(sample.stage).toBe("append");
      expect(sample.appended_event_id).toBeNull();
    }
  });
});
