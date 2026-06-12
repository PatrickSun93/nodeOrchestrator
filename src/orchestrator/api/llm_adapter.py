"""Thin sync LLM router adapter for run_turn (ADR-025 D3).

Satisfies LLMRouterProtocol (sync def call()) by delegating the routing
decision to select_model_and_provider and provider.call (both async),
running them in a new event loop on the current thread (the writer executor).

Decision-free: this is glue, not a decision surface (HR#1). The routing
choice is made by select_model_and_provider; this adapter only bridges
sync↔async without adding judgment.

No new LLMPurpose — the request's purpose is set by dispatch_turn.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from orchestrator.llm.exceptions import (
    LLMError,
    NoSuitableModelError,
    TransientProviderError,
)
from orchestrator.llm.router import (
    ModelRegistry,
    ProviderRegistry,
    RouteCandidate,
    select_viable_routes,
)
from orchestrator.llm.types import AgentLLMConfig, GlobalLLMOverride, LLMRequest, LLMResponse


class RealLLMRouter:
    """Sync LLMRouterProtocol implementation (ADR-025 D3).

    Runs async routing + provider.call on a new event loop in the calling
    thread (the serialized writer executor). Decision-free — delegates all
    routing to select_model_and_provider.
    """

    def __init__(
        self,
        agent_configs: dict[str, AgentLLMConfig],
        models: ModelRegistry,
        providers: ProviderRegistry,
        override: GlobalLLMOverride | None,
    ) -> None:
        self._agent_configs = agent_configs
        self._models = models
        self._providers = providers
        self._override = override

    def call(self, request: LLMRequest) -> LLMResponse:
        """Route and call synchronously (runs in a thread, not the event loop).

        Opens a new event loop for the async routing + provider call.
        Raises LLMError subclass on routing or provider failure.
        """
        agent_id = request.caller_agent_id
        if agent_id is None:
            raise LLMError("caller_agent_id required for routing")
        agent_config = self._agent_configs.get(agent_id)
        if agent_config is None:
            raise LLMError(f"no LLM config for agent {agent_id!r}")

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._async_call(request, agent_config))
        finally:
            loop.close()

    async def _async_call(self, request: LLMRequest, agent_config: AgentLLMConfig) -> LLMResponse:
        # D-mech-A (ADR-002 D4 call-time half): health-check the whole viable set
        # once up-front, then walk the list on TransientProviderError.
        routes = await select_viable_routes(
            agent_config,
            request,
            self._models,
            self._providers,
            self._override,
        )

        call_trace: list[dict[str, Any]] = []
        for route in routes:
            try:
                return await route.provider.call(
                    request,
                    route.model,
                    model_id_requested=route.model_id_requested,
                )
            except TransientProviderError as exc:
                call_trace.append(
                    dataclasses.asdict(
                        RouteCandidate(
                            model_id=route.model.id,
                            provider_id=route.model.provider,
                            accepted=False,
                            reason=f"call-time transient: {exc}",
                        )
                    )
                )
            # PermanentProviderError propagates — no fallback (ADR-002 D4).

        raise NoSuitableModelError(
            "all viable providers raised TransientProviderError",
            decision_trace=call_trace,
        )
