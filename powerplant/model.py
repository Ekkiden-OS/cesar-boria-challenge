from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from fractions import Fraction


class PlantType(str, Enum):
    GAS_FIRED = "gasfired"
    TURBOJET = "turbojet"
    WIND_TURBINE = "windturbine"


@dataclass(frozen=True)
class Fuels:
    gas_price: Decimal
    kerosine_price: Decimal
    co2_price: Decimal
    wind_percent: Decimal


@dataclass(frozen=True)
class PowerPlant:
    name: str
    plant_type: PlantType
    efficiency: Decimal
    pmin: Decimal
    pmax: Decimal
    min_units: int
    max_units: int
    marginal_cost: Fraction
    available_wind_power: Decimal | None = None
    available_wind_units: int | None = None


@dataclass(frozen=True)
class ProductionProblem:
    load: Decimal
    load_units: int
    fuels: Fuels
    powerplants: tuple[PowerPlant, ...]
