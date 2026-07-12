import uuid
import logging
from typing import List, Optional
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

    async def _resolve_bot_id_for_conversation(self, db: AsyncSession, conversation_id: uuid.UUID) -> Optional[uuid.UUID]:
        from app.utils.redis import get_redis
        from sqlalchemy import select
        from app.models.bot_config import BotConfig
        from app.core.mongo import mongo_registry
        from app.core.config import settings
        
        # 1. Try Redis first
        redis_client = None
        try:
            redis_gen = get_redis()
            redis_client = await redis_gen.__anext__()
            if redis_client and not getattr(redis_client, "is_mock", False):
                cached = await redis_client.get(f"cache:conv_bot:{conversation_id}")
                if cached:
                    val = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                    return uuid.UUID(val)
        except Exception as re_err:
            logger.warning(f"Redis lookup failed in resolve_bot_id: {re_err}")

        # 2. Try main Mongo lookup if configured
        if settings.MONGODB_URL and "localhost" not in settings.MONGODB_URL:
            try:
                mongo_client = mongo_registry.get_client("resolve_bot", settings.MONGODB_URL)
                if mongo_client:
                    db_name = mongo_registry.get_database_name(settings.MONGODB_URL)
                    conv_doc = await mongo_client[db_name]["conversations"].find_one({"_id": str(conversation_id)})
                    if not conv_doc:
                        conv_doc = await mongo_client[db_name]["widget_sessions"].find_one({"_id": str(conversation_id)})
                    if conv_doc and "bot_id" in conv_doc:
                        bot_id = uuid.UUID(conv_doc["bot_id"])
                        if redis_client and not getattr(redis_client, "is_mock", False):
                            await redis_client.set(f"cache:conv_bot:{conversation_id}", str(bot_id), ex=86400)
                        return bot_id
            except Exception as mongo_err:
                logger.warning(f"Main Mongo lookup failed in resolve_bot_id: {mongo_err}")

        # 3. Multi-tenant scan: check each bot's custom MongoDB config
        try:
            bot_configs_res = await db.execute(select(BotConfig))
            bot_configs = bot_configs_res.scalars().all()
            for config in bot_configs:
                mongo_uri = config.mongo_uri if config.use_custom_mongo else settings.MONGODB_URL
                if not mongo_uri or (not config.use_custom_mongo and "localhost" in mongo_uri):
                    continue
                try:
                    client = mongo_registry.get_client(str(config.bot_id), mongo_uri)
                    if client:
                        db_name = config.mongo_db_name if config.use_custom_mongo else mongo_registry.get_database_name(mongo_uri)
                        conv_doc = await client[db_name]["conversations"].find_one({"_id": str(conversation_id)})
                        if not conv_doc:
                            conv_doc = await client[db_name]["widget_sessions"].find_one({"_id": str(conversation_id)})
                        if conv_doc:
                            bot_id = config.bot_id
                            if redis_client and not getattr(redis_client, "is_mock", False):
                                await redis_client.set(f"cache:conv_bot:{conversation_id}", str(bot_id), ex=86400)
                            return bot_id
                except Exception as check_err:
                    logger.debug(f"Failed to check mongo for bot {config.bot_id}: {check_err}")
        except Exception as scan_err:
            logger.error(f"Error during bot configs scan in resolve_bot_id: {scan_err}")

        return None

    async def _get_mongo_collection(self, db: AsyncSession, conversation_id: uuid.UUID):
        from app.models.bot_config import BotConfig
        from app.core.mongo import mongo_registry
        from app.core.config import settings
        from sqlalchemy import select

        bot_id = await self._resolve_bot_id_for_conversation(db, conversation_id)
        if not bot_id:
            return None, None
            
        bot_config_res = await db.execute(
            select(BotConfig).where(BotConfig.bot_id == bot_id)
        )
        bot_config = bot_config_res.scalars().first()
        
        mongo_uri = None
        db_name = "chatbot"
        
        if bot_config and bot_config.use_custom_mongo:
            mongo_uri = bot_config.mongo_uri or settings.MONGODB_URL
            db_name = bot_config.mongo_db_name or mongo_registry.get_database_name(mongo_uri)
        else:
            mongo_uri = settings.MONGODB_URL
            db_name = mongo_registry.get_database_name(mongo_uri)
            
        if mongo_uri:
            mongo_client = mongo_registry.get_client(str(bot_id), mongo_uri)
            if mongo_client:
                return mongo_client[db_name]["messages"], bot_id
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
