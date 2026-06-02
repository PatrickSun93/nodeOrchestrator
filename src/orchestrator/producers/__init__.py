"""Tagging and other producers that feed the dormant promotion rules.

Per ADR-022 D1: producers live outside memory/ (the no-LLM rglob is
preserved). They are leaf consumers — they import memory/core/llm but
nothing in core/memory/derived/llm/ may import them.
"""
