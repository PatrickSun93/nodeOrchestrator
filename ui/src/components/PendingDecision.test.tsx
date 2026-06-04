/**
 * F2 acceptance tests for PendingDecisionList (ADR-030 D6 / B3 acceptance).
 *
 * Tests:
 *   - Displays pending tool name humanized (no mcp__ leak)
 *   - no-raw-vocab: tier / countdown_confirm / hard_confirm / mcp__ / "skill" / "plugin" never in DOM
 *   - no-forge: confirm request carries only {pending_event_id, decision}
 *   - Renders nothing when pendingCalls is empty
 *   - approve / cancel buttons call correct hook path
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRoomStore } from "../store.ts";
import { PendingDecisionList } from "./PendingDecision.tsx";
import type { PendingCall } from "../store.ts";

// ---------------------------------------------------------------------------
// Mock useConfirm to capture calls without fetch
// ---------------------------------------------------------------------------

const mockConfirm = vi.fn().mockResolvedValue(null);
vi.mock("../hooks/useConfirm.ts", () => ({
  useConfirm: () => ({
    status: "idle",
    error: null,
    confirm: mockConfirm,
  }),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function seedPending(
  eventId: string,
  callId: string,
  toolName: string,
  tier: PendingCall["autonomy_tier"] = "countdown_confirm",
) {
  const { pendingCalls } = useRoomStore.getState();
  const newMap = new Map(pendingCalls);
  newMap.set(eventId, {
    event_id: eventId,
    tool_name: toolName,
    autonomy_tier: tier,
    call_id: callId,
  });
  useRoomStore.setState({ roomId: "room_test", pendingCalls: newMap });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PendingDecisionList (F2)", () => {
  beforeEach(() => {
    useRoomStore.getState().reset();
    useRoomStore.setState({ roomId: "room_test" });
    mockConfirm.mockClear();
  });

  it("renders nothing when pendingCalls is empty", () => {
    render(<PendingDecisionList />);
    expect(screen.queryByTestId("pending-decision-list")).toBeNull();
  });

  it("renders pending card with humanized tool name", () => {
    seedPending("p1", "call_abc", "apply_edit");
    render(<PendingDecisionList />);
    const toolName = screen.getByTestId("pending-tool-name");
    // humanized: "编辑文件" — not "apply_edit"
    expect(toolName.textContent).toBe(" 编辑文件");
    expect(toolName.textContent).not.toContain("apply_edit");
  });

  it("no-raw-vocab: tier tokens never in DOM text", () => {
    seedPending("p1", "call_abc", "apply_edit", "countdown_confirm");
    seedPending("p2", "call_def", "apply_edit", "hard_confirm");
    render(<PendingDecisionList />);
    const bodyText = document.body.textContent ?? "";
    // D-C: tier names must NEVER surface
    expect(bodyText).not.toContain("countdown_confirm");
    expect(bodyText).not.toContain("hard_confirm");
    expect(bodyText).not.toContain("auto_execute");
    expect(bodyText).not.toContain("autonomy");
    expect(bodyText).not.toContain("skill");
    expect(bodyText).not.toContain("plugin");
    expect(bodyText).not.toContain("MCP");
    expect(bodyText).not.toContain("mcp__");
  });

  it("no-raw-vocab: mcp__ prefix stripped from tool name display", () => {
    seedPending("p1", "call_mcp", "mcp__filesystem__apply_edit");
    render(<PendingDecisionList />);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).not.toContain("mcp__");
  });

  it("approve button calls confirm with {roomId, event_id, 'approve'} — no-forge", async () => {
    seedPending("p1", "call_abc", "apply_edit");
    render(<PendingDecisionList />);
    const approveBtn = screen.getByTestId("confirm-approve-btn");
    await userEvent.click(approveBtn);
    expect(mockConfirm).toHaveBeenCalledWith("room_test", "p1", "approve");
    // Ensure only event_id + decision are passed (no tool_name/params)
    const [, eventId, decision] = mockConfirm.mock.calls[0] as [string, string, string];
    expect(eventId).toBe("p1");
    expect(decision).toBe("approve");
  });

  it("cancel button calls confirm with 'cancel'", async () => {
    seedPending("p1", "call_abc", "apply_edit");
    render(<PendingDecisionList />);
    const cancelBtn = screen.getByTestId("confirm-cancel-btn");
    await userEvent.click(cancelBtn);
    expect(mockConfirm).toHaveBeenCalledWith("room_test", "p1", "cancel");
  });

  it("renders one card per pending call", () => {
    seedPending("p1", "call_1", "apply_edit");
    seedPending("p2", "call_2", "read_file");
    render(<PendingDecisionList />);
    const cards = screen.getAllByTestId("pending-decision-card");
    expect(cards).toHaveLength(2);
  });
});
