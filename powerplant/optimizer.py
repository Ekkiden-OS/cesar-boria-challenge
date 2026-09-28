from collections import deque
from dataclasses import dataclass
from fractions import Fraction

from powerplant.model import PlantType, PowerPlant, ProductionProblem

MAX_LOAD_UNITS = 200_000
MAX_STATE_CELLS = 2_000_000


class InfeasibleError(ValueError):
    """Raised when no combination of plant outputs can meet the load exactly."""


class ResourceLimitError(ValueError):
    """Raised before optimization when a valid problem exceeds the safe work envelope."""


@dataclass(frozen=True)
class _State:
    cost: Fraction
    outputs: tuple[int, ...]


@dataclass(frozen=True)
class _WindowCandidate:
    previous_total: int
    adjusted_cost: Fraction
    state: _State


def optimize(problem: ProductionProblem) -> list[dict[str, str | float]]:
    """Find an exact minimum-cost plan with dynamic programming."""
    _enforce_resource_limits(problem)
    return _optimize_within_limits(problem)


def _enforce_resource_limits(problem: ProductionProblem) -> None:
    if problem.load_units > MAX_LOAD_UNITS:
        raise ResourceLimitError(f"load exceeds supported limit of {MAX_LOAD_UNITS} tenths of MW")

    potential_cells = (problem.load_units + 1) * len(problem.powerplants)
    if potential_cells > MAX_STATE_CELLS:
        raise ResourceLimitError(
            f"potential state-space exceeds supported limit of {MAX_STATE_CELLS} cells"
        )


def _optimize_within_limits(problem: ProductionProblem) -> list[dict[str, str | float]]:
    plants = tuple(
        plant
        for _, plant in sorted(
            enumerate(problem.powerplants),
            key=lambda item: (item[1].marginal_cost, item[0]),
        )
    )
    states: dict[int, _State] = {0: _State(cost=Fraction(0), outputs=())}

    for plant in plants:
        if plant.plant_type is PlantType.WIND_TURBINE:
            states = _transition_wind(states, plant, problem.load_units)
        else:
            states = _transition_thermal(states, plant, problem.load_units)

    solution = states.get(problem.load_units)
    if solution is None:
        raise InfeasibleError("no production plan can satisfy the load exactly")

    return [
        {"name": plant.name, "p": output / 10}
        for plant, output in zip(plants, solution.outputs, strict=True)
    ]


def _transition_wind(
    states: dict[int, _State], plant: PowerPlant, load_units: int
) -> dict[int, _State]:
    next_states: dict[int, _State] = {}
    available = plant.available_wind_units
    can_run = (
        available is not None and available > 0 and plant.min_units <= available <= plant.max_units
    )

    for accumulated, state in states.items():
        outputs = (0, available) if can_run and accumulated + available <= load_units else (0,)
        for output in outputs:
            total = accumulated + output
            candidate = _State(
                cost=state.cost + plant.marginal_cost * Fraction(output, 10),
                outputs=(*state.outputs, output),
            )
            current = next_states.get(total)
            if current is None or _is_better(candidate, current):
                next_states[total] = candidate
    return next_states


def _transition_thermal(
    states: dict[int, _State], plant: PowerPlant, load_units: int
) -> dict[int, _State]:
    next_states: dict[int, _State] = {}
    window: deque[_WindowCandidate] = deque()
    minimum = max(1, plant.min_units)
    maximum = plant.max_units
    unit_cost = plant.marginal_cost / 10

    for total in range(load_units + 1):
        entering_total = total - minimum
        if minimum <= maximum and entering_total in states:
            entering_state = states[entering_total]
            entering = _WindowCandidate(
                previous_total=entering_total,
                adjusted_cost=entering_state.cost - unit_cost * entering_total,
                state=entering_state,
            )
            while window and _window_precedes(entering, window[-1]):
                window.pop()
            window.append(entering)

        oldest_allowed = total - maximum
        while window and window[0].previous_total < oldest_allowed:
            window.popleft()

        off_state = states.get(total)
        if off_state is not None:
            next_states[total] = _State(
                cost=off_state.cost,
                outputs=(*off_state.outputs, 0),
            )

        if window:
            best = window[0]
            active = _State(
                cost=best.adjusted_cost + unit_cost * total,
                outputs=(*best.state.outputs, total - best.previous_total),
            )
            current = next_states.get(total)
            if current is None or _is_better(active, current):
                next_states[total] = active

    return next_states


def _window_precedes(candidate: _WindowCandidate, current: _WindowCandidate) -> bool:
    return candidate.adjusted_cost < current.adjusted_cost or (
        candidate.adjusted_cost == current.adjusted_cost
        and candidate.state.outputs > current.state.outputs
    )


def _is_better(candidate: _State, current: _State) -> bool:
    return candidate.cost < current.cost or (
        candidate.cost == current.cost and candidate.outputs > current.outputs
    )
