"""MCP client package — stdio transport + generic tool-adapter + autonomy-gating.

Leaf consumer: upstream layers (core/autonomy/agents/llm) do NOT import mcp/.
Decision-free: no routing, no tier decisions, no LLM calls (ADR-027 HR#6).
Requires the [mcp] optional extra (the official modelcontextprotocol/python-sdk).
"""
