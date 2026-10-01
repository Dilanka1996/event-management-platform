"""Runs the ~15 agent scenarios and asserts they pass, reporting the rate."""

from agent.scenarios import SCENARIOS, run_all


def test_all_scenarios_pass(capsys):
    rate = run_all(verbose=True)
    out = capsys.readouterr().out
    # Surface the report in pytest output.
    print(out)
    assert rate >= 0.8, f"agent scenario pass rate too low: {rate:.0%}\n{out}"


def test_expected_scenario_count():
    assert len(SCENARIOS) >= 15
