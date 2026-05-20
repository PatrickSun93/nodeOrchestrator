"""Hard Guards: a sibling layer to the autonomy scorer.

Hard Guards is the P1.3 refusal layer that runs before (or alongside)
the P1.2 scorer. It operates on binary triggers — not continuous scores.

Dimensions handled here (not in the scorer):
- Per ADR-005 Decision 1: cost_impact, blast_radius, destructive,
  and external_visibility relocated from the original 6-dimension
  design to this layer, expressed as binary triggers.

Key design point (ADR-005 Decision 5):
- Hard Guards reads the raw reversibility score, not the effective
  threshold. This preserves Hard Guards' authority to refuse
  user-cooperative destructive requests regardless of user_intent_modifier.

No implementation in P1.2. Placeholder reserved for P1.3.
"""
