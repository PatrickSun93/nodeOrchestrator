"""Principal model — the per-request authenticated identity (ADR-039 D1).

P4.5-2: the resolved identity that both session-cookie and bearer-token
auth paths resolve to. Frozen; carried by the auth middleware into every
handler via request.state.principal.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    """Authenticated per-request identity (ADR-039 D1).

    user_id: the users-table PK, constrained to [a-zA-Z0-9_-]+.
             Used to stamp author="user:<user_id>" server-side (D7).
    """

    user_id: str
