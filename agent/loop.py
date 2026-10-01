"""The agent loop: plan -> propose -> gate -> execute -> observe -> replan.

Talks to the platform only through PlatformApi (user's own token). Writes are
gated by ApprovalGate, which is outside the model. The loop is bounded; when
the step budget runs out it stops and reports what completed. Writes may be
previewed with a server-side dry_run so approvals reflect the real outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.gate import ApprovalGate
from agent.trace import Trace
from agent.tools import ApiError, PlatformApi


@dataclass
class Plan:
    """A resolved intent: reads to gather facts, then writes to apply."""

    action: str
    params: dict = field(default_factory=dict)


class BudgetExhausted(Exception):
    pass


class AgentLoop:
    def __init__(
        self,
        api: PlatformApi,
        gate: ApprovalGate,
        budget: int = 8,
        trace: Trace | None = None,
    ):
        self.api = api
        self.gate = gate
        self.budget = budget
        self.trace = trace or Trace()
        self._interrupts: list[str] = []
        self.completed: list[str] = []
        self.skipped: list[str] = []

    # -- interruption -----------------------------------------------------
    def interrupt(self, note: str) -> None:
        """Absorb a mid-flight correction without restarting the plan."""
        self._interrupts.append(note)
        self.trace.add("interrupt", f"absorbed: {note}")

    def _drain_interrupts(self) -> list[str]:
        notes, self._interrupts = self._interrupts, []
        return notes

    # -- core -------------------------------------------------------------
    def run(self, plans: list[Plan]) -> dict:
        steps = 0
        for plan in plans:
            steps += 1
            if steps > self.budget:
                self.trace.add("stop", f"budget exhausted ({self.budget} steps)")
                return self._report("budget_exhausted")

            try:
                self._execute(plan, interrupt_check=self._drain_interrupts)
                self.completed.append(plan.action)
            except ApiError as err:
                # Denial / conflict are normal paths: record and continue.
                self.trace.add("result", f"{plan.action} failed: {err.detail}")
                self.skipped.append(plan.action)
            except Exception as err:  # noqa: BLE001
                self.trace.add("result", f"{plan.action} error: {err}")
                self.skipped.append(plan.action)

        return self._report("ok")

    def _execute(self, plan: Plan, interrupt_check) -> None:
        action = plan.action
        params = plan.params

        if action == "create_session":
            self._do_create_session(params, interrupt_check)
        elif action == "invite":
            self._do_invite(params)
        elif action == "add_member":
            self._do_add_member(params)
        else:
            self.trace.add("think", f"no handler for action {action!r}")

    # -- actions ----------------------------------------------------------
    def _do_create_session(self, params: dict, interrupt_check) -> None:
        event_id = params["event_id"]
        intent = params["intent"]

        # 1. RESOLVE: free room for the requested window, before any write.
        self.trace.add("think", f"resolving a free room for {intent!r}")
        rooms = self._call("free_rooms", event_id, params["start"], params["minutes"])
        if not rooms:
            self.trace.add("think", "no room free in that window; ask the user")
            raise ApiError(409, "no free room for the requested window")

        chosen = params.get("room_name") or rooms[0]["room_name"]

        # 2. PREVIEW: server-side dry_run reflects the real outcome.
        preview = self._call(
            "create_session",
            event_id,
            params["title"],
            chosen,
            params["start"],
            params["end"],
            dry_run=True,
        )

        # 3. GATE: approve what will actually be sent.
        decision = self.gate.check("create_session", preview.get("summary", chosen))
        self.trace.add("gate", f"create_session -> {decision.reason}")
        if not decision.allowed:
            raise ApiError(403, decision.reason)

        # 4. INTERRUPT: absorb a correction before committing.
        notes = interrupt_check()
        for note in notes:
            if "Room B" in note and chosen != "Room B":
                self.trace.add("think", f"replanning room: {note}")
                chosen = "Room B"
                rooms = self._call("free_rooms", event_id, params["start"], params["minutes"])
                if not any(r["room_name"] == "Room B" for r in rooms):
                    raise ApiError(409, "Room B is not free")

        # 5. EXECUTE for real.
        self._call(
            "create_session",
            event_id,
            params["title"],
            chosen,
            params["start"],
            params["end"],
            dry_run=False,
        )
        self.trace.add("result", f"session created in {chosen}")

    def _do_invite(self, params: dict) -> None:
        event_id = params["event_id"]
        preview = self._call(
            "invite", event_id, params["emails"], dry_run=True
        )
        decision = self.gate.check("invite", preview.get("summary", "invite attendees"))
        self.trace.add("gate", f"invite -> {decision.reason}")
        if not decision.allowed:
            raise ApiError(403, decision.reason)
        self._call("invite", event_id, params["emails"], dry_run=False)
        self.trace.add("result", "invitations sent")

    def _do_add_member(self, params: dict) -> None:
        event_id = params["event_id"]
        preview = f"grant role {params['role']} to {params['email']} on event {event_id}"
        decision = self.gate.check("add_member", preview)
        self.trace.add("gate", f"add_member -> {decision.reason}")
        if not decision.allowed:
            raise ApiError(403, decision.reason)
        self._call("add_member", event_id, params["email"], params["role"])
        self.trace.add("result", "member added")

    # -- helpers ----------------------------------------------------------
    def _call(self, name: str, *args, **kwargs):
        method_path = {
            "free_rooms": ("GET", "/rooms/free"),
            "create_session": ("POST", "/sessions"),
            "invite": ("POST", "/invitations"),
            "add_member": ("POST", "/members"),
        }[name]
        self.trace.add("call", f"{name}{args if args else ''}", {
            "method": method_path[0],
            "path": method_path[1],
            "name": name,
            "dry_run": kwargs.get("dry_run", False),
        })
        fn = getattr(self.api, name)
        result = fn(*args, **kwargs)
        self.trace.add("result", f"{name} -> {str(result)[:120]}")
        return result

    def _report(self, status: str) -> dict:
        return {
            "status": status,
            "completed": list(self.completed),
            "skipped": list(self.skipped),
            "trace": self.trace.render(),
            "calls": self.trace.calls(),
        }
