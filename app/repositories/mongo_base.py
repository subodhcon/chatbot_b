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

    async def get_collection(self):
        mongo_client = mongo_registry.get_client("repositories", settings.MONGODB_URL)
        return mongo_client["chatbot"][self.collection_name]

    async def get_async(self, db: Any, id: Any) -> Optional[ModelType]:
        coll = await self.get_collection()
        doc = await coll.find_one({"_id": str(id)})
        return self.wrapper_class(doc) if doc else None

    async def get_multi_async(self, db: Any, *, skip: int = 0, limit: int = 100) -> List[ModelType]:
        coll = await self.get_collection()
        cursor = coll.find({}).skip(skip).limit(limit)
        results = []
        async for doc in cursor:
            results.append(self.wrapper_class(doc))
        return results

    async def create_async(self, db: Any, *, obj_in: Dict[str, Any]) -> ModelType:
        coll = await self.get_collection()
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
        coll = await self.get_collection()
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

    async def remove_async(self, db: Any, *, id: Any) -> Optional[ModelType]:
        coll = await self.get_collection()
        doc = await coll.find_one({"_id": str(id)})
        if doc:
            await coll.delete_one({"_id": str(id)})
            return self.wrapper_class(doc)
        return None
