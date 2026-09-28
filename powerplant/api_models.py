from pydantic import BaseModel


class ProductionPlanItem(BaseModel):
    name: str
    p: float


class ApiError(BaseModel):
    error: str
    message: str


NUMBER_SCHEMA = {"type": "number"}

POWERPLANT_SCHEMA = {
    "type": "object",
    "required": ["name", "type", "efficiency", "pmin", "pmax"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "type": {"type": "string", "enum": ["gasfired", "turbojet", "windturbine"]},
        "efficiency": {"type": "number", "exclusiveMinimum": 0},
        "pmin": {"type": "number", "minimum": 0},
        "pmax": {"type": "number", "minimum": 0},
    },
}

PRODUCTION_PLAN_REQUEST_SCHEMA = {
    "type": "object",
    "required": ["load", "fuels", "powerplants"],
    "properties": {
        "load": {"type": "number", "minimum": 0, "multipleOf": 0.1},
        "fuels": {
            "type": "object",
            "required": [
                "gas(euro/MWh)",
                "kerosine(euro/MWh)",
                "co2(euro/ton)",
                "wind(%)",
            ],
            "properties": {
                "gas(euro/MWh)": NUMBER_SCHEMA,
                "kerosine(euro/MWh)": NUMBER_SCHEMA,
                "co2(euro/ton)": NUMBER_SCHEMA,
                "wind(%)": {"type": "number", "minimum": 0, "maximum": 100},
            },
        },
        "powerplants": {"type": "array", "items": POWERPLANT_SCHEMA},
    },
}
