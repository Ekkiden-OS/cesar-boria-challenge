# Powerplant Production Planner

FastAPI service for the ENGIE powerplant coding challenge. Given a load, fuel prices, wind
availability, and plant constraints, `POST /productionplan` returns an exact minimum-cost plan in
`0.1 MW` increments. The optimizer is implemented from scratch; it does not use an external
linear-programming solver.

The original statement is preserved in [`CHALLENGE_ORIGINAL.md`](CHALLENGE_ORIGINAL.md), the
unchanged official examples are in [`example_payloads/`](example_payloads/), and the algorithm and
trade-offs are explained in [`DESIGN.md`](DESIGN.md).

## Requirements

- Python 3.10 or newer
- Docker, only for the container workflow

## Install and run locally

From the repository root, create a virtual environment and install the pinned dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

Start Uvicorn on the required port:

```powershell
.\.venv\Scripts\python -m uvicorn powerplant.main:app --host 0.0.0.0 --port 8888
```

The API is available at `http://localhost:8888`. Interactive documentation is at
`http://localhost:8888/docs`, and the generated schema is at
`http://localhost:8888/openapi.json`.

## Request a production plan

In another PowerShell terminal, submit an official payload:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://localhost:8888/productionplan `
  -ContentType application/json `
  -InFile example_payloads/payload3.json
```

The response is an array of plant names and assigned powers. Every power is on the `0.1 MW` grid,
and the sum equals the requested load exactly. For `payload3.json`, the result matches
`example_payloads/response3.json`.

The endpoint distinguishes these outcomes:

| Status | Meaning |
|---:|---|
| `200` | Valid request and an exact minimum-cost plan was found. |
| `400` | Malformed JSON or invalid domain input. |
| `413` | Valid input exceeds the optimizer's documented resource envelope. |
| `422` | Valid, bounded problem has no exact feasible plan. |
| `500` | Unexpected internal failure; implementation details are not returned. |

## Optional CO2 cost

CO2 emission cost is disabled by default, preserving the base challenge behavior. To enable it,
set `INCLUDE_CO2=true` in the environment used to start the server:

```powershell
$env:INCLUDE_CO2 = "true"
.\.venv\Scripts\python -m uvicorn powerplant.main:app --host 0.0.0.0 --port 8888
```

The application reads the setting on every request, which keeps tests and in-process configuration
isolated. An already-running process cannot see later changes made in a different shell; restart it
with the desired environment value.

When enabled, the gas-fired marginal cost in euro per electrical MWh is:

```text
gas price / efficiency + 0.3 * CO2 price
```

The challenge defines `0.3 ton/MWh` of gas-fired emissions. Turbojets continue to use
`kerosine price / efficiency`, and wind remains free. Values other than the case-insensitive string
`true` leave the option disabled.

## Tests and checks

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format --check .
git diff --check
```

The suite includes the official examples, HTTP contract tests, adversarial edge cases, and 150
seeded small instances checked against an independent exhaustive oracle. A reproducible performance
measurement for the official fixtures is available with:

```powershell
.\.venv\Scripts\python benchmarks\benchmark_official.py
```

The recorded before/after measurements and their limitations are in [`DESIGN.md`](DESIGN.md).

## Docker

Build the image from the repository root and publish the required port:

```powershell
docker build --pull --no-cache -t powerplant-api .
docker run --rm --name powerplant-api -p 8888:8888 powerplant-api
```

The container starts Uvicorn without development reload and listens on `0.0.0.0:8888`. `EXPOSE`
documents the container port; `-p 8888:8888` makes it reachable from the host.

Enable the optional CO2 objective inside the container with:

```powershell
docker run --rm --name powerplant-api-co2 -e INCLUDE_CO2=true `
  -p 8888:8888 powerplant-api
```

Press `Ctrl+C` to stop either foreground container. Because `--rm` is present, Docker removes it
after it stops.
