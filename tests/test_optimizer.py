import json
from decimal import Decimal
from pathlib import Path

import pytest

import powerplant.optimizer as optimizer_module
from powerplant import (
    InfeasibleError,
    ResourceLimitError,
    optimize,
    parse_json_payload,
    parse_payload,
)

ROOT = Path(__file__).parents[1]


def load_fixture(name: str):
    return parse_json_payload((ROOT / "example_payloads" / name).read_bytes())


@pytest.mark.parametrize(
    ("filename", "expected_load"),
    [("payload1.json", 480), ("payload2.json", 480), ("payload3.json", 910)],
)
def test_official_payloads_have_exact_plans(filename: str, expected_load: int) -> None:
    plan = optimize(load_fixture(filename))

    assert sum(Decimal(str(item["p"])) for item in plan) == Decimal(expected_load)
    assert all((Decimal(str(item["p"])) * 10) % 1 == 0 for item in plan)
    assert len(plan) == 6
    if filename == "payload3.json":
        expected = json.loads((ROOT / "example_payloads" / "response3.json").read_text())
        assert plan == expected


def test_minimum_output_can_require_backing_off_a_cheaper_plant() -> None:
    problem = parse_payload(
        {
            "load": Decimal("1.2"),
            "fuels": {
                "gas(euro/MWh)": Decimal("1"),
                "kerosine(euro/MWh)": Decimal("10"),
                "co2(euro/ton)": Decimal("0"),
                "wind(%)": Decimal("0"),
            },
            "powerplants": [
                {
                    "name": "cheap",
                    "type": "gasfired",
                    "efficiency": Decimal("1"),
                    "pmin": Decimal("0"),
                    "pmax": Decimal("1"),
                },
                {
                    "name": "fixed",
                    "type": "turbojet",
                    "efficiency": Decimal("1"),
                    "pmin": Decimal("0.6"),
                    "pmax": Decimal("0.6"),
                },
            ],
        }
    )

    assert optimize(problem) == [
        {"name": "cheap", "p": 0.6},
        {"name": "fixed", "p": 0.6},
    ]


def test_infeasible_load_is_reported() -> None:
    problem = parse_payload(
        {
            "load": Decimal("0.5"),
            "fuels": {
                "gas(euro/MWh)": Decimal("1"),
                "kerosine(euro/MWh)": Decimal("1"),
                "co2(euro/ton)": Decimal("0"),
                "wind(%)": Decimal("0"),
            },
            "powerplants": [
                {
                    "name": "large-minimum",
                    "type": "gasfired",
                    "efficiency": Decimal("1"),
                    "pmin": Decimal("1"),
                    "pmax": Decimal("2"),
                }
            ],
        }
    )

    with pytest.raises(InfeasibleError, match="satisfy the load exactly"):
        optimize(problem)


def test_resource_limit_is_checked_before_optimizer_structures_are_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = parse_payload(
        {
            "load": Decimal("20000.1"),
            "fuels": {
                "gas(euro/MWh)": Decimal("1"),
                "kerosine(euro/MWh)": Decimal("1"),
                "co2(euro/ton)": Decimal("0"),
                "wind(%)": Decimal("0"),
            },
            "powerplants": [],
        }
    )
    core_called = False

    def fail_if_called(_problem):
        nonlocal core_called
        core_called = True
        raise AssertionError("optimizer core must not run")

    monkeypatch.setattr(optimizer_module, "_optimize_within_limits", fail_if_called)

    with pytest.raises(ResourceLimitError, match="load exceeds supported limit"):
        optimizer_module.optimize(problem)
    assert not core_called
