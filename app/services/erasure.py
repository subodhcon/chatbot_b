import uuid
import logging
from typing import Dict, Any
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("app.services.erasure")


class ErasureService:
    """
    ErasureService orchestrates GDPR "Right to Erasure" compliance operations.
    Ensures complete removal of visitor conversation records, message transcripts,
    feedback ratings, and telemetry analytics events from the database.
    """

    async def erase_conversation(self, db: AsyncSession, conversation_id: uuid.UUID) -> bool:
        """
        Hard-deletes a conversation session by its ID.
        Cascades automatically deletes messages, feedback ratings, and analytics events in MongoDB.
        """
        try:
            logger.info(f"GDPR Erasure: Request received for conversation_id={conversation_id}")

            from app.core.config import settings
            from app.core.mongo import mongo_registry
            mongo_client = mongo_registry.get_client("erasure", settings.MONGODB_URL)
            if not mongo_client:
                return False

            db_name = "chatbot"
            mongo_db = mongo_client[db_name]

            # 1. Fetch models to verify existence
            conv_doc = await mongo_db["conversations"].find_one({"_id": str(conversation_id)})
            session_doc = await mongo_db["widget_sessions"].find_one({"_id": str(conversation_id)})

            if not conv_doc and not session_doc:
                logger.warning(f"GDPR Erasure: No active records found for conversation_id={conversation_id}")
                return False

            # 2. Delete related data from MongoDB
            cid_str = str(conversation_id)
            await mongo_db["conversations"].delete_many({"_id": cid_str})
            await mongo_db["widget_sessions"].delete_many({"_id": cid_str})
            await mongo_db["messages"].delete_many({"conversation_id": cid_str})
            await mongo_db["feedback_ratings"].delete_many({"conversation_id": cid_str})
            await mongo_db["analytics_events"].delete_many({"conversation_id": cid_str})

            logger.info(f"GDPR Erasure: Erasure completed successfully for conversation_id={conversation_id}")
            return True

        except Exception as e:
            logger.error(f"GDPR Erasure: Failed to execute erasure for conversation_id={conversation_id}: {e}")
            raise e

    async def erase_visitor_history(self, db: AsyncSession, visitor_session_id: str) -> Dict[str, Any]:
        """
        Hard-deletes all conversation history associated with a visitor_session_id.
        """
        try:
            logger.info(f"GDPR Erasure: Request received for visitor_session_id={visitor_session_id}")

            from app.core.config import settings
            from app.core.mongo import mongo_registry
            mongo_client = mongo_registry.get_client("erasure", settings.MONGODB_URL)
            if not mongo_client:
                return {
                    "visitor_session_id": visitor_session_id,
                    "conversations_erased": 0,
                    "success": False
                }

            db_name = "chatbot"
            mongo_db = mongo_client[db_name]

            # Find all widget sessions for this visitor
            cursor = mongo_db["widget_sessions"].find({"visitor_session_id": visitor_session_id}, {"_id": 1})
            conversation_ids = [doc["_id"] async for doc in cursor]

            erased_count = 0
            for cid in conversation_ids:
                success = await self.erase_conversation(db, conversation_id=cid)
                if success:
                    erased_count += 1

            return {
                "visitor_session_id": visitor_session_id,
                "conversations_erased": erased_count,
                "success": True
            }

        except Exception as e:
            logger.error(f"GDPR Erasure: Failed to execute erasure for visitor_session_id={visitor_session_id}: {e}")
            raise e


# Module-level singleton
erasure_service = ErasureService()
