from typing import Any, Optional
from fastapi.responses import JSONResponse

def api_success_response(data: Any = None, status_code: int = 200) -> JSONResponse:
    """
    Standard successful JSON response wrapper.
    """
    return JSONResponse(
        status_code=status_code,
        content={
            "success": True,
            "data": data,
            "error": None
        }
    )

def api_error_response(
    message: str, 
    code: str = "ERROR", 
    details: Optional[Any] = None, 
    status_code: int = 400
) -> JSONResponse:
    """
    Standard error JSON response wrapper.
    """
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": code,
                "message": message,
                "details": details
            }
        }
    )
