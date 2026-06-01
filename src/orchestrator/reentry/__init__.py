"""Room re-entry / 离开-回来追平 consumer package.

Composes memory/ readers + derived/ + llm/ into the "AI 记得我" experience.
Placement: outside memory/ (no-LLM rule); imports memory/ + derived/ + llm/.
No upstream layer (core/ memory/ derived/ llm/) may import this package.
Per ADR-021 D1.
"""
