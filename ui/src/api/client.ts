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

// Plugin management types (ADR-038 D5 / P4.7-BE — not in openapi.json, hand-typed)
export interface PluginInfo {
  plugin_id: string;
  enabled: boolean;
  version: string | null;
  provenance: string;
  provenance_kind: string | null;
  fetched: boolean;
}

export interface PluginWriteResponse {
  effect: "next_restart";
}

export interface AdmitRequest {
  source_url: string;
  digest: string;
  version?: string | null;
}

// Auth types (ADR-039 D3 / P4.7-BE)
export interface LoginResponse {
  user_id: string;
}

export class AuthError extends Error {
  constructor() {
    super("Unauthorized");
    this.name = "AuthError";
  }
}

const BASE = "";

// Global 401 callback — set by App on mount so any API call can redirect to login.
let _on401: (() => void) | null = null;
export function set401Handler(handler: (() => void) | null): void {
  _on401 = handler;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    ...init,
  });
  if (res.status === 401) {
    _on401?.();
    throw new AuthError();
  }
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

// Plugin management API (ADR-038 D5 / P4.7-BE)

export function getPlugins(): Promise<PluginInfo[]> {
  return request<PluginInfo[]>(`${BASE}/plugins`);
}

export function enablePlugin(pluginId: string): Promise<PluginWriteResponse> {
  return request<PluginWriteResponse>(`${BASE}/plugins/${encodeURIComponent(pluginId)}/enable`, {
    method: "POST",
  });
}

export function disablePlugin(pluginId: string): Promise<PluginWriteResponse> {
  return request<PluginWriteResponse>(`${BASE}/plugins/${encodeURIComponent(pluginId)}/disable`, {
    method: "POST",
  });
}

export function admitPlugin(pluginId: string, body: AdmitRequest): Promise<PluginWriteResponse> {
  return request<PluginWriteResponse>(`${BASE}/plugins/${encodeURIComponent(pluginId)}/admit`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deletePlugin(pluginId: string): Promise<PluginWriteResponse> {
  return request<PluginWriteResponse>(`${BASE}/plugins/${encodeURIComponent(pluginId)}`, {
    method: "DELETE",
  });
}

// Auth API (ADR-039 D3 / P4.7-BE)

export function login(userId: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>(`${BASE}/login`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, password }),
  });
}

export function logout(): Promise<{ status: string }> {
  return request<{ status: string }>(`${BASE}/logout`, { method: "POST" });
}

// Auth probe: calls GET /rooms/{fake-id} — returns true if authenticated (404), false if 401.
export async function probeAuth(): Promise<boolean> {
  try {
    await request<unknown>(`${BASE}/rooms/__auth_probe__`);
    return true;
  } catch (err) {
    if (err instanceof AuthError) return false;
    return true; // 404 or other = authenticated
  }
}
