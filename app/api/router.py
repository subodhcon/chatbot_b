from fastapi import APIRouter
from app.api.v1.endpoints import auth, bots, conversations, documents, analytics, public, websocket, users

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(bots.router, prefix="/bots", tags=["bots"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(public.router, prefix="/public", tags=["public"])
api_router.include_router(websocket.router, prefix="/ws", tags=["websocket"])
api_router.include_router(users.router, prefix="/users", tags=["users"])


