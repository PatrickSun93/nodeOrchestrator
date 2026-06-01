"""LLM call purpose taxonomy.

Every ``LLMRequest`` carries a ``purpose: LLMPurpose`` field. This
serves two functions:

1. **Audit and PR review.** Every LLM call site is one of these values
   plus (optionally) a caller agent id. PR template Q1 ("why couldn't
   this LLM call be code?") is enforced against this field's call
   sites. Reviewers can grep the codebase by purpose to see all places
   the project relies on LLM judgment.

2. **Test mocking.** ``MockProvider`` keys responses on
   ``(purpose, caller_agent_id)`` so tests can inject role-specific
   replies without intercepting the underlying SDK.

Adding a new purpose is intentional friction: it should require an
explanation in the PR description of why no code path was sufficient.
"""

from __future__ import annotations

from enum import StrEnum


class LLMPurpose(StrEnum):
    """What kind of work an LLM call is doing.

    P1.1 set; subsequent PRs add purposes via ADR.
    """

    # ---- Agent-driven content generation ------------------------------
    # All agent roles share this purpose. ``LLMRequest.caller_agent_id``
    # discriminates which agent (e.g. "agent:prober", "agent:skeptic").
    # Mock responses can key on (AGENT_RESPONSE, caller_agent_id) to
    # provide per-role canned replies.
    AGENT_RESPONSE = "agent_response"

    # ---- Structural LLM uses ------------------------------------------
    # Each below is a load-bearing trade-off: the structural fields of
    # the result are pure code, but free-text fields go through LLM.
    # See handoff.md §6.1 for the snapshot example.

    # Snapshot's free-text fields (current_focus, key_uncertainties,
    # would_pushback_on, needs_user_decision). The structural fields
    # (event_count, cost_so_far, etc.) are pure code.
    SNAPSHOT_SEMANTIC = "snapshot_semantic"

    # Extracting candidate hypotheses from utterances/observations.
    # Output goes to the hypothesis pool — NOT directly to verified
    # knowledge (promotion is human-confirmed per Principle 11).
    HYPOTHESIS_CANDIDATE = "hypothesis_candidate"

    # Marking events as "key node" candidates for human review.
    # Same pool/promotion shape as hypothesis.
    KEY_NODE_CANDIDATE = "key_node_candidate"

    # Interpreting a tool result for the agent's downstream context.
    # E.g., paraphrasing a long search hit so the agent's prompt is
    # shorter on the next turn.
    TOOL_OUTPUT_INTERPRET = "tool_output_interpret"

    # Proposing a definition for a term being repeatedly used. Output
    # goes to the term-definition queue for human approval.
    TERM_DEFINITION_PROPOSAL = "term_definition_proposal"

    # ---- Room re-entry content-gen (P2.5 / ADR-021) -------------------
    # Both render an already-CODE-SELECTED, already-ordered fact-set into
    # natural-language prose. They are content-gen ONLY — the selection /
    # ranking / ordering is pure code (Principle 11); the LLM phrases, it
    # does not choose. Confined to orchestrator/reentry/ (the consumer);
    # the LLM-free-selection AST guard forbids these in the selection fns.

    # Phrasing the assembled re-entry ReentryDigest into a "welcome back,
    # here's what you missed" catch-up. Receives the frozen digest; adds
    # no facts. ADR-021 D4.
    REENTRY_DIGEST_RENDER = "reentry_digest_render"

    # Generating a closed room's ProjectArchive narrative fields
    # (one_line_summary, spinoff_questions) at leave-time from the room's
    # facts, then persisted via record_project_archive. A SECOND, distinct
    # content-gen surface (not REENTRY_DIGEST_RENDER). ADR-021 D5/D9.
    ARCHIVE_SUMMARY_RENDER = "archive_summary_render"
