"""Stable API errors. Every expected failure is raised as ApiError → `{"detail", "code"}`."""

from __future__ import annotations

from fastapi import HTTPException


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found")


def forbidden(detail: str, code: str = "FORBIDDEN") -> ApiError:
    return ApiError(403, code, detail)


def conflict(code: str, detail: str) -> ApiError:
    return ApiError(409, code, detail)


def bad_request(code: str, detail: str) -> ApiError:
    return ApiError(400, code, detail)
