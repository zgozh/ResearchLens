from fastapi import APIRouter

from . import canonical, routes  # noqa: F401

api_router = APIRouter()
api_router.include_router(routes.router)
api_router.include_router(canonical.router)
