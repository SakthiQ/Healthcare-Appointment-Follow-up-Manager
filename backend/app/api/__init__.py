from fastapi import APIRouter
from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.api.doctors import router as doctors_router
from app.api.slots import router as slots_router
from app.api.appointments import router as appointments_router
from app.api.ai import router as ai_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(doctors_router)
api_router.include_router(slots_router)
api_router.include_router(appointments_router)
api_router.include_router(ai_router)
