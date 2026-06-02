import { describe, it, expect } from "vitest";
import { eventTypeLabel, authorLabel, roomTypeLabel, roomStateLabel } from "./uiStrings.ts";
import type { EventType, RoomType } from "./api/client.ts";

// All 19 EventType values from openapi.json
const ALL_EVENT_TYPES: EventType[] = [
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

// All 5 RoomType values from openapi.json
const ALL_ROOM_TYPES: RoomType[] = [
  "free_chat",
  "bug_fix",
  "research",
  "code_review",
  "idea_validation",
];

// Raw internal tokens that must NEVER appear in output (HR#3 不暴露)
const FORBIDDEN_RAW_TOKENS = [
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
  "research",
  "code_review",
  "idea_validation",
  // internal-only vocab that must not leak
  "state machine",
  "autonomy level",
  "dissent dimension",
  "skill",
];

describe("uiStrings — no raw vocab leak (HR#3)", () => {
  it("every EventType maps to a human label ≠ the raw key", () => {
    for (const type of ALL_EVENT_TYPES) {
      const label = eventTypeLabel(type);
      expect(label, `eventTypeLabel("${type}") should not return the raw key`).not.toBe(type);
      expect(label.length, `label for "${type}" should be non-empty`).toBeGreaterThan(0);
    }
  });

  it("every EventType label contains no forbidden raw token", () => {
    for (const type of ALL_EVENT_TYPES) {
      const label = eventTypeLabel(type);
      for (const forbidden of FORBIDDEN_RAW_TOKENS) {
        expect(
          label.toLowerCase(),
          `eventTypeLabel("${type}") = "${label}" must not contain "${forbidden}"`,
        ).not.toContain(forbidden);
      }
    }
  });

  it("every RoomType maps to a human label ≠ the raw key", () => {
    for (const type of ALL_ROOM_TYPES) {
      const label = roomTypeLabel(type);
      expect(label).not.toBe(type);
      expect(label.length).toBeGreaterThan(0);
    }
  });

  it("every RoomType label contains no forbidden raw token", () => {
    for (const type of ALL_ROOM_TYPES) {
      const label = roomTypeLabel(type);
      for (const forbidden of FORBIDDEN_RAW_TOKENS) {
        expect(
          label.toLowerCase(),
          `roomTypeLabel("${type}") must not contain "${forbidden}"`,
        ).not.toContain(forbidden);
      }
    }
  });

  it("authorLabel('user') returns non-raw human term (你 not 'user')", () => {
    expect(authorLabel("user")).not.toBe("user");
    expect(authorLabel("user")).toBe("你");
  });

  it("authorLabel('system') returns non-raw human term", () => {
    expect(authorLabel("system")).not.toBe("system");
  });

  it("authorLabel with known agent id returns human name, not raw agent prefix", () => {
    const label = authorLabel("agent:architect");
    expect(label).not.toContain("agent:");
    expect(label.length).toBeGreaterThan(0);
  });

  it("authorLabel with unknown agent id falls back to safe generic, not raw string", () => {
    const label = authorLabel("agent:unknown-future-agent-xyz");
    expect(label).not.toContain("unknown-future-agent-xyz");
    expect(label).not.toContain("agent:");
    expect(label.length).toBeGreaterThan(0);
  });

  it("authorLabel with totally unknown author falls back to safe generic", () => {
    const label = authorLabel("some_internal_service");
    expect(label).not.toBe("some_internal_service");
    expect(label.length).toBeGreaterThan(0);
  });

  it("roomStateLabel for all known states returns non-raw human term", () => {
    const knownStates = [
      "open",
      "setup",
      "active",
      "closed",
      "reproduced",
      "diagnosed",
      "fix_proposed",
      "exploration",
      "divergence",
      "convergence",
      "snapshot_pending",
      "reviewing",
      "changes_requested",
      "approved",
      "pitching",
      "validating",
      "decided",
    ];
    for (const state of knownStates) {
      const label = roomStateLabel(state);
      expect(label, `roomStateLabel("${state}") should not return the raw key`).not.toBe(state);
      expect(label.length).toBeGreaterThan(0);
    }
  });

  it("roomStateLabel unknown state falls back to safe generic, not the raw token", () => {
    const label = roomStateLabel("unknown_future_state_xyz");
    expect(label).not.toBe("unknown_future_state_xyz");
    expect(label.length).toBeGreaterThan(0);
  });
});
