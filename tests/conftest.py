from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from powerplant.main import app


@pytest.fixture
def api() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def valid_payload() -> dict:
    return {
        "load": 1.2,
        "fuels": {
            "gas(euro/MWh)": 1,
            "kerosine(euro/MWh)": 10,
            "co2(euro/ton)": 0,
            "wind(%)": 0,
        },
        "powerplants": [
            {
                "name": "gas",
                "type": "gasfired",
                "efficiency": 1,
                "pmin": 0,
                "pmax": 2,
            }
        ],
    }
