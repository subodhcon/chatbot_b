import uuid
from typing import Optional
from app.repositories.mongo_base import MongoBaseRepository
from app.models.feedback_rating import FeedbackRating, FeedbackRatingValue


class FeedbackRatingRepository(MongoBaseRepository):
    """
    Repository layer for managing thumbs up/down user feedback ratings in MongoDB.
    """

    def __init__(self) -> None:
        super().__init__("feedback_ratings", FeedbackRating)

    async def create_rating(
        self,
        db,
        *,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        rating: FeedbackRatingValue,
        feedback_text: Optional[str] = None,
    ) -> FeedbackRating:
        """
        Inserts a new feedback rating, or updates an existing one if it exists.
        """
        coll = await self.get_collection()
        doc = await coll.find_one({
            "conversation_id": str(conversation_id),
            "message_id": str(message_id)
        })
        rating_val = rating.value if hasattr(rating, "value") else rating

        if doc:
            db_obj = FeedbackRating(doc)
            return await self.update_async(db, db_obj=db_obj, obj_in={
                "rating": rating_val,
                "feedback_text": feedback_text
            })

        obj_in = {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "rating": rating_val,
            "feedback_text": feedback_text,
        }
        return await self.create_async(db, obj_in=obj_in)


# Module-level singleton
feedback_rating_repository = FeedbackRatingRepository()
