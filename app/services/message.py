import uuid
import logging
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("app.services.message")


class MongoMessageWrapper:
    def __init__(self, doc):
        self.id = uuid.UUID(doc["_id"]) if isinstance(doc["_id"], str) else doc["_id"]
        self.conversation_id = uuid.UUID(doc["conversation_id"]) if isinstance(doc["conversation_id"], str) else doc["conversation_id"]
        self.sender = doc["sender"]
        self.content = doc["content"]
        self.created_at = doc["created_at"]


class MessageService:
    """
    Orchestrates business logic for saving and retrieving conversation messages.
    """

    async def _get_mongo_collection(self, db: AsyncSession, conversation_id: uuid.UUID):
        from app.models.conversation import Conversation
        from app.models.bot_config import BotConfig
        from app.core.mongo import mongo_registry
        from app.core.config import settings
        from sqlalchemy import select

        conv = None
        mongo_client = mongo_registry.get_client("message_service", settings.MONGODB_URL)
        if mongo_client:
            conv_doc = await mongo_client["chatbot"]["conversations"].find_one({"_id": str(conversation_id)})
            if conv_doc:
                conv = Conversation(conv_doc)
        if not conv:
            return None, None
            
        bot_config_res = await db.execute(
            select(BotConfig).where(BotConfig.bot_id == conv.bot_id)
        )
        bot_config = bot_config_res.scalars().first()
        
        mongo_uri = None
        db_name = "chatbot"
        
        if bot_config and bot_config.use_custom_mongo:
            mongo_uri = bot_config.mongo_uri or settings.MONGODB_URL
            db_name = bot_config.mongo_db_name or "chatbot"
        else:
            mongo_uri = settings.MONGODB_URL
            
        if mongo_uri:
            mongo_client = mongo_registry.get_client(str(conv.bot_id), mongo_uri)
            if mongo_client:
                return mongo_client[db_name]["messages"], conv.bot_id
        return None, None

    async def save_user_message(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        content: str,
    ) -> MongoMessageWrapper:
        """
        Saves a message sent by the user.
        """
        logger.info(f"Saving user message for conversation: {conversation_id}")
        
        mongo_coll, bot_id = await self._get_mongo_collection(db, conversation_id)
        if mongo_coll is None:
            raise RuntimeError("MongoDB connection not available for conversation messages.")
            
        import datetime
        msg_id = uuid.uuid4()
        doc = {
            "_id": str(msg_id),
            "conversation_id": str(conversation_id),
            "sender": "user",
            "content": content,
            "created_at": datetime.datetime.utcnow()
        }
        try:
            await mongo_coll.insert_one(doc)
            
            # Track analytics event
            from app.services.analytics_tracking import analytics_tracking_service
            try:
                await analytics_tracking_service.track_message_sent(
                    db,
                    bot_id=bot_id,
                    conversation_id=conversation_id,
                    sender="user",
                    message_length=len(content),
                )
            except Exception as e:
                logger.error(f"Failed to track user message sent: {e}", exc_info=True)
                
            return MongoMessageWrapper(doc)
        except Exception as e:
            logger.error(f"Failed to save user message in MongoDB: {e}")
            raise e

    async def save_assistant_message(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        content: str,
    ) -> MongoMessageWrapper:
        """
        Saves a message sent by the assistant (bot).
        """
        logger.info(f"Saving assistant/bot message for conversation: {conversation_id}")
        
        mongo_coll, bot_id = await self._get_mongo_collection(db, conversation_id)
        if mongo_coll is None:
            raise RuntimeError("MongoDB connection not available for conversation messages.")
            
        import datetime
        msg_id = uuid.uuid4()
        doc = {
            "_id": str(msg_id),
            "conversation_id": str(conversation_id),
            "sender": "bot",
            "content": content,
            "created_at": datetime.datetime.utcnow()
        }
        try:
            await mongo_coll.insert_one(doc)
            
            # Track analytics event
            from app.services.analytics_tracking import analytics_tracking_service
            try:
                await analytics_tracking_service.track_bot_response(
                    db,
                    bot_id=bot_id,
                    conversation_id=conversation_id,
                    response_length=len(content),
                )
            except Exception as e:
                logger.error(f"Failed to track assistant response: {e}", exc_info=True)
                
            return MongoMessageWrapper(doc)
        except Exception as e:
            logger.error(f"Failed to save assistant message in MongoDB: {e}")
            raise e

    async def fetch_conversation_history(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> List[MongoMessageWrapper]:
        """
        Retrieves all messages in a conversation in chronological order.
        """
        logger.info(f"Fetching history for conversation: {conversation_id}")
        
        mongo_coll, _ = await self._get_mongo_collection(db, conversation_id)
        if mongo_coll is None:
            return []
            
        cursor = mongo_coll.find({"conversation_id": str(conversation_id)}).sort("created_at", 1).skip(skip).limit(limit)
        docs = []
        async for doc in cursor:
            docs.append(MongoMessageWrapper(doc))
        return docs

    async def fetch_recent_messages(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        limit: int = 10,
    ) -> List[MongoMessageWrapper]:
        """
        Retrieves the most recent messages in a conversation in chronological order.
        """
        logger.info(f"Fetching recent messages for conversation: {conversation_id}")
        
        mongo_coll, _ = await self._get_mongo_collection(db, conversation_id)
        if mongo_coll is None:
            return []
            
        cursor = mongo_coll.find({"conversation_id": str(conversation_id)}).sort("created_at", -1).limit(limit)
        docs = []
        async for doc in cursor:
            docs.append(MongoMessageWrapper(doc))
        docs.reverse()
        return docs


message_service = MessageService()
