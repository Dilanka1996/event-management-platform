"""The approval gate.

This lives in code, OUTSIDE the model. Reads run freely; writes require
approval; destructive actions require a stronger confirmation. The model
cannot talk its way past it: the loop calls `gate.check(...)` before every
write, and a rejection is a normal control-flow path (the agent replans or
asks).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Risk(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


@dataclass
class Decision:
    allowed: bool
    reason: str = ""


class ApprovalGate:
    """A pluggable approval source.

    `approval_fn(prompt) -> bool` is the human (or, in evals, a scripted
    responder). The gate itself is deterministic policy; the responder only
    answers yes/no to a shown prompt.
    """

    def __init__(self, approval_fn):
        self.approval_fn = approval_fn

    def classify(self, action: str) -> Risk:
        if action in {"create_session", "invite", "create_invitations"}:
            return Risk.WRITE
        if action in {"delete_event", "add_member"}:
            return Risk.DESTRUCTIVE
        return Risk.READ

    def check(self, action: str, preview: str) -> Decision:
        """Show what will ACTUALLY be sent, and require approval for writes."""
        risk = self.classify(action)
        if risk is Risk.READ:
            return Decision(allowed=True, reason="reads run freely")

        label = "DESTRUCTIVE" if risk is Risk.DESTRUCTIVE else "write"
        prompt = f"[{label}] {preview}\nApprove? (y/n): "
        approved = bool(self.approval_fn(prompt))
        if not approved:
            return Decision(allowed=False, reason="approval denied by user")
        if risk is Risk.DESTRUCTIVE and action == "delete_event":
            # Destructive needs more than a shrug: a second explicit confirm.
            confirm = self.approval_fn(
                f"[DESTRUCTIVE] Confirm PERMANENTLY deleting: {preview}\nType 'yes': "
            )
            if not confirm:
                return Decision(allowed=False, reason="destructive confirm denied")
        return Decision(allowed=True, reason="approved")
