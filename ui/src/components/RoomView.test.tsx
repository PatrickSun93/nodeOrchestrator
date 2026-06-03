import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRoomStore } from "../store.ts";
import type { Event } from "../api/client.ts";

// ── Mock the API modules ──────────────────────────────────────────────────────
vi.mock("../api/client.ts", () => ({
  postIntent: vi.fn(),
  getRoom: vi.fn(),
  createRoom: vi.fn(),
  getEvents: vi.fn(),
  // ProgressPanel calls getSnapshot on mount — default to null so blocks don't render
  getSnapshot: vi.fn().mockResolvedValue(null),
  getThread: vi.fn(),
}));

vi.mock("../api/stream.ts", () => ({
  connectStream: vi.fn(),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeEvent(id: string, author = "agent:senior", type: Event["type"] = "utterance"): Event {
  return { id, room_id: "r1", type, author, timestamp: Date.now(), content: `Content of ${id}` };
}

async function importMocks() {
  const clientMod = await import("../api/client.ts");
  const streamMod = await import("../api/stream.ts");
  return {
    postIntent: vi.mocked(clientMod.postIntent),
    connectStream: vi.mocked(streamMod.connectStream),
  };
}

// ── Integration: load → replay → send → live render ──────────────────────────
describe("RoomView integration", () => {
  beforeEach(async () => {
    useRoomStore.getState().reset();
    vi.clearAllMocks();
  });

  afterEach(() => {
    useRoomStore.getState().reset();
  });

  it("renders historical events from replay and live events after", async () => {
    const { connectStream } = await importMocks();

    // Capture the callbacks so we can simulate server messages
    let capturedCallbacks: Parameters<typeof connectStream>[1] | null = null;
    connectStream.mockImplementation((_roomId, callbacks) => {
      capturedCallbacks = callbacks;
      // Immediately fire loading
      callbacks.onPhaseChange("loading");
      return () => {};
    });

    // Set up room in store
    act(() => {
      useRoomStore.getState().setRoom("r1", "free_chat");
    });

    // Lazy-import after mocks are set
    const { RoomView } = await import("./RoomView.tsx");
    render(<RoomView />);

    // Simulate server: replay 2 historical events
    act(() => {
      capturedCallbacks!.onEvent(makeEvent("e1", "user", "user_input"));
      capturedCallbacks!.onEvent(makeEvent("e2", "agent:senior", "utterance"));
      capturedCallbacks!.onReplayComplete();
      capturedCallbacks!.onPhaseChange("live");
    });

    await waitFor(() => {
      expect(screen.getAllByTestId("message-item")).toHaveLength(2);
    });

    // Simulate a new live event
    act(() => {
      capturedCallbacks!.onEvent(makeEvent("e3", "agent:senior", "decision"));
    });

    await waitFor(() => {
      expect(screen.getAllByTestId("message-item")).toHaveLength(3);
    });
  });

  it("sends POST /intent on Composer submit", async () => {
    const { connectStream, postIntent } = await importMocks();
    connectStream.mockImplementation((_id, cbs) => {
      cbs.onPhaseChange("loading");
      cbs.onReplayComplete();
      cbs.onPhaseChange("live");
      return () => {};
    });
    postIntent.mockResolvedValue({
      appended_event: makeEvent("e-sent", "user", "user_input"),
      turn: { utterances: [], total_asked: 0, snapshot_failed: false },
    });

    act(() => {
      useRoomStore.getState().setRoom("r1", "free_chat");
    });

    const { RoomView } = await import("./RoomView.tsx");
    render(<RoomView />);

    const textarea = screen.getByTestId("composer-textarea");
    await userEvent.type(textarea, "hello world");
    await userEvent.click(screen.getByTestId("send-button"));

    await waitFor(() => {
      expect(postIntent).toHaveBeenCalledWith("r1", { type: "user_input", content: "hello world" });
    });
  });
});

// ── Discriminating: StreamError stage:turn → reconcile, NOT re-post ───────────
describe("partial-turn correctness (HR#4 discriminating)", () => {
  beforeEach(async () => {
    useRoomStore.getState().reset();
    vi.clearAllMocks();
  });

  afterEach(() => {
    useRoomStore.getState().reset();
  });

  it("StreamError stage:turn → Composer disabled, no re-send offered (not merely 'renders something')", async () => {
    const { connectStream, postIntent } = await importMocks();

    let capturedCallbacks: Parameters<typeof connectStream>[1] | null = null;
    connectStream.mockImplementation((_id, cbs) => {
      capturedCallbacks = cbs;
      cbs.onPhaseChange("loading");
      cbs.onReplayComplete();
      cbs.onPhaseChange("live");
      return () => {};
    });
    postIntent.mockResolvedValue({
      appended_event: makeEvent("e-send", "user", "user_input"),
      turn: { utterances: [], total_asked: 0, snapshot_failed: false },
    });

    act(() => {
      useRoomStore.getState().setRoom("r1", "free_chat");
    });

    const { RoomView } = await import("./RoomView.tsx");
    render(<RoomView />);

    // Type and send a message
    const textarea = screen.getByTestId("composer-textarea");
    await userEvent.type(textarea, "test message");
    await userEvent.click(screen.getByTestId("send-button"));
    await waitFor(() => expect(postIntent).toHaveBeenCalledOnce());

    // Server emits a StreamError stage:turn (intent persisted, turn failed)
    act(() => {
      capturedCallbacks!.onError({
        kind: "error",
        stage: "turn",
        appended_event_id: "e-send",
        reason: "turn failed",
      });
    });

    // Assert: send button is DISABLED (not offering re-send)
    const sendBtn = screen.getByTestId("send-button");
    expect(sendBtn).toBeDisabled();

    // Assert: textarea is also DISABLED (not accepting new input for re-send)
    expect(textarea).toBeDisabled();

    // Assert: turn-error notice is shown
    expect(screen.getByTestId("turn-error-notice")).toBeTruthy();

    // Assert: postIntent was only called ONCE (no re-post happened)
    expect(postIntent).toHaveBeenCalledOnce();
  });

  it("StreamError stage:append → appendError shown, input re-enabled for retry", async () => {
    const { connectStream, postIntent } = await importMocks();

    connectStream.mockImplementation((_id, cbs) => {
      cbs.onPhaseChange("live");
      return () => {};
    });
    // Simulate append-fail: postIntent throws IntentError stage:append
    postIntent.mockRejectedValue({ stage: "append", reason: "append failed" });

    act(() => {
      useRoomStore.getState().setRoom("r1", "free_chat");
    });

    const { RoomView } = await import("./RoomView.tsx");
    render(<RoomView />);

    const textarea = screen.getByTestId("composer-textarea");
    await userEvent.type(textarea, "retry me");
    await userEvent.click(screen.getByTestId("send-button"));

    await waitFor(() => {
      expect(screen.getByTestId("append-error-notice")).toBeTruthy();
    });

    // Textarea should NOT be disabled for append errors (retry is allowed)
    expect(textarea).not.toBeDisabled();
  });
});

// ── Constitutional: no raw vocab in rendered DOM ──────────────────────────────
describe("constitutional: ui_strings no-raw-vocab in rendered DOM", () => {
  beforeEach(async () => {
    useRoomStore.getState().reset();
    vi.clearAllMocks();
  });

  afterEach(() => {
    useRoomStore.getState().reset();
  });

  it("rendered message items contain no raw EventType or RoomType tokens", async () => {
    const { connectStream } = await importMocks();
    let capturedCallbacks: Parameters<typeof connectStream>[1] | null = null;
    connectStream.mockImplementation((_id, cbs) => {
      capturedCallbacks = cbs;
      cbs.onPhaseChange("live");
      return () => {};
    });

    act(() => {
      useRoomStore.getState().setRoom("r1", "free_chat");
    });

    const { RoomView } = await import("./RoomView.tsx");
    const { container } = render(<RoomView />);

    // Render one of each event type to verify no raw token leaks
    const EVENT_TYPES: Event["type"][] = [
      "user_input",
      "utterance",
      "hypothesis",
      "decision",
      "rejection",
      "retraction",
      "observation",
      "tool_call",
      "tool_result",
      "tool_failed",
      "escalation",
      "summary_snapshot",
      "state_transition",
      "milestone",
      "term_definition",
      "decision_pivot",
      "autonomy_decision",
      "autonomy_refusal",
      "external_validation",
    ];

    act(() => {
      EVENT_TYPES.forEach((type, i) => {
        capturedCallbacks!.onEvent({
          id: `evt-${i}`,
          room_id: "r1",
          type,
          author: "agent:senior",
          timestamp: i,
          content: "x",
        });
      });
    });

    await waitFor(() => {
      expect(screen.getAllByTestId("message-item").length).toBe(EVENT_TYPES.length);
    });

    const domText = container.textContent ?? "";
    const RAW_TOKENS = [
      "user_input",
      "utterance",
      "hypothesis",
      "decision",
      "rejection",
      "retraction",
      "observation",
      "tool_call",
      "tool_result",
      "tool_failed",
      "escalation",
      "summary_snapshot",
      "state_transition",
      "milestone",
      "term_definition",
      "decision_pivot",
      "autonomy_decision",
      "autonomy_refusal",
      "external_validation",
      "free_chat",
      "bug_fix",
      "code_review",
      "idea_validation",
    ];
    for (const raw of RAW_TOKENS) {
      expect(domText, `DOM must not contain raw token "${raw}"`).not.toContain(raw);
    }
  });
});
