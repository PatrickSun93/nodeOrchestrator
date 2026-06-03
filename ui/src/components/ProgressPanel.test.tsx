/**
 * F5 acceptance tests for ProgressPanel (§6.4 pattern 3).
 *
 * Tests:
 *   - Renders snapshot data read-only (event_count, decision_count, participants)
 *   - Pending tool calls shown with humanized name (no mcp__ leak)
 *   - Collapse / expand toggle works
 *   - no-raw-leak: tier names / raw vocab never in DOM
 *   - No action affordances (read-only panel)
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Snapshot } from "../api/client.ts";

vi.mock("../api/client.ts", () => ({
  getSnapshot: vi.fn(),
}));

import * as clientMod from "../api/client.ts";
import { ProgressPanel } from "./ProgressPanel.tsx";

function makeSnapshot(overrides: Partial<Snapshot> = {}): Snapshot {
  return {
    room_id: "r1",
    room_type: "free_chat",
    room_state: "active",
    snapshot_at: 1700000000,
    event_count: 5,
    decision_count: 2,
    open_hypotheses: [],
    closed_decisions: [],
    tool_calls_pending_confirm: [],
    last_state_transition: null,
    participants: ["agent:senior"],
    ...overrides,
  };
}

describe("ProgressPanel (F5 §6.4 pattern 3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders event_count and decision_count from snapshot", async () => {
    vi.mocked(clientMod.getSnapshot).mockResolvedValue(makeSnapshot());
    render(<ProgressPanel roomId="r1" />);
    await waitFor(() => screen.getByTestId("event-count"));
    expect(screen.getByTestId("event-count").textContent).toContain("5");
    expect(screen.getByTestId("decision-count").textContent).toContain("2");
  });

  it("renders participants count", async () => {
    vi.mocked(clientMod.getSnapshot).mockResolvedValue(
      makeSnapshot({ participants: ["agent:senior", "agent:junior"] }),
    );
    render(<ProgressPanel roomId="r1" />);
    await waitFor(() => screen.getByTestId("participants"));
    expect(screen.getByTestId("participants").textContent).toContain("2");
  });

  it("pending tool calls shown with humanized name — no mcp__ leak", async () => {
    vi.mocked(clientMod.getSnapshot).mockResolvedValue(
      makeSnapshot({
        tool_calls_pending_confirm: [
          {
            event_id: "e1",
            tool_name: "mcp__filesystem__apply_edit",
            autonomy_tier: "countdown_confirm",
          },
        ],
      }),
    );
    render(<ProgressPanel roomId="r1" />);
    await waitFor(() => screen.getByTestId("pending-list"));
    const item = screen.getByTestId("pending-item");
    expect(item.textContent).not.toContain("mcp__");
    expect(item.textContent).not.toContain("filesystem");
  });

  it("no pending block when list is empty", async () => {
    vi.mocked(clientMod.getSnapshot).mockResolvedValue(
      makeSnapshot({ tool_calls_pending_confirm: [] }),
    );
    render(<ProgressPanel roomId="r1" />);
    await waitFor(() => screen.getByTestId("event-count"));
    expect(screen.queryByTestId("pending-list")).toBeNull();
  });

  it("collapse hides content; expand restores", async () => {
    vi.mocked(clientMod.getSnapshot).mockResolvedValue(makeSnapshot());
    render(<ProgressPanel roomId="r1" />);
    const collapseBtn = screen.getByTestId("panel-collapse-btn");
    await userEvent.click(collapseBtn);
    expect(screen.queryByTestId("event-count")).toBeNull();
    const expandBtn = screen.getByTestId("panel-expand-btn");
    await userEvent.click(expandBtn);
    await waitFor(() => screen.getByTestId("event-count"));
  });

  it("no-raw-leak: internal vocab never in DOM", async () => {
    vi.mocked(clientMod.getSnapshot).mockResolvedValue(
      makeSnapshot({
        tool_calls_pending_confirm: [
          {
            event_id: "e1",
            tool_name: "countdown_confirm_tool",
            autonomy_tier: "countdown_confirm",
          },
        ],
        participants: ["agent:senior"],
      }),
    );
    render(<ProgressPanel roomId="r1" />);
    await waitFor(() => screen.getByTestId("pending-list"));
    const body = document.body.textContent ?? "";
    expect(body).not.toContain("countdown_confirm");
    expect(body).not.toContain("hard_confirm");
    expect(body).not.toContain("autonomy");
    expect(body).not.toContain("skill");
    expect(body).not.toContain("plugin");
    expect(body).not.toContain("MCP");
  });

  it("panel is read-only — no confirm/cancel buttons", async () => {
    vi.mocked(clientMod.getSnapshot).mockResolvedValue(
      makeSnapshot({
        tool_calls_pending_confirm: [
          { event_id: "e1", tool_name: "apply_edit", autonomy_tier: "hard_confirm" },
        ],
      }),
    );
    render(<ProgressPanel roomId="r1" />);
    await waitFor(() => screen.getByTestId("pending-list"));
    expect(screen.queryByRole("button", { name: /确认/u })).toBeNull();
    expect(screen.queryByRole("button", { name: /取消/u })).toBeNull();
  });
});
