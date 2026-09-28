import json
from collections.abc import Mapping
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from fractions import Fraction
from typing import Any, NoReturn

from powerplant.model import Fuels, PlantType, PowerPlant, ProductionProblem

POWER_STEP = Decimal("0.1")
HUNDRED = Decimal("100")
CO2_TONS_PER_MWH = Decimal("0.3")


class DomainValidationError(ValueError):
    """Raised when an input cannot represent a valid production problem."""


def _reject_json_constant(value: str) -> NoReturn:
    raise DomainValidationError(f"{value} is not a finite JSON number")


def parse_json_payload(payload: bytes | str, *, include_co2: bool = False) -> ProductionProblem:
    """Parse the original JSON text without passing numbers through binary floats."""
    try:
        data = json.loads(
            payload,
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise DomainValidationError("payload must be valid JSON") from error

    return parse_payload(data, include_co2=include_co2)


def parse_payload(data: object, *, include_co2: bool = False) -> ProductionProblem:
    payload = _mapping(data, "payload")
    load = _number(_required(payload, "load", "payload"), "load")
    if load < 0:
        raise DomainValidationError("load must be greater than or equal to zero")
    load_units = power_to_units(load, "load")

    fuels = _parse_fuels(_required(payload, "fuels", "payload"))
    raw_plants = _required(payload, "powerplants", "payload")
    if not isinstance(raw_plants, list):
        raise DomainValidationError("powerplants must be an array")

    plants = tuple(
        _parse_plant(item, index, fuels, include_co2) for index, item in enumerate(raw_plants)
    )
    names = [plant.name for plant in plants]
    if len(names) != len(set(names)):
        raise DomainValidationError("powerplant names must be unique")

    return ProductionProblem(load=load, load_units=load_units, fuels=fuels, powerplants=plants)


def power_to_units(value: Decimal, field: str = "power") -> int:
    """Convert power to exact tenths of MW, rejecting values outside that grid."""
    units = value / POWER_STEP
    integral_units = units.to_integral_value()
    if units != integral_units:
        raise DomainValidationError(f"{field} must use 0.1 MW increments")
    return int(integral_units)


def _parse_fuels(data: object) -> Fuels:
    fuels = _mapping(data, "fuels")
    gas_price = _number(_required(fuels, "gas(euro/MWh)", "fuels"), "gas(euro/MWh)")
    kerosine_price = _number(_required(fuels, "kerosine(euro/MWh)", "fuels"), "kerosine(euro/MWh)")
    wind_percent = _number(_required(fuels, "wind(%)", "fuels"), "wind(%)")
    co2_price = _number(_required(fuels, "co2(euro/ton)", "fuels"), "co2(euro/ton)")

    if not Decimal("0") <= wind_percent <= HUNDRED:
        raise DomainValidationError("wind(%) must be between 0 and 100")

    return Fuels(
        gas_price=gas_price,
        kerosine_price=kerosine_price,
        co2_price=co2_price,
        wind_percent=wind_percent,
    )


def _parse_plant(data: object, index: int, fuels: Fuels, include_co2: bool) -> PowerPlant:
    field = f"powerplants[{index}]"
    plant = _mapping(data, field)

    name = _required(plant, "name", field)
    if not isinstance(name, str) or not name.strip():
        raise DomainValidationError(f"{field}.name must be a non-empty string")

    raw_type = _required(plant, "type", field)
    try:
        plant_type = PlantType(raw_type)
    except (TypeError, ValueError) as error:
        allowed = ", ".join(item.value for item in PlantType)
        raise DomainValidationError(f"{field}.type must be one of: {allowed}") from error

    efficiency = _number(_required(plant, "efficiency", field), f"{field}.efficiency")
    pmin = _number(_required(plant, "pmin", field), f"{field}.pmin")
    pmax = _number(_required(plant, "pmax", field), f"{field}.pmax")

    if efficiency <= 0:
        raise DomainValidationError(f"{field}.efficiency must be greater than zero")
    if pmin < 0 or pmax < 0 or pmin > pmax:
        raise DomainValidationError(f"{field} must satisfy 0 <= pmin <= pmax")

    min_units = int((pmin / POWER_STEP).to_integral_value(rounding=ROUND_CEILING))
    max_units = int((pmax / POWER_STEP).to_integral_value(rounding=ROUND_FLOOR))
    marginal_cost = _marginal_cost(plant_type, efficiency, fuels, include_co2)

    available_wind_power = None
    available_wind_units = None
    if plant_type is PlantType.WIND_TURBINE:
        available_wind_power = pmax * fuels.wind_percent / HUNDRED
        try:
            available_wind_units = power_to_units(
                available_wind_power, f"{field}.available_wind_power"
            )
        except DomainValidationError:
            available_wind_units = None

    return PowerPlant(
        name=name,
        plant_type=plant_type,
        efficiency=efficiency,
        pmin=pmin,
        pmax=pmax,
        min_units=min_units,
        max_units=max_units,
        marginal_cost=marginal_cost,
        available_wind_power=available_wind_power,
        available_wind_units=available_wind_units,
    )


def _marginal_cost(
    plant_type: PlantType, efficiency: Decimal, fuels: Fuels, include_co2: bool
) -> Fraction:
    if plant_type is PlantType.WIND_TURBINE:
        return Fraction(0)
    price = fuels.gas_price if plant_type is PlantType.GAS_FIRED else fuels.kerosine_price
    fuel_cost = Fraction(price) / Fraction(efficiency)
    if include_co2 and plant_type is PlantType.GAS_FIRED:
        return fuel_cost + Fraction(CO2_TONS_PER_MWH) * Fraction(fuels.co2_price)
    return fuel_cost


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise DomainValidationError(f"{field} must be an object")
    return value


def _required(mapping: Mapping[str, Any], key: str, field: str) -> Any:
    if key not in mapping:
        raise DomainValidationError(f"{field}.{key} is required")
    return mapping[key]


def _number(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise DomainValidationError(f"{field} must be a JSON number")
    if not value.is_finite():
        raise DomainValidationError(f"{field} must be finite")
    return value
