import type { components } from "./schema.ts";

// Re-export the contract types for the rest of the app
export type Event = components["schemas"]["Event"];
export type Room = components["schemas"]["Room"];
export type RoomType = components["schemas"]["RoomType"];
export type EventType = components["schemas"]["EventType"];
export type Snapshot = components["schemas"]["Snapshot"];
export type ToolCallRef = components["schemas"]["ToolCallRef"];
export type IntentRequest = components["schemas"]["IntentRequest"];
export type IntentResponse = components["schemas"]["IntentResponse"];
export type IntentError = components["schemas"]["IntentError"];
export type ConfirmRequest = components["schemas"]["ConfirmRequest"];
export type ConfirmResponse = components["schemas"]["ConfirmResponse"];
export type ConfirmError = components["schemas"]["ConfirmError"];

const BASE = "";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as unknown;
    if (body !== null && typeof body === "object" && "stage" in body && "reason" in body) {
      throw body as IntentError;
    }
    throw { stage: "append", reason: res.statusText } as IntentError;
  }
  return res.json() as Promise<T>;
}

export function createRoom(type: RoomType): Promise<Room> {
  return request<Room>(`${BASE}/rooms`, {
    method: "POST",
    body: JSON.stringify({ type }),
  });
}

export function getRoom(id: string): Promise<Room> {
  return request<Room>(`${BASE}/rooms/${id}`);
}

export function getEvents(roomId: string): Promise<Event[]> {
  return request<Event[]>(`${BASE}/rooms/${roomId}/events`);
}

export function getSnapshot(roomId: string): Promise<Snapshot> {
  return request<Snapshot>(`${BASE}/rooms/${roomId}/snapshot`);
}

export function getThread(eventId: string): Promise<Event[]> {
  return request<Event[]>(`${BASE}/events/${eventId}/thread`);
}

export function postIntent(
  roomId: string,
  body: { type: "user_input"; content: string },
): Promise<IntentResponse> {
  return request<IntentResponse>(`${BASE}/rooms/${roomId}/intent`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function postConfirm(roomId: string, body: ConfirmRequest): Promise<ConfirmResponse> {
  return request<ConfirmResponse>(`${BASE}/rooms/${roomId}/confirm`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
