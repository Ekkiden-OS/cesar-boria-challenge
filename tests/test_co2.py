import json
from decimal import Decimal
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from powerplant import optimize, parse_payload


def payload(*, co2_price: str = "10") -> dict:
    return {
        "load": Decimal("1"),
        "fuels": {
            "gas(euro/MWh)": Decimal("4"),
            "kerosine(euro/MWh)": Decimal("10"),
            "co2(euro/ton)": Decimal(co2_price),
            "wind(%)": Decimal("100"),
        },
        "powerplants": [
            {
                "name": "gas",
                "type": "gasfired",
                "efficiency": Decimal("0.5"),
                "pmin": Decimal("0"),
                "pmax": Decimal("1"),
            },
            {
                "name": "jet",
                "type": "turbojet",
                "efficiency": Decimal("1"),
                "pmin": Decimal("0"),
                "pmax": Decimal("1"),
            },
            {
                "name": "wind",
                "type": "windturbine",
                "efficiency": Decimal("1"),
                "pmin": Decimal("0"),
                "pmax": Decimal("0"),
            },
        ],
    }


def costs(problem) -> dict[str, Fraction]:
    return {plant.name: plant.marginal_cost for plant in problem.powerplants}


def output_map(plan: list[dict[str, str | float]]) -> dict[str, Decimal]:
    return {row["name"]: Decimal(str(row["p"])) for row in plan}


def test_co2_disabled_preserves_the_previous_costs_and_plan() -> None:
    implicit_default = parse_payload(payload())
    explicit_disabled = parse_payload(payload(), include_co2=False)

    assert costs(implicit_default) == costs(explicit_disabled)
    assert optimize(implicit_default) == optimize(explicit_disabled)
    assert costs(implicit_default)["gas"] == Fraction(8)


def test_co2_enabled_adds_exact_gas_emission_cost() -> None:
    problem = parse_payload(payload(), include_co2=True)

    assert costs(problem)["gas"] == Fraction(11)


def test_zero_co2_price_is_identical_when_feature_is_enabled() -> None:
    disabled = parse_payload(payload(co2_price="0"), include_co2=False)
    enabled = parse_payload(payload(co2_price="0"), include_co2=True)

    assert costs(enabled) == costs(disabled)
    assert optimize(enabled) == optimize(disabled)


def test_co2_does_not_affect_turbojet_or_wind() -> None:
    disabled = costs(parse_payload(payload(), include_co2=False))
    enabled = costs(parse_payload(payload(), include_co2=True))

    assert enabled["jet"] == disabled["jet"] == Fraction(10)
    assert enabled["wind"] == disabled["wind"] == Fraction(0)


def test_enabling_co2_changes_the_economically_preferred_plant() -> None:
    without_co2 = output_map(optimize(parse_payload(payload(), include_co2=False)))
    with_co2 = output_map(optimize(parse_payload(payload(), include_co2=True)))

    assert without_co2["gas"] == Decimal("1.0")
    assert with_co2["jet"] == Decimal("1.0")


def test_environment_is_read_per_request_without_leaking_between_requests(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_body = json.loads(json.dumps(payload(), default=float))

    monkeypatch.delenv("INCLUDE_CO2", raising=False)
    before = output_map(api.post("/productionplan", json=request_body).json())

    monkeypatch.setenv("INCLUDE_CO2", "true")
    enabled = output_map(api.post("/productionplan", json=request_body).json())

    monkeypatch.delenv("INCLUDE_CO2")
    after = output_map(api.post("/productionplan", json=request_body).json())

    assert before["gas"] == Decimal("1.0")
    assert enabled["jet"] == Decimal("1.0")
    assert after == before
