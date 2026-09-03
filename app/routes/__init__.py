from fastapi import APIRouter

from app.routes.admin import router as admin_router
from app.routes.bootstrap import router as bootstrap_router
from app.routes.chat import router as chat_router
from app.routes.fairy import router as fairy_router
from app.routes.media import router as media_router
from app.routes.schedule import router as schedule_router
from app.routes.status import router as status_router


api_router = APIRouter(prefix="/api")
api_router.include_router(status_router)
api_router.include_router(bootstrap_router)
api_router.include_router(chat_router)
api_router.include_router(media_router)
api_router.include_router(schedule_router)
api_router.include_router(admin_router)
api_router.include_router(fairy_router)
