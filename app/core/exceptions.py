import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.responses import api_error_response
from app.core.error_monitoring import error_monitor

logger = logging.getLogger("app.exceptions")

async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Handles Starlette/FastAPI HTTPExceptions (e.g. 404 Not Found, 401 Unauthorized).
    """
    logger.warning(f"HTTP exception: status_code={exc.status_code} detail={exc.detail}")
    if isinstance(exc.detail, dict):
        return api_error_response(
            message=exc.detail.get("message", "An error occurred."),
            code=exc.detail.get("code", "HTTP_ERROR"),
            details=exc.detail.get("details"),
            status_code=exc.status_code
        )
    return api_error_response(
        message=str(exc.detail),
        code="HTTP_ERROR",
        status_code=exc.status_code
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handles Pydantic validation errors (RequestValidationError).
    Formats them clearly.
    """
    errors = exc.errors()
    formatted_errors = []
    for error in errors:
        formatted_errors.append({
            "field": " -> ".join(map(str, error.get("loc", []))),
            "message": error.get("msg", ""),
            "type": error.get("type", "")
        })
        
    logger.warning(f"Validation error: {formatted_errors}")
    return api_error_response(
        message="Request validation failed.",
        code="VALIDATION_ERROR",
        details=formatted_errors,
        status_code=422
    )

async def generic_exception_handler(request: Request, exc: Exception):
    """
    Handles any unhandled Python exception (500 Internal Server Error).
    """
    # Track exception centrally
    error_monitor.capture_exception(
        exc,
        context={
            "url": str(request.url),
            "method": request.method,
            "headers": dict(request.headers),
        },
        tags={"layer": "api"}
    )
    return api_error_response(
        message="An unexpected server error occurred.",
        code="INTERNAL_SERVER_ERROR",
        status_code=500
    )

def setup_exception_handlers(app: FastAPI) -> None:
    """
    Bind exception handlers to the FastAPI app instance.
    """
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
