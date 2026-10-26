"""FastAPI application factory.

Reads score the local cache. They do not call Elexon and they do not place orders.
"""

import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes.health import router as health_router
from app.api.routes.v1 import router as study_router
from app.logging_setup import configure_logging
from app.schemas.health import ErrorResponse
from app.settings import Settings, load_settings

logger = logging.getLogger("wind_procurement.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API with explicit CORS and a configuration health check."""
    application_settings = load_settings() if settings is None else settings
    configure_logging(application_settings)

    application = FastAPI(
        title="GB wind procurement pilot",
        version="0.2.0",
        description=(
            "January 2026 GB wind procurement pilot. "
            "GET /health reports configuration. "
            "GET /api/v1/summary, /series, /accuracy, /forecast-vintages, and /data-quality "
            "score the local FUELHH and WINDFOR cache. "
            "A read does not call Elexon. Metric definitions are in docs/ANALYTICS.md. "
            "The API does not recommend a trade or place an order."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    application.state.settings = application_settings
    application.include_router(health_router)
    application.include_router(study_router)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=application_settings.allowed_cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type"],
    )
    application.middleware("http")(log_http_request)
    _register_error_handlers(application)

    logger.info(
        "Wind procurement API ready for settlement dates %s to %s. "
        "Decision cutoff %s %s is a %s. Elexon was not called.",
        application_settings.study_start.isoformat(),
        application_settings.study_end.isoformat(),
        application_settings.decision_cutoff_local,
        application_settings.decision_timezone,
        "pilot assumption",
    )
    return application


async def log_http_request(request: Request, call_next):
    """Log the method, path, status, and duration for each request."""
    started_at = perf_counter()
    response = await call_next(request)
    elapsed_milliseconds = (perf_counter() - started_at) * 1000
    logger.info(
        "%s %s completed with status %s in %.1f ms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_milliseconds,
    )
    return response


def _register_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        validation_error: RequestValidationError,
    ) -> JSONResponse:
        invalid_fields = [
            ".".join(str(part) for part in error_item["loc"])
            + ": "
            + str(error_item.get("msg", "invalid"))
            for error_item in validation_error.errors()
        ]
        logger.warning(
            "Rejected %s %s because these fields were invalid: %s",
            request.method,
            request.url.path,
            "; ".join(invalid_fields) or "unknown",
        )
        payload = ErrorResponse(
            error_code="invalid_request",
            detail=(
                "The request could not be validated. "
                + ("; ".join(invalid_fields) or "Check the query parameters.")
            ),
        )
        return JSONResponse(status_code=422, content=payload.model_dump())

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request,
        http_exception: StarletteHTTPException,
    ) -> JSONResponse:
        coded_error = getattr(http_exception, "error_code", None)
        if http_exception.status_code == 404:
            detail = (
                f"No route matches {request.method} {request.url.path}. "
                "The API serves GET /health, GET /api/health, and GET /api/v1/summary."
            )
            error_code = "http_error"
        elif isinstance(coded_error, str):
            detail = http_exception.detail if isinstance(http_exception.detail, str) else "The request was rejected."
            error_code = coded_error
        elif isinstance(http_exception.detail, str):
            detail = http_exception.detail
            error_code = "invalid_request" if http_exception.status_code == 422 else "http_error"
        else:
            detail = "The request was rejected."
            error_code = "http_error"
        payload = ErrorResponse(error_code=error_code, detail=detail)
        return JSONResponse(
            status_code=http_exception.status_code,
            content=payload.model_dump(),
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request,
        unexpected_exception: Exception,
    ) -> JSONResponse:
        logger.exception(
            "Unhandled failure for %s %s",
            request.method,
            request.url.path,
            exc_info=unexpected_exception,
        )
        payload = ErrorResponse(
            error_code="internal_error",
            detail=(
                "The request failed before a response could be built. "
                "Check the API log for the traceback."
            ),
        )
        return JSONResponse(status_code=500, content=payload.model_dump())


app = create_app()
