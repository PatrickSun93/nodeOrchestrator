# ADR-023: LLM Layer-4 Global Override + Alt-Backend Trust Boundary + Startup-Error Contract

**Status:** Proposed — 2026-06-02 (senior-drafted per P2.7 brief; awaiting architect accept)

**Scope:** P2.7 — the P2 closing slice's LLM-layer + startup decisions. Governs **(S2)** the LLM **Layer-4 global cost/quality override** — a deterministic, config-driven transform over the existing code router (`llm/router.py` + a new global-override config), **(S3)** the **Claude Code alt-backend** (`ANTHROPIC_BASE_URL`) trust boundary — opt-in + allowlist-validated (`providers/claude_code_cli.py` + provider config), and **(S4)** the **friendly startup-error contract** + the pinned boot entry (`src/orchestrator/bootstrap.py` + `llm/exceptions.py`). Companion amendments: **ADR-002** (registers Layer-4 as the 4th config layer) and **ADR-012** (S1 — scaffold RoomType transition tables; a separate concern, its own amendment). Does NOT govern: an LLM-driven model chooser (**forbidden** — routing is code); a backend marketplace/auto-discovery (just the `ANTHROPIC_BASE_URL` mechanism + the trust posture); multi-source trust-weighting; P3 work.

## Context

P2.6 closed; the LLM layer ships as **3 layers** (providers / models / agents — ADR-002) with a **pure-code router** (`select_model_and_provider`, `router.py:109-246`, module docstring line 15: *"This module contains zero LLM calls. Routing is decision-path code."*). The router walks the effective chain `[default_model, *fallback_chain]` and returns the first candidate passing required-capability + provider-exists + tools-support + health filters; it raises `NoSuitableModelError` (carrying a `decision_trace`) when the chain is exhausted. `ANTHROPIC_BASE_URL`/`base_url` plumbing exists in `providers/openai_compatible.py` (a `base_url: str` field interpolated into the endpoint) but **not** in `providers/claude_code_cli.py` (which shells out to the `claude` binary with no endpoint control). There is **no `main.py`/CLI/boot entry** in `src/orchestrator/` (only `__init__.py`); the load→validate→health sequence is exercised only by tests.

P2.7 adds three LLM-layer/startup concerns, each with a constitutional or security edge:

- **S2 is a routing decision.** Choosing *which model* for a cost/quality goal is exactly "routing/gating/scoring/model-selection" — pinned as **code** by `llm-layer.md:11-14` and forbidden as LLM judgment by CLAUDE.md ("never LLM-judge a routing decision") + Principle 5/11. The `LLMPurpose` taxonomy has **no** routing/judgment purpose (verified through P2.6 — all values content-gen). So Layer-4 must be a **declarative config knob → deterministic code transform**, never an LLM "picking the best model."
- **S3 is a trust boundary.** Pointing Claude Code at a non-Anthropic backend means conversation content + tool calls + an API key flow to a third-party server. The dev-harness r0b proxy is a *local-trusted* precedent; an arbitrary `ANTHROPIC_BASE_URL` is a **higher trust tier**.
- **S4 is cross-cutting polish.** The new config S2/S3 introduce (override knobs, alt-backend allowlist) needs the *same* fail-loud-at-startup discipline ADR-002 D5 established — and friendly, actionable messages.

Hard requirements:

1. **Routing is code** (Principle 5; `llm-layer.md:11-14`; CLAUDE.md): S2's override is a deterministic code rule; **no LLM call in the model-selection path**; **no new routing/judgment `LLMPurpose`**.
2. **Determinism**: the override is a pure function `(override_config, available_models) → candidate_chain`; discriminating tests (RC-25); a **structural test** proving the override path makes no `LLMProvider.call` (RC-24 real-AST/spy, not substring).
3. **Layer-3 composition**: the override transforms the candidate chain *before* the router walks it; it never bypasses the router's capability/provider/tools/health filters (ADR-002 D4 unchanged).
4. **Security (S3)**: opt-in (unset `base_url` = Anthropic default); **fail-closed allowlist** (a set `base_url` not in the trusted list raises at startup); credentials via the existing `api_key_env` env-var indirection (never inline).
5. **Fail-loud at startup** (ADR-002 D5): boot validation accumulates violations; S4 renders them actionably.
6. **Closed-ADR discipline**: ADR-002/ADR-012 changed only via the architect-accepted amendments appended to those files (RC-23-safe; no literal `Status:`-value substring in amendment prose).

