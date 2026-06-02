import { describe, it, expect, vi, beforeEach } from "vitest";
import type { IntentError, Room, Event } from "./client.ts";

// We test the client by mocking fetch (the global is allowed in src/api/).
// This verifies the typed contract surface: correct endpoints, method, error shape.

async function importClient() {
  const mod = await import("./client.ts");
  return mod;
}

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: `HTTP ${status}`,
    json: () => Promise.resolve(body),
  } as Response);
}

describe("API client", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("createRoom calls POST /rooms and returns the room", async () => {
    const room: Room = { id: "r1", type: "free_chat", state: "open" };
    vi.stubGlobal("fetch", mockFetch(201, room));
    const { createRoom } = await importClient();
    const result = await createRoom("free_chat");
    expect(result).toEqual(room);
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe("/rooms");
    expect((vi.mocked(fetch).mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });

  it("getEvents calls GET /rooms/{id}/events", async () => {
    vi.stubGlobal("fetch", mockFetch(200, []));
    const { getEvents } = await importClient();
    await getEvents("r1");
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe("/rooms/r1/events");
  });

  it("postIntent returns IntentResponse on success", async () => {
    const evt: Event = {
      id: "e1",
      room_id: "r1",
      type: "user_input",
      author: "user",
      timestamp: 1,
      content: "hi",
    };
    const resp = {
      appended_event: evt,
      turn: { utterances: [], total_asked: 0, snapshot_failed: false },
    };
    vi.stubGlobal("fetch", mockFetch(200, resp));
    const { postIntent } = await importClient();
    const result = await postIntent("r1", { type: "user_input", content: "hi" });
    expect(result.appended_event.id).toBe("e1");
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe("/rooms/r1/intent");
    expect((vi.mocked(fetch).mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });

  it("postIntent throws IntentError with stage on 422", async () => {
    const err: IntentError = { stage: "append", reason: "bad type", appended_event_id: null };
    vi.stubGlobal("fetch", mockFetch(422, err));
    const { postIntent } = await importClient();
    await expect(postIntent("r1", { type: "user_input", content: "x" })).rejects.toMatchObject({
      stage: "append",
      reason: "bad type",
    });
  });

  it("postIntent throws IntentError with stage:turn on 500", async () => {
    const err: IntentError = { stage: "turn", reason: "turn failed", appended_event_id: "e2" };
    vi.stubGlobal("fetch", mockFetch(500, err));
    const { postIntent } = await importClient();
    await expect(postIntent("r1", { type: "user_input", content: "x" })).rejects.toMatchObject({
      stage: "turn",
    });
  });

  it("IntentError.stage discriminates append vs turn", async () => {
    const appendErr: IntentError = { stage: "append", reason: "r", appended_event_id: null };
    vi.stubGlobal("fetch", mockFetch(422, appendErr));
    const { postIntent } = await importClient();
    let caughtStage: string | null = null;
    try {
      await postIntent("r1", { type: "user_input", content: "x" });
    } catch (e) {
      caughtStage = (e as IntentError).stage;
    }
    expect(caughtStage).toBe("append");
  });
});
