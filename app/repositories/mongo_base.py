import uuid
import datetime
from typing import Any, Dict, List, Optional, Type, TypeVar
from app.core.config import settings
from app.core.mongo import mongo_registry

ModelType = TypeVar("ModelType")

class MongoBaseRepository:
    def __init__(self, collection_name: str, wrapper_class: Type[ModelType]):
        """
        Base Repository with async MongoDB CRUD methods mimicking BaseRepository.
        """
        self.collection_name = collection_name
        self.wrapper_class = wrapper_class

    async def get_collection_for_bot(self, db: Any, bot_id: Any):
        from app.models.bot_config import BotConfig
        from sqlalchemy import select
        
        db_bot_id = bot_id
        if isinstance(db_bot_id, str):
            try:
                db_bot_id = uuid.UUID(db_bot_id)
            except ValueError:
                pass
                
        bot_config_res = await db.execute(
            select(BotConfig).where(BotConfig.bot_id == db_bot_id)
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
            
        if not mongo_uri:
            raise ValueError(f"No MongoDB connection configured for bot: {bot_id}")
            
        mongo_client = mongo_registry.get_client(str(bot_id), mongo_uri)
        return mongo_client[db_name][self.collection_name]

    async def get_collection(self, db: Any = None, bot_id: Any = None):
        if db and bot_id:
            # This will use custom mongo if configured, or default otherwise
            return await self.get_collection_for_bot(db, bot_id)
                
        mongo_client = mongo_registry.get_client("repositories", settings.MONGODB_URL)
        if not mongo_client:
            raise RuntimeError("MongoDB connection not available.")
        db_name = mongo_registry.get_database_name(settings.MONGODB_URL)
        return mongo_client[db_name][self.collection_name]


    async def get_async(self, db: Any, id: Any) -> Optional[ModelType]:
        coll = await self.get_collection(db)
        doc = await coll.find_one({"_id": str(id)})
        return self.wrapper_class(doc) if doc else None

    async def get_multi_async(self, db: Any, *, bot_id: Any = None, skip: int = 0, limit: int = 100) -> List[ModelType]:
        coll = await self.get_collection(db, bot_id)
        cursor = coll.find({}).skip(skip).limit(limit)
        results = []
        async for doc in cursor:
            results.append(self.wrapper_class(doc))
        return results

    async def create_async(self, db: Any, *, obj_in: Dict[str, Any]) -> ModelType:
        bot_id = obj_in.get("bot_id")
        coll = await self.get_collection(db, bot_id)
        doc = {**obj_in}
        if "_id" not in doc:
            doc["_id"] = str(uuid.uuid4())
        # Ensure all UUID fields are serialized as string for MongoDB
        for k, v in list(doc.items()):
            if isinstance(v, uuid.UUID):
                doc[k] = str(v)
        if "created_at" not in doc:
            doc["created_at"] = datetime.datetime.utcnow()
        if "updated_at" not in doc:
            doc["updated_at"] = datetime.datetime.utcnow()
            
        await coll.insert_one(doc)
        return self.wrapper_class(doc)

    async def update_async(self, db: Any, *, db_obj: Any, obj_in: Dict[str, Any]) -> ModelType:
        bot_id = getattr(db_obj, "bot_id", None) or obj_in.get("bot_id")
        coll = await self.get_collection(db, bot_id)
        update_data = {**obj_in}
        for k, v in list(update_data.items()):
            if isinstance(v, uuid.UUID):
                update_data[k] = str(v)
        update_data["updated_at"] = datetime.datetime.utcnow()
        
        await coll.update_one({"_id": str(db_obj.id)}, {"$set": update_data})
        # Merge update_data into db_obj
        for k, v in update_data.items():
            setattr(db_obj, k, v)
        return db_obj

    async def remove_async(self, db: Any, *, id: Any, bot_id: Any = None) -> Optional[ModelType]:
        # Try to resolve bot_id by looking up the document first
        coll = await self.get_collection(db, bot_id)
        doc = await coll.find_one({"_id": str(id)})
        if doc:
            if not bot_id and "bot_id" in doc:
                # If we found bot_id in the document, re-get the exact collection
                coll = await self.get_collection(db, doc["bot_id"])
            await coll.delete_one({"_id": str(id)})
            return self.wrapper_class(doc)
        return None