---

## Decisions

### S2 — LLM Layer-4 global cost/quality override (the constitutional crux, c1)

#### D1. Layer-4 is a global, optional, declarative config — `config/llm_override.yaml`

A new **optional** config file `config/llm_override.yaml` carries the global override. **Absent file = no override = default routing unchanged** (ADR-002 behavior preserved; test-coverage §3 cleanup). It parses into a frozen + `extra="forbid"` Pydantic model (senior fork — minimal two-knob shape; extensible later):

```python
class GlobalLLMOverride(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    quality_tier: Literal["economy", "balanced", "premium"] | None = None
    cost_ceiling_per_1m_output: float | None = Field(default=None, ge=0.0)
```

This is a **global** knob (one per deployment), distinct from the per-agent `AgentLLMConfig` (ADR-002 layer-3). It is the **4th layer** (ADR-002 amendment): provider ← model ← agent ← **global override**. It sits *above* the agent layer because it is a deployment-wide operational dial (cost governance / quality posture), not a per-agent property.

#### D2. The override is a PURE chain transform applied before the router walks the chain

A pure function — the c1 chokepoint the brief names `(override_config, available_models) → selected_model`, realized here as a **chain transform** (so it composes cleanly with the existing fallback walk rather than short-circuiting it):

```python
def apply_global_override(
    chain: list[ModelId],
    override: GlobalLLMOverride | None,
    models: ModelRegistry,
) -> list[ModelId]:
    """Pure function. Deterministically filters + reorders the candidate
    chain per the global override. Zero LLM calls, zero I/O.
    None override (or absent file) => returns chain unchanged."""
```

Two **independent, deterministic** operations over **static `ModelProfile` attributes** (no inference):

- **Filter** by `cost_ceiling_per_1m_output`: drop any candidate whose `ModelProfile.cost_per_1m_output` is *known and strictly greater* than the ceiling. A candidate with `cost_per_1m_output is None` (unknown cost) is **kept** — the ceiling cannot be evaluated, so the override does not silently drop it (documented; the alternative — fail-closed on unknown cost — is rejected as surprising for a cost dial).
- **Reorder** by `quality_tier`, a **stable sort** by a tier-specific key over static attributes: `economy` → ascending `cost_per_1m_output` (None-cost sorts last); `premium` → descending `len(capabilities)` then original order (prefer the most-capable available); `balanced` / `None` → identity (no reorder). Stable so equal keys preserve the author's `[default_model, *fallback_chain]` intent.

**Composition with Layer-3 (ADR-002 D4):** the transformed `effective_chain` is fed into the **existing** `select_model_and_provider` loop, which still applies `required_capabilities` + provider-exists + tools-support + `health_check` per candidate, unchanged. The override **never** bypasses those filters — it only pre-filters/reorders *which* candidates the router considers and *in what order*. Integration site: `router.py:164-166` (chain construction) gains `effective_chain = apply_global_override(chain, override, models)`; `select_model_and_provider` gains an `override: GlobalLLMOverride | None = None` parameter (default `None` ⇒ no behavior change for existing callers/tests).

