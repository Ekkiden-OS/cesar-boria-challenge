import json

import pytest
from fastapi.testclient import TestClient

import powerplant.main as app_module


def test_success_is_200_with_json_plan(api: TestClient, valid_payload: dict) -> None:
    response = api.post("/productionplan", json=valid_payload)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == [{"name": "gas", "p": 1.2}]


def test_malformed_json_is_400_and_next_request_still_works(
    api: TestClient, valid_payload: dict
) -> None:
    invalid = api.post(
        "/productionplan", content=b'{"load":', headers={"Content-Type": "application/json"}
    )

    assert invalid.status_code == 400
    assert invalid.json()["error"] == "invalid_request"
    assert api.post("/productionplan", json=valid_payload).status_code == 200


@pytest.mark.parametrize(
    "mutation",
    [
        lambda body: body.pop("load"),
        lambda body: body.update(load=True),
        lambda body: body["fuels"].update({"wind(%)": 101}),
        lambda body: body["powerplants"][0].update(efficiency=0),
        lambda body: body["powerplants"][0].update(type="nuclear"),
    ],
)
def test_invalid_fields_and_values_are_400(api: TestClient, valid_payload: dict, mutation) -> None:
    mutation(valid_payload)

    response = api.post("/productionplan", json=valid_payload)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_high_precision_load_literal_is_not_silently_rounded(api: TestClient) -> None:
    body = b"""{
      "load": 0.10000000000000001,
      "fuels": {"gas(euro/MWh)": 1, "kerosine(euro/MWh)": 1,
                "co2(euro/ton)": 0, "wind(%)": 0},
      "powerplants": []
    }"""

    response = api.post(
        "/productionplan", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 400
    assert "0.1 MW increments" in response.json()["message"]


def test_pmax_below_one_tenth_is_not_rounded_up(api: TestClient) -> None:
    body = b"""{
      "load": 0.1,
      "fuels": {"gas(euro/MWh)": 1, "kerosine(euro/MWh)": 1,
                "co2(euro/ton)": 0, "wind(%)": 0},
      "powerplants": [{"name": "gas", "type": "gasfired", "efficiency": 1,
                       "pmin": 0, "pmax": 0.09999999999999999}]
    }"""

    response = api.post(
        "/productionplan", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["error"] == "infeasible"


def test_valid_but_infeasible_problem_is_422(api: TestClient, valid_payload: dict) -> None:
    valid_payload["load"] = 1
    valid_payload["powerplants"] = []

    response = api.post("/productionplan", json=valid_payload)

    assert response.status_code == 422
    assert response.json()["error"] == "infeasible"


def test_load_over_resource_limit_is_413_and_next_request_still_works(
    api: TestClient, valid_payload: dict
) -> None:
    oversized = {**valid_payload, "load": 20_000.1}

    response = api.post("/productionplan", json=oversized)

    assert response.status_code == 413
    assert response.json()["error"] == "resource_limit"
    assert api.post("/productionplan", json=valid_payload).status_code == 200


def test_combined_load_and_plant_state_space_over_limit_is_413(
    api: TestClient, valid_payload: dict
) -> None:
    template = valid_payload["powerplants"][0]
    oversized = {
        **valid_payload,
        "load": 10_000,
        "powerplants": [{**template, "name": f"gas-{index}"} for index in range(21)],
    }

    response = api.post("/productionplan", json=oversized)

    assert response.status_code == 413
    assert response.json()["error"] == "resource_limit"


def test_huge_pmax_with_small_load_is_bounded_by_the_target(
    api: TestClient, valid_payload: dict
) -> None:
    valid_payload["load"] = 0.1
    valid_payload["powerplants"][0]["pmax"] = 10**100

    response = api.post("/productionplan", json=valid_payload)

    assert response.status_code == 200
    assert response.json() == [{"name": "gas", "p": 0.1}]


def test_internal_error_is_logged_hidden_and_does_not_break_next_request(
    api: TestClient,
    valid_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_detail = "database password accidentally reached optimizer"

    def fail(_problem):
        raise RuntimeError(sensitive_detail)

    with monkeypatch.context() as patch:
        patch.setattr(app_module, "optimize", fail)
        response = api.post("/productionplan", json=valid_payload)

    assert response.status_code == 500
    assert response.json() == {"error": "internal_error", "message": "internal server error"}
    assert sensitive_detail in caplog.text
    assert sensitive_detail not in json.dumps(response.json())
    assert api.post("/productionplan", json=valid_payload).status_code == 200


def test_openapi_documents_request_success_and_error_contract(api: TestClient) -> None:
    response = api.get("/openapi.json")

    assert response.status_code == 200
    operation = response.json()["paths"]["/productionplan"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["required"] == ["load", "fuels", "powerplants"]
    assert request_schema["properties"]["load"]["multipleOf"] == 0.1
    assert request_schema["properties"]["powerplants"]["items"]["required"] == [
        "name",
        "type",
        "efficiency",
        "pmin",
        "pmax",
    ]

    responses = operation["responses"]
    assert {"200", "400", "413", "422", "500"} <= responses.keys()
    assert responses["200"]["content"]["application/json"]["schema"]["type"] == "array"
    for status_code in ("400", "413", "422", "500"):
        error_schema = responses[status_code]["content"]["application/json"]["schema"]
        assert error_schema["$ref"].endswith("/ApiError")
