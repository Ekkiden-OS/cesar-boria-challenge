from copy import deepcopy
from decimal import Decimal
from fractions import Fraction

import pytest

from powerplant import DomainValidationError, PlantType, parse_json_payload, parse_payload


def payload(*, load: object = Decimal("1.0"), plants: list[dict] | None = None) -> dict:
    return {
        "load": load,
        "fuels": {
            "gas(euro/MWh)": Decimal("13.4"),
            "kerosine(euro/MWh)": Decimal("50.8"),
            "co2(euro/ton)": Decimal("20"),
            "wind(%)": Decimal("60"),
        },
        "powerplants": plants or [],
    }


def plant(**overrides: object) -> dict:
    result = {
        "name": "plant",
        "type": "gasfired",
        "efficiency": Decimal("0.5"),
        "pmin": Decimal("0"),
        "pmax": Decimal("10"),
    }
    result.update(overrides)
    return result


def test_json_numbers_are_parsed_as_decimals_before_modeling() -> None:
    problem = parse_json_payload(
        b'{"load":0.1,"fuels":{"gas(euro/MWh)":13.4,'
        b'"kerosine(euro/MWh)":50.8,"co2(euro/ton)":20,"wind(%)":60},'
        b'"powerplants":[]}'
    )

    assert problem.load == Decimal("0.1")
    assert problem.load_units == 1
    assert problem.fuels.gas_price == Decimal("13.4")
    assert problem.fuels.co2_price == Decimal("20")


def test_high_precision_literal_is_not_silently_rounded_to_one_tenth() -> None:
    raw = (
        b'{"load":0.10000000000000001,"fuels":{"gas(euro/MWh)":1,'
        b'"kerosine(euro/MWh)":1,"co2(euro/ton)":0,"wind(%)":0},"powerplants":[]}'
    )

    with pytest.raises(DomainValidationError, match="0.1 MW increments"):
        parse_json_payload(raw)


def test_thermal_bounds_are_mapped_to_admissible_tenth_units() -> None:
    problem = parse_payload(payload(plants=[plant(pmin=Decimal("0.11"), pmax=Decimal("0.29"))]))
    modeled = problem.powerplants[0]

    assert modeled.pmin == Decimal("0.11")
    assert modeled.pmax == Decimal("0.29")
    assert modeled.min_units == 2
    assert modeled.max_units == 2


def test_cost_is_an_exact_fraction_and_accounts_for_efficiency() -> None:
    problem = parse_payload(payload(plants=[plant(efficiency=Decimal("0.3"))]))

    assert problem.powerplants[0].marginal_cost == Fraction(134, 3)


@pytest.mark.parametrize(
    ("plant_type", "expected_cost"),
    [
        ("gasfired", Fraction(134, 5)),
        ("turbojet", Fraction(508, 5)),
        ("windturbine", Fraction(0)),
    ],
)
def test_plant_types_select_their_exact_marginal_cost(
    plant_type: str, expected_cost: Fraction
) -> None:
    problem = parse_payload(payload(plants=[plant(type=plant_type)]))

    assert problem.powerplants[0].plant_type is PlantType(plant_type)
    assert problem.powerplants[0].marginal_cost == expected_cost


def test_wind_available_power_is_derived_without_binary_rounding() -> None:
    problem = parse_payload(
        payload(plants=[plant(type="windturbine", pmax=Decimal("4"), pmin=Decimal("0"))])
    )
    wind = problem.powerplants[0]

    assert wind.available_wind_power == Decimal("2.4")
    assert wind.available_wind_units == 24


def test_non_grid_wind_power_remains_exact_but_has_no_tenth_unit_representation() -> None:
    raw = payload(plants=[plant(type="windturbine", pmax=Decimal("0.15"))])
    raw["fuels"]["wind(%)"] = Decimal("100")

    wind = parse_payload(raw).powerplants[0]

    assert wind.available_wind_power == Decimal("0.15")
    assert wind.available_wind_units is None


@pytest.mark.parametrize("invalid", [Decimal("-0.1"), Decimal("0.01")])
def test_load_must_be_non_negative_and_on_the_tenth_grid(invalid: Decimal) -> None:
    with pytest.raises(DomainValidationError):
        parse_payload(payload(load=invalid))


@pytest.mark.parametrize("invalid", [Decimal("0"), Decimal("-0.1")])
def test_efficiency_must_be_positive(invalid: Decimal) -> None:
    with pytest.raises(DomainValidationError, match="efficiency must be greater than zero"):
        parse_payload(payload(plants=[plant(efficiency=invalid)]))


@pytest.mark.parametrize(
    "bounds",
    [
        {"pmin": Decimal("-0.1")},
        {"pmax": Decimal("-0.1")},
        {"pmin": Decimal("2"), "pmax": Decimal("1")},
    ],
)
def test_plant_bounds_must_be_ordered_and_non_negative(bounds: dict) -> None:
    with pytest.raises(DomainValidationError, match="0 <= pmin <= pmax"):
        parse_payload(payload(plants=[plant(**bounds)]))


@pytest.mark.parametrize("invalid", ["nuclear", "gas-fired", None])
def test_unknown_plant_types_are_rejected(invalid: object) -> None:
    with pytest.raises(DomainValidationError, match="type must be one of"):
        parse_payload(payload(plants=[plant(type=invalid)]))


@pytest.mark.parametrize("invalid", [Decimal("-0.1"), Decimal("100.1")])
def test_wind_percentage_must_be_between_zero_and_one_hundred(invalid: Decimal) -> None:
    raw = payload()
    raw["fuels"]["wind(%)"] = invalid

    with pytest.raises(DomainValidationError, match="between 0 and 100"):
        parse_payload(raw)


@pytest.mark.parametrize("invalid", [True, "1.0", None, 1.0, 1])
def test_model_only_accepts_exact_decimal_numbers(invalid: object) -> None:
    with pytest.raises(DomainValidationError, match="must be a JSON number"):
        parse_payload(payload(load=invalid))


def test_non_finite_json_constants_are_rejected() -> None:
    raw = (
        '{"load":NaN,"fuels":{"gas(euro/MWh)":1,"kerosine(euro/MWh)":1,'
        '"co2(euro/ton)":0,"wind(%)":0},"powerplants":[]}'
    )

    with pytest.raises(DomainValidationError, match="finite JSON number"):
        parse_json_payload(raw)


def test_duplicate_plant_names_are_rejected() -> None:
    with pytest.raises(DomainValidationError, match="names must be unique"):
        parse_payload(payload(plants=[plant(), plant()]))


def test_input_data_is_not_mutated() -> None:
    raw = payload(plants=[plant()])
    original = deepcopy(raw)

    parse_payload(raw)

    assert raw == original
