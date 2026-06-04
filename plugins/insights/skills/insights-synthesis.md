---
id: insights-synthesis
category: engineering
applies_to:
  agents: ["*"]
  room_types: [research]
priority: 20
---

# Insights Synthesis

A demonstration skill shipped by the insights plugin bundle (ADR-029 D7).
Guides agents to synthesise findings from an insights database query into
a concise, evidence-backed conclusion.

When synthesising query results:
1. State what was queried and why.
2. Identify the top two or three most relevant findings.
3. Note any gaps or surprising absences in the data.
4. Form a single conclusion sentence that is directly supported by the findings.
