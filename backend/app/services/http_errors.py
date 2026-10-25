"""The two HTTP errors every service raises the same way, kept below both ``work_items`` and ``grimoire_view``."""

from fastapi import HTTPException, status


def not_found(entity: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{entity} not found")


def conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
