"""Container syscall/egress sandbox (ADR-037).

Downstream leaf: imported only by api/ + subprocess_trust / net_trust.
Provides the sandbox mechanism (runtime detection, isolation profile, egress constraint,
sandboxed spawn, posture resolver) that retires R1-R4/R7/R8 residuals.
"""
