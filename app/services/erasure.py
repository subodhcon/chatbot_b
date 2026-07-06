import uuid
import logging
from typing import Dict, Any
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.widget_session import WidgetSession
from app.models.conversation import Conversation

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
        Cascades automatically deletes messages, feedback ratings, and analytics events.
        """
        try:
            logger.info(f"GDPR Erasure: Request received for conversation_id={conversation_id}")

            # 1. Fetch models to verify existence
            conv_query = select(Conversation).where(Conversation.id == conversation_id)
            conv_res = await db.execute(conv_query)
            conversation = conv_res.scalar_one_or_none()

            session_query = select(WidgetSession).where(WidgetSession.id == conversation_id)
            session_res = await db.execute(session_query)
            session = session_res.scalar_one_or_none()

            if not conversation and not session:
                logger.warning(f"GDPR Erasure: No active records found for conversation_id={conversation_id}")
                return False

            # 2. Delete Conversation (cascades to messages, feedback ratings, analytics events)
            if conversation:
                await db.delete(conversation)
                logger.info(f"GDPR Erasure: Deleted conversation model for {conversation_id}")

            # 3. Delete WidgetSession
            if session:
                await db.delete(session)
                logger.info(f"GDPR Erasure: Deleted widget session model for {conversation_id}")

            # Commit the erasure transaction
            await db.commit()
            logger.info(f"GDPR Erasure: Erasure completed successfully for conversation_id={conversation_id}")
            return True

        except Exception as e:
            logger.error(f"GDPR Erasure: Failed to execute erasure for conversation_id={conversation_id}: {e}")
            await db.rollback()
            raise e

    async def erase_visitor_history(self, db: AsyncSession, visitor_session_id: str) -> Dict[str, Any]:
        """
        Hard-deletes all conversation history associated with a visitor_session_id.
        """
        try:
            logger.info(f"GDPR Erasure: Request received for visitor_session_id={visitor_session_id}")

            # Find all widget sessions for this visitor
            query = select(WidgetSession.id).where(WidgetSession.visitor_session_id == visitor_session_id)
            res = await db.execute(query)
            conversation_ids = res.scalars().all()

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
