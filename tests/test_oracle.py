import random
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from itertools import product

import pytest

from powerplant import InfeasibleError, PlantType, ProductionProblem, optimize, parse_payload

ORACLE_CASES = 150


@dataclass(frozen=True)
class ExhaustiveResult:
    cost: Fraction
    outputs: tuple[int, ...]


def exhaustive_optimum(problem: ProductionProblem) -> ExhaustiveResult | None:
    """Enumerate the Cartesian product of every plant's output choices."""
    choices: list[tuple[int, ...]] = []
    for plant in problem.powerplants:
        if plant.plant_type is PlantType.WIND_TURBINE:
            wind = plant.available_wind_units
            if wind is not None and wind > 0 and plant.min_units <= wind <= plant.max_units:
                choices.append((0, wind))
            else:
                choices.append((0,))
            continue

        positive = tuple(range(max(1, plant.min_units), plant.max_units + 1))
        choices.append((0, *positive))

    best: ExhaustiveResult | None = None
    for outputs in product(*choices):
        if sum(outputs) != problem.load_units:
            continue
        cost = sum(
            (plant.marginal_cost * Fraction(output, 10))
            for plant, output in zip(problem.powerplants, outputs, strict=True)
        )
        if best is None or cost < best.cost:
            best = ExhaustiveResult(cost=cost, outputs=outputs)
    return best


def make_problem(
    load_units: int,
    plants: list[dict],
    *,
    gas_price: str = "1",
    kerosine_price: str = "4",
    wind_percent: str = "0",
) -> ProductionProblem:
    return parse_payload(
        {
            "load": Decimal(load_units) / 10,
            "fuels": {
                "gas(euro/MWh)": Decimal(gas_price),
                "kerosine(euro/MWh)": Decimal(kerosine_price),
                "co2(euro/ton)": Decimal("0"),
                "wind(%)": Decimal(wind_percent),
            },
            "powerplants": plants,
        }
    )


def plant(
    name: str,
    *,
    kind: str = "gasfired",
    efficiency: str = "1",
    minimum: int = 0,
    maximum: int = 10,
) -> dict:
    return {
        "name": name,
        "type": kind,
        "efficiency": Decimal(efficiency),
        "pmin": Decimal(minimum) / 10,
        "pmax": Decimal(maximum) / 10,
    }


def as_output_map(plan: list[dict[str, str | float]]) -> dict[str, Decimal]:
    return {row["name"]: Decimal(str(row["p"])) for row in plan}


def plan_cost(problem: ProductionProblem, plan: list[dict[str, str | float]]) -> Fraction:
    cost_by_name = {item.name: item.marginal_cost for item in problem.powerplants}
    return sum(cost_by_name[str(row["name"])] * Fraction(Decimal(str(row["p"]))) for row in plan)


def test_zero_load_keeps_every_plant_off() -> None:
    problem = make_problem(0, [plant("thermal", minimum=5), plant("wind", kind="windturbine")])

    assert as_output_map(optimize(problem)) == {
        "wind": Decimal("0.0"),
        "thermal": Decimal("0.0"),
    }


def test_capacity_exactly_equal_to_load_uses_all_available_capacity() -> None:
    problem = make_problem(10, [plant("a", maximum=4), plant("b", maximum=6)])

    assert as_output_map(optimize(problem)) == {"a": Decimal("0.4"), "b": Decimal("0.6")}


def test_insufficient_total_capacity_is_infeasible() -> None:
    problem = make_problem(10, [plant("a", maximum=4), plant("b", maximum=5)])

    with pytest.raises(InfeasibleError):
        optimize(problem)


def test_equal_minimum_and_maximum_is_a_fixed_output_when_on() -> None:
    problem = make_problem(7, [plant("fixed", minimum=7, maximum=7)])

    assert optimize(problem) == [{"name": "fixed", "p": 0.7}]


def test_minimum_output_creates_a_feasibility_gap() -> None:
    problem = make_problem(5, [plant("gapped", minimum=6, maximum=10)])

    with pytest.raises(InfeasibleError):
        optimize(problem)


def test_lower_marginal_cost_is_selected() -> None:
    problem = make_problem(
        10,
        [plant("expensive", kind="turbojet"), plant("cheap")],
        gas_price="2",
        kerosine_price="9",
    )

    assert as_output_map(optimize(problem)) == {
        "cheap": Decimal("1.0"),
        "expensive": Decimal("0.0"),
    }


def test_equal_cost_tie_prefers_more_output_from_the_earlier_plant() -> None:
    problem = make_problem(10, [plant("first"), plant("second")])

    assert optimize(problem) == [
        {"name": "first", "p": 1.0},
        {"name": "second", "p": 0.0},
    ]


def test_negative_price_plant_is_preferred() -> None:
    problem = make_problem(
        10,
        [plant("positive", kind="turbojet"), plant("negative")],
        gas_price="-2",
        kerosine_price="1",
    )

    assert as_output_map(optimize(problem))["negative"] == Decimal("1.0")


def test_wind_is_all_or_nothing() -> None:
    problem = make_problem(
        5,
        [plant("wind", kind="windturbine", maximum=10), plant("gas", maximum=10)],
        wind_percent="40",
    )

    assert as_output_map(optimize(problem)) == {
        "wind": Decimal("0.4"),
        "gas": Decimal("0.1"),
    }


def test_non_grid_wind_output_cannot_be_dispatched() -> None:
    problem = make_problem(
        2,
        [plant("wind", kind="windturbine", maximum=3), plant("gas", maximum=2)],
        wind_percent="50",
    )

    assert problem.powerplants[0].available_wind_power == Decimal("0.15")
    assert problem.powerplants[0].available_wind_units is None
    assert as_output_map(optimize(problem))["gas"] == Decimal("0.2")


def test_greedy_fill_of_cheapest_plant_would_block_the_feasible_optimum() -> None:
    problem = make_problem(
        12,
        [
            plant("cheap", maximum=10),
            plant("fixed-expensive", kind="turbojet", minimum=6, maximum=6),
        ],
        gas_price="1",
        kerosine_price="10",
    )

    assert as_output_map(optimize(problem)) == {
        "cheap": Decimal("0.6"),
        "fixed-expensive": Decimal("0.6"),
    }


def test_seeded_small_problems_match_independent_exhaustive_oracle() -> None:
    rng = random.Random(20260924)

    for case in range(ORACLE_CASES):
        plants = []
        for index in range(rng.randint(0, 4)):
            maximum = rng.randint(0, 8)
            plants.append(
                plant(
                    f"p{index}",
                    kind=rng.choice(["gasfired", "turbojet", "windturbine"]),
                    efficiency=rng.choice(["0.5", "0.8", "1"]),
                    minimum=rng.randint(0, maximum),
                    maximum=maximum,
                )
            )

        problem = make_problem(
            rng.randint(0, 16),
            plants,
            gas_price=rng.choice(["-2", "0", "1", "3"]),
            kerosine_price=rng.choice(["-1", "0", "2", "5"]),
            wind_percent=rng.choice(["0", "50", "100"]),
        )
        expected = exhaustive_optimum(problem)

        if expected is None:
            with pytest.raises(InfeasibleError, match="satisfy the load exactly"):
                optimize(problem)
        else:
            actual = optimize(problem)
            assert sum(Decimal(str(row["p"])) for row in actual) == problem.load, case
            assert plan_cost(problem, actual) == expected.cost, case
