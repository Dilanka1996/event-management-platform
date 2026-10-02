"""Deterministic tests for the loop's 'ask the user' attention reporting.

A dead-end (no free room, denial, busy room) must surface a real, human-readable
message to the caller — not just a trace line that claims "ask the user".
"""

from agent.gate import ApprovalGate
from agent.loop import AgentLoop, Plan
from agent.scenarios import FakeApi


def _agent(api, approvals, budget=8):
    return AgentLoop(
        api,
        ApprovalGate(lambda _p: approvals.pop(0) if approvals else False),
        budget=budget,
    )


_PLAN = Plan("create_session", {
    "event_id": 1, "intent": "45-min design review", "title": "Design Review",
    "start": "2025-03-11T13:00:00+00:00", "end": "2025-03-11T13:45:00+00:00",
    "minutes": 45,
})


def test_no_free_room_reports_attention():
    api = FakeApi(free=())  # nothing free
    res = _agent(api, [True]).run([_PLAN])
    assert res["skipped"] == ["create_session"]
    assert len(res["attention"]) == 1
    assert "No room is free" in res["attention"][0]


def test_denied_write_reports_cancellation():
    api = FakeApi()
    res = _agent(api, [False]).run([_PLAN])  # user says "no"
    assert res["attention"] and "Cancelled" in res["attention"][0]
    # Nothing was actually committed.
    assert not any(c.startswith("create_session:") and not dr for c, dr in api.calls)


def test_attention_does_not_accumulate_across_runs():
    """The loop is reused per REPL turn; per-run state must reset."""
    api = FakeApi(free=())
    loop = _agent(api, [True, True])
    first = loop.run([_PLAN])
    second = loop.run([_PLAN])
    assert len(first["attention"]) == 1
    assert len(second["attention"]) == 1, "attention leaked from the previous run"
    assert len(second["completed"]) == 0 and second["skipped"] == ["create_session"]


def test_successful_run_has_no_attention():
    api = FakeApi()
    res = _agent(api, [True]).run([_PLAN])
    assert res["attention"] == []
    assert res["status"] == "ok"
