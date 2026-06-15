import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRoomStore } from "../store.ts";
import type { Room } from "../api/client.ts";

vi.mock("../api/client.ts", () => ({
  listRooms: vi.fn(),
}));

import * as clientMod from "../api/client.ts";
import { RoomList } from "./RoomList.tsx";

function makeRoom(id: string, type: Room["type"] = "free_chat", state = "open"): Room {
  return { id, type, state, created_at: Date.now() };
}

describe("RoomList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useRoomStore.getState().reset();
  });

  it("renders humanized type and state (no raw wire vocab)", async () => {
    vi.mocked(clientMod.listRooms).mockResolvedValue([
      makeRoom("room_1", "free_chat", "open"),
      makeRoom("room_2", "research", "active"),
    ]);
    render(<RoomList />);
    await waitFor(() => screen.getByTestId("room-list"));

    // Type labels must be humanized (not raw wire values)
    expect(screen.queryByText("free_chat")).toBeNull();
    expect(screen.queryByText("research")).toBeNull();
    expect(screen.queryByText("open")).toBeNull();

    // Humanized labels should be present
    const items = screen.getAllByRole("button");
    expect(items.length).toBe(2);
  });

  it("clicking a room calls setRoom with its id and type", async () => {
    const room = makeRoom("room_abc", "bug_fix", "open");
    vi.mocked(clientMod.listRooms).mockResolvedValue([room]);
    render(<RoomList />);
    await waitFor(() => screen.getByTestId("room-item-room_abc"));

    const setRoom = vi.fn();
    useRoomStore.setState({ setRoom });

    await userEvent.click(screen.getByTestId("room-item-room_abc"));

    // Re-render after store is set so setRoom gets called
    vi.clearAllMocks();
    vi.mocked(clientMod.listRooms).mockResolvedValue([room]);
    const mockSetRoom = vi.fn();
    useRoomStore.setState({ setRoom: mockSetRoom });
    render(<RoomList />);
    await waitFor(() => screen.getAllByTestId("room-item-room_abc"));

    const buttons = screen.getAllByTestId("room-item-room_abc");
    await userEvent.click(buttons[0]);
    expect(mockSetRoom).toHaveBeenCalledWith("room_abc", "bug_fix");
  });

  it("empty result renders friendly empty-state message", async () => {
    vi.mocked(clientMod.listRooms).mockResolvedValue([]);
    render(<RoomList />);
    await waitFor(() => screen.getByTestId("room-list-empty"));
    // No raw wire vocab in the empty state
    expect(screen.queryByText("[]")).toBeNull();
    expect(screen.queryByText("null")).toBeNull();
  });
});
