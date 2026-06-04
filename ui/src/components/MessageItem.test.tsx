/**
 * F3 acceptance tests for MessageItem — type-appropriate rendering of all EventTypes.
 *
 * Tests:
 *   - tool_call/tool_result/tool_failed → 工具活动 affordance with humanized tool name
 *   - tool_call_pending / tool_call_cancelled → 工具活动 affordance
 *   - decision/rejection/retraction/decision_pivot → decision affordance
 *   - system events → system affordance (no author shown)
 *   - no-raw-vocab: mcp__ never in DOM; raw EventType keys never exposed as text
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MessageItem } from "./MessageItem.tsx";
import type { Event, EventType } from "../api/client.ts";

function makeEvent(type: EventType, overrides: Partial<Event> = {}): Event {
  return {
    id: "evt_test",
    room_id: "r1",
    type,
    author: "agent:operator",
    timestamp: 1,
    content: "test content",
    metadata: {},
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tool activity rendering
// ---------------------------------------------------------------------------

describe("MessageItem tool activity affordance (F3)", () => {
  it("tool_call shows 工具活动 affordance with humanized tool name", () => {
    render(
      <MessageItem
        event={makeEvent("tool_call", {
          metadata: { tool_name: "apply_edit", call_id: "c1", params: {} },
        })}
      />,
    );
    const desc = screen.getByTestId("tool-activity-desc");
    expect(desc.textContent).toContain("编辑文件");
    expect(desc.textContent).not.toContain("apply_edit");
  });

  it("tool_call with mcp__ tool strips prefix", () => {
    render(
      <MessageItem
        event={makeEvent("tool_call", {
          metadata: { tool_name: "mcp__filesystem__read_file", call_id: "c1", params: {} },
        })}
      />,
    );
    const desc = screen.getByTestId("tool-activity-desc");
    expect(desc.textContent).not.toContain("mcp__");
  });

  it("tool_result shows affordance", () => {
    render(
      <MessageItem
        event={makeEvent("tool_result", {
          metadata: { call_id: "c1", success: true },
          content: "raw output",
        })}
      />,
    );
    const desc = screen.getByTestId("tool-activity-desc");
    expect(desc.textContent).toContain("结果");
  });

  it("tool_failed shows failure affordance", () => {
    render(
      <MessageItem
        event={makeEvent("tool_failed", {
          metadata: { call_id: "c1" },
        })}
      />,
    );
    const desc = screen.getByTestId("tool-activity-desc");
    expect(desc.textContent).toContain("失败");
  });

  it("tool_call_pending shows 等待确认 affordance", () => {
    render(
      <MessageItem
        event={makeEvent("tool_call_pending", {
          metadata: {
            tool_name: "apply_edit",
            call_id: "c1",
            tier: "countdown_confirm",
            initiating_agent: "operator",
          },
        })}
      />,
    );
    const desc = screen.getByTestId("tool-activity-desc");
    expect(desc.textContent).toContain("等待确认");
    // tier is NOT exposed as text
    expect(desc.textContent).not.toContain("countdown_confirm");
  });

  it("tool_call_cancelled shows 已取消 affordance", () => {
    render(
      <MessageItem
        event={makeEvent("tool_call_cancelled", {
          metadata: { call_id: "c1" },
        })}
      />,
    );
    const desc = screen.getByTestId("tool-activity-desc");
    expect(desc.textContent).toContain("已取消");
  });
});

// ---------------------------------------------------------------------------
// Decision-class affordance
// ---------------------------------------------------------------------------

describe("MessageItem decision affordance (F3)", () => {
  it("decision renders type chip as 决定", () => {
    render(<MessageItem event={makeEvent("decision")} />);
    const chip = screen.getByText("决定");
    expect(chip).toBeTruthy();
  });

  it("rejection renders type chip as 拒绝", () => {
    render(<MessageItem event={makeEvent("rejection")} />);
    expect(screen.getByText("拒绝")).toBeTruthy();
  });

  it("retraction renders type chip as 撤回", () => {
    render(<MessageItem event={makeEvent("retraction")} />);
    expect(screen.getByText("撤回")).toBeTruthy();
  });

  it("decision_pivot renders type chip as 决策转向", () => {
    render(<MessageItem event={makeEvent("decision_pivot")} />);
    expect(screen.getByText("决策转向")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// System affordance (no author shown for system events)
// ---------------------------------------------------------------------------

describe("MessageItem system affordance (F3)", () => {
  it("state_transition renders type chip as 状态更新", () => {
    render(
      <MessageItem
        event={makeEvent("state_transition", {
          author: "system",
          metadata: { new_state: "convergence", prior_state: "exploration" },
        })}
      />,
    );
    expect(screen.getByText("状态更新")).toBeTruthy();
  });

  it("autonomy_refusal renders type chip as 拒绝执行 (read-only, no action)", () => {
    render(
      <MessageItem
        event={makeEvent("autonomy_refusal", {
          metadata: {
            operation_tool_id: "evil",
            operation_initiating_agent: "op",
            user_explicit_intent: false,
            refusal_reason: "unknown_tool",
          },
        })}
      />,
    );
    expect(screen.getByText("拒绝执行")).toBeTruthy();
    // No button affordance (read-only)
    expect(screen.queryByRole("button")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// no-raw-vocab: exhaustive across all 21 event types
// ---------------------------------------------------------------------------

describe("MessageItem no-raw-vocab (F3)", () => {
  const RAW_VOCAB = [
    "mcp__",
    "countdown_confirm",
    "hard_confirm",
    "auto_execute",
    "skill",
    "plugin",
    "MCP",
    "autonomy_level",
    // Raw EventType keys that must not surface as-is
    "user_input",
    "tool_call_pending",
    "tool_call_cancelled",
    "autonomy_decision",
    "autonomy_refusal",
    "external_validation",
    "summary_snapshot",
    "state_transition",
    "term_definition",
    "decision_pivot",
  ];

  const ALL_TYPES: EventType[] = [
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
    "tool_call_pending",
    "tool_call_cancelled",
  ];

  ALL_TYPES.forEach((type) => {
    it(`no raw vocab in ${type} event render`, () => {
      const { unmount } = render(
        <MessageItem
          event={makeEvent(type, {
            metadata: {
              // Provide common metadata fields so validation doesn't fail
              tool_name: "apply_edit",
              call_id: "c1",
              tier: "countdown_confirm",
              initiating_agent: "operator",
              operation_tool_id: "apply_edit",
              operation_initiating_agent: "operator",
              user_explicit_intent: false,
              score: 5,
              reversibility_score: 5,
              threshold_auto_raw: 8,
              threshold_confirm_raw: 4,
              user_intent_modifier: 0,
              threshold_auto_effective: 8,
              threshold_confirm_effective: 4,
              rule: "score_between_confirm_and_auto",
              refusal_reason: "unknown_tool",
              new_state: "exploration",
              prior_state: "setup",
            },
          })}
        />,
      );
      const bodyText = document.body.textContent ?? "";
      for (const vocab of RAW_VOCAB) {
        expect(bodyText, `${type}: raw vocab "${vocab}" must not appear`).not.toContain(vocab);
      }
      unmount();
    });
  });
});
