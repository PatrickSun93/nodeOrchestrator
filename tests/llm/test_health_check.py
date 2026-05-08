"""Tests for check_all_providers."""

from __future__ import annotations

from orchestrator.llm.health_check import ProviderHealth, check_all_providers
from orchestrator.llm.providers.mock import MockProvider
from orchestrator.llm.router import ProviderRegistry
from orchestrator.llm.types import ProviderId


class TestCheckAllProviders:
    def test_empty_registry_returns_empty(self) -> None:
        registry = ProviderRegistry({})
        assert check_all_providers(registry) == []

    def test_healthy_provider_reported(self) -> None:
        provider = MockProvider(provider_id=ProviderId("p"), healthy=True)
        registry = ProviderRegistry({ProviderId("p"): provider})

        results = check_all_providers(registry)
        assert len(results) == 1
        assert results[0].provider_id == ProviderId("p")
        assert results[0].healthy is True
        assert results[0].error is None
        assert results[0].checked_at_ms > 0

    def test_unhealthy_provider_reported(self) -> None:
        provider = MockProvider(provider_id=ProviderId("p"), healthy=False)
        registry = ProviderRegistry({ProviderId("p"): provider})

        results = check_all_providers(registry)
        assert len(results) == 1
        assert results[0].healthy is False
        # No exception raised, just returned False — error stays None.
        assert results[0].error is None

    def test_provider_exception_captured_as_error(self) -> None:
        class BadProvider:
            provider_id = ProviderId("bad")

            def can_use_orchestrator_tools(self) -> bool:
                return True

            def health_check(self) -> bool:
                raise RuntimeError("kaboom")

            async def call(self, request: object, model: object) -> object:
                raise NotImplementedError

        registry = ProviderRegistry({ProviderId("bad"): BadProvider()})  # type: ignore[dict-item]

        results = check_all_providers(registry)
        assert len(results) == 1
        assert results[0].healthy is False
        assert results[0].error is not None
        assert "RuntimeError" in results[0].error
        assert "kaboom" in results[0].error

    def test_multiple_providers_all_checked(self) -> None:
        p1 = MockProvider(provider_id=ProviderId("a"), healthy=True)
        p2 = MockProvider(provider_id=ProviderId("b"), healthy=False)
        p3 = MockProvider(provider_id=ProviderId("c"), healthy=True)
        registry = ProviderRegistry(
            {
                ProviderId("a"): p1,
                ProviderId("b"): p2,
                ProviderId("c"): p3,
            }
        )

        results = check_all_providers(registry)
        assert len(results) == 3
        by_id = {r.provider_id: r for r in results}
        assert by_id[ProviderId("a")].healthy is True
        assert by_id[ProviderId("b")].healthy is False
        assert by_id[ProviderId("c")].healthy is True

    def test_does_not_raise_on_provider_failure(self) -> None:
        """Per the docstring contract: this function never raises.
        A misbehaving provider produces a result entry, not an exception."""

        class ExplodingProvider:
            provider_id = ProviderId("boom")

            def can_use_orchestrator_tools(self) -> bool:
                return True

            def health_check(self) -> bool:
                raise SystemError("hardware fault")

            async def call(self, request: object, model: object) -> object:
                raise NotImplementedError

        ok = MockProvider(provider_id=ProviderId("ok"), healthy=True)
        registry = ProviderRegistry(
            {
                ProviderId("boom"): ExplodingProvider(),  # type: ignore[dict-item]
                ProviderId("ok"): ok,
            }
        )
        # Must not raise — must return both entries.
        results = check_all_providers(registry)
        assert len(results) == 2

    def test_provider_health_dataclass_frozen(self) -> None:
        ph = ProviderHealth(
            provider_id=ProviderId("x"),
            healthy=True,
            error=None,
            checked_at_ms=12345,  # type: ignore[arg-type]
        )
        # @dataclass(frozen=True) — attribute reassignment must fail
        import dataclasses

        with __import__("pytest").raises(dataclasses.FrozenInstanceError):
            ph.healthy = False  # type: ignore[misc]
