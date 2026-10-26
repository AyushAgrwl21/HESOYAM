"""HTTP errors that keep a stable error_code in the JSON body."""

from fastapi import HTTPException


class CodedHTTPException(HTTPException):
    """An HTTP failure whose JSON error_code is chosen by the caller."""

    def __init__(self, status_code: int, error_code: str, detail: str) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code
