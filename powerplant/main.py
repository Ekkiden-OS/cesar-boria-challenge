import logging
import os

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from powerplant.api_models import PRODUCTION_PLAN_REQUEST_SCHEMA, ApiError, ProductionPlanItem
from powerplant.optimizer import InfeasibleError, ResourceLimitError, optimize
from powerplant.validation import DomainValidationError, parse_json_payload

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Powerplant Production Planner",
    description="API for the ENGIE powerplant coding challenge.",
    version="0.1.0",
)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    """Confirm that the API is running."""
    return {"message": "Powerplant Production Planner API"}


@app.post(
    "/productionplan",
    tags=["production"],
    response_model=list[ProductionPlanItem],
    responses={
        400: {"model": ApiError, "description": "Malformed JSON or invalid payload"},
        413: {"model": ApiError, "description": "Valid payload exceeds safe optimizer limits"},
        422: {"model": ApiError, "description": "Valid payload with no exact production plan"},
        500: {"model": ApiError, "description": "Unexpected internal error"},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": PRODUCTION_PLAN_REQUEST_SCHEMA}},
        }
    },
)
async def production_plan(request: Request) -> list[dict[str, str | float]] | JSONResponse:
    try:
        problem = parse_json_payload(await request.body(), include_co2=_include_co2())
        plan = await run_in_threadpool(optimize, problem)
    except DomainValidationError as error:
        logger.warning("invalid production-plan request: %s", error)
        return _error_response(400, "invalid_request", str(error))
    except ResourceLimitError as error:
        logger.warning("production-plan request exceeds resource limits: %s", error)
        return _error_response(413, "resource_limit", str(error))
    except InfeasibleError as error:
        logger.warning("infeasible production-plan request: %s", error)
        return _error_response(422, "infeasible", str(error))
    except Exception:
        logger.exception("unexpected production-plan failure")
        return _error_response(500, "internal_error", "internal server error")

    logger.info("production plan calculated for %s MW", problem.load)
    return plan


def _error_response(status_code: int, error: str, message: str) -> JSONResponse:
    body = ApiError(error=error, message=message)
    return JSONResponse(status_code=status_code, content=body.model_dump())


def _include_co2() -> bool:
    return os.getenv("INCLUDE_CO2", "").strip().lower() == "true"