**Empty-chain outcome:** if the override filters out *every* candidate (e.g. a ceiling below all models' cost), the router raises `NoSuitableModelError` with its existing `decision_trace` — extended to record that the global override filtered the chain (so S4 can render *"all models exceed cost_ceiling X; raise the ceiling or remove it"*). The override is **fail-loud**, never a silent fallback to an unfiltered chain.

#### D3. The c1 guarantee — structural no-LLM-in-selection + no routing purpose

Two enforcements make "the override is code, not LLM judgment" structural, not conventional:

- **Structural test** `test_constitution_override_path_makes_no_llm_call` (real, RC-24): a **spy provider** records `.call(...)` invocations; the test drives `apply_global_override` + `select_model_and_provider` across every `quality_tier`/`cost_ceiling` combination and asserts the spy's `call` count is **0** (selection consults only `health_check()` — a sync probe, not an LLM call). Belt-and-suspenders: an **AST guard** that `apply_global_override`'s module references no provider `.call`. This extends the router's existing zero-LLM-calls posture (`router.py:15`) to the new override surface.
- **No new `LLMPurpose`**: the override adds **zero** `LLMPurpose` values (the taxonomy stays content-gen-only; verified through P2.6). There is no inference surface to misuse — the override is a list transform over static config.

---

### S3 — Claude Code alt-backend (`ANTHROPIC_BASE_URL`) trust boundary (security, c2)

#### D4. `base_url` opt-in on the Claude Code provider, plumbed via subprocess env

`providers/claude_code_cli.py` gains an optional field `base_url: str | None = None`. When set, the provider passes `ANTHROPIC_BASE_URL=<base_url>` in the subprocess environment of the `claude` invocation (the CLI honors that env var to redirect its endpoint). **Unset (`None`) = the default Anthropic endpoint** — existing behavior unchanged (test-coverage §3 cleanup). This mirrors the *intent* of `openai_compatible.py`'s `base_url` field, adapted to the subprocess (env-var) rather than HTTP-client construction.

#### D5. Fail-closed allowlist — only explicitly-trusted base_urls

The architect ruled S3 = **opt-in + allowlist validation (only trusted base_url)**. The provider config (the `claude_code_cli` entry in `llm_providers.yaml` `params`) carries, alongside `base_url`, an explicit `trusted_base_urls: list[str]` (senior fork — co-located with the opt-in so the trust grant is declared right next to the redirect it authorizes). Validation at provider construction / config load:

- `base_url` **unset** → no validation, Anthropic default (opt-out is the safe default).
- `base_url` **set and ∈ `trusted_base_urls`** → allowed.
- `base_url` **set and ∉ `trusted_base_urls`** (including an absent/empty allowlist) → **`ConfigError`** at startup (boundary validator, test-coverage §5). **Fail-closed**: the user must *explicitly* list the URL to authorize the redirect — opt-in-with-responsibility, not implicit trust.

#### D6. Credentials + what-flows; the trust tier is explicit

The alt-backend API key uses the **existing `api_key_env` env-var indirection** (the key is never inline in yaml; the provider reads it from the named env var). The ADR records explicitly **what flows to a set `base_url`**: conversation content + tool-call payloads + the API key. The allowlist (D5) is the single trust gate. This is documented as a **higher trust tier** than the dev-harness r0b proxy (which is *local-trusted*, role-rewriting only) — the two must not be conflated. An LLM-in-connector / response-crafting-attack hardening (a malicious backend returning adversarial content) is a **forward hook**, not P2.7 scope; the allowlist is the P2.7 defense.

---

### S4 — friendly startup-error contract + pinned boot entry

#### D7. Boot entry — `src/orchestrator/bootstrap.py` (the pinned startup home)

Since `src/orchestrator/` has no `main.py`, P2.7 pins the boot/validation home at a new **`src/orchestrator/bootstrap.py`** (top-level — startup is cross-cutting across llm + future room/agent loading; senior fork over an llm-scoped `llm/bootstrap.py`). It exposes a single sequence function (shape pinned at impl):

```python
def load_and_validate_llm_layer(config_dir: Path) -> LLMLayer:
    """Sequence: load_providers -> load_models -> load_agent_llm_config
    -> load global override (S2) -> validate_full_config -> check_all_providers.
    On any ConfigError / health failure, raise StartupError with a rendered,
    actionable message (D8). Fail-loud (ADR-002 D5)."""
```

It is the single place a future CLI/web entry calls to bring the LLM layer up; it composes (does not duplicate) the existing `config_loader` + `health_check` functions.

#### D8. Friendly error rendering — `StartupError` + `render_startup_error`

A new `StartupError(LLMError)` wraps the rendered message; `render_startup_error(exc) -> str` turns the structured failures into a **multi-line, actionable** message: *what* failed, *which file/field*, *how to fix*. It renders each of: `ConfigError` (its `.violations` list — file + field + reason), `NoSuitableModelError` (its `.decision_trace` — per-candidate rejection reasons, **including the new global-override filter reason from D2**), and provider **health** failures (from `check_all_providers`, which returns `ProviderHealth` with an `error` string, never raising). Tests assert **message content** (test-coverage §4, load-bearing for S4) — e.g. an over-tight `cost_ceiling` renders the ceiling + the dropped models; an un-allowlisted `base_url` (D5) renders the URL + the `trusted_base_urls` field to add it to. S4 is **sequenced last** (see plan §3) because its rendering must cover the *new* S2 (override) + S3 (allowlist) failure modes.

---

## Considered alternatives

- **(S2) LLM-driven model chooser** — ask an LLM "which model is best for this cost/quality goal?" **Rejected, constitutionally** (Principle 5; CLAUDE.md "never LLM-judge a routing decision"; `llm-layer.md:11-14`). Model selection is routing; routing is code. There is no `LLMPurpose` for it and none is added.
- **(S2) Override as a hard post-selection swap** — let the override pick the final model directly, bypassing the router's capability/health walk. **Rejected**: it would let a cost dial select an unhealthy or capability-missing model, duplicating (and contradicting) the router's Layer-3 filters. The chain-transform (D2) composes with Layer-3 instead of bypassing it.
- **(S2) Override on `AgentLLMConfig` (per-agent)** — **Rejected**: cost/quality posture is a *deployment-wide* dial; per-agent override already exists (the agent's own `default_model`/`fallback_chain`). Layer-4 is the global knob ADR-002 lacked.
- **(S3) Free-form `base_url` (no allowlist)** — **Rejected** by the architect's c2 ruling: a third-party endpoint is a trust boundary; fail-closed allowlist (D5) is the opt-in-with-responsibility gate.
- **(S3) Schema-tighten `base_url` to an allowlisted `Literal`** — **Rejected**: the trusted set is deployment-specific (operational config, not code); a config-level `trusted_base_urls` list is the right granularity (ADR-002 C "yaml for operational knobs").
- **(S4) Boot logic inline in a future `main.py`** — **Rejected for now**: there is no `main.py`; pinning `bootstrap.py` gives the startup sequence a testable home today and a single call site for whatever entry lands later.

## Consequences

**Easier:** a deployment-wide cost ceiling / quality tier is one optional yaml file (S2); pointing Claude Code at a trusted alternate backend is two config lines + an allowlist entry (S3); startup failures read as actionable fixes, not stack traces (S4); the boot sequence has one testable home (S4).

**Harder:** the override adds a 4th layer to reason about (ADR-002 amendment documents it); `trusted_base_urls` is one more config field to maintain (S3); `render_startup_error` must be kept in sync as new config (S2/S3) adds failure modes — hence S4-last.

**Neutral:** the override's `quality_tier` reorder rules are a senior fork (economy/balanced/premium) — extensible without re-litigating the constitutional boundary (any new tier is still a deterministic static-attribute sort). The `bootstrap.py` vs `llm/bootstrap.py` placement is a senior fork; both are compatible with this ADR's contracts.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| S2 D1 — global override config (4th layer) | **Low** — absent file = no override; removing the layer is deleting an optional parse path + the `override=None` default param (no caller change). |
| S2 D2 — pure chain transform | **Low** — the transform is one pure function at one integration site; reverting is removing the `apply_global_override` call. |
| S2 D3 — structural no-LLM guarantee | **Trivial** — adding/removing a test; the constraint itself is constitutional (don't reverse). |
| S3 D4 — `base_url` opt-in | **Low** — a nullable field + env plumbing; unset preserves default. |
| S3 D5 — fail-closed allowlist | **Medium** — relaxing to free-form is a validator change, but reverses the architect's security ruling; don't without a security re-decision. |
| S4 D7/D8 — boot entry + error contract | **Low** — `bootstrap.py` composes existing loaders; reverting is inlining at the eventual entry. |

## References

- `docs/process/architect-briefs/P2.7.md` (the four sub-items + the c1/c2 crux + the parallelism graph).
- `docs/process/senior-plans/P2.7.md` (this ADR's plan; §3 slice/workflow recommendation).
- `docs/architecture/llm-layer.md:11-14` (routing/model-selection = code; "the LLM never makes architectural choices") — the S2 basis.
- ADR-002 (three-layer config) — **amended by P2.7** to register Layer-4 (the global override) as the 4th layer.
- ADR-012 (room state machine) — **amended by P2.7-S1** (separate concern: scaffold RoomType transition tables).
- ADR-003 (why Claude Code can't have orchestrator tools) — the alt-backend (S3) does not change the tools posture.
- `src/orchestrator/llm/{router.py:109-246, config_loader.py, types.py, exceptions.py, health_check.py}` + `providers/{claude_code_cli.py, openai_compatible.py}` (verified `origin/main` substrate).
- CLAUDE.md ("never LLM-judge a routing decision"); Principle 5/11.
