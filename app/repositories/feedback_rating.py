import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import BaseRepository
from app.models.feedback_rating import FeedbackRating, FeedbackRatingValue


class FeedbackRatingRepository(BaseRepository[FeedbackRating]):
    """
    Repository layer for managing thumbs up/down user feedback ratings.
    """

    def __init__(self) -> None:
        super().__init__(FeedbackRating)

    async def create_rating(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        rating: FeedbackRatingValue,
        feedback_text: Optional[str] = None,
    ) -> FeedbackRating:
        """
        Inserts a new feedback rating, or updates an existing one if it exists.
        """
        from sqlalchemy import select
        query = (
            select(FeedbackRating)
            .where(FeedbackRating.conversation_id == conversation_id)
            .where(FeedbackRating.message_id == message_id)
        )
        res = await db.execute(query)
        existing = res.scalar_one_or_none()

        if existing:
            existing.rating = rating
            existing.feedback_text = feedback_text
            await db.commit()
            await db.refresh(existing)
            return existing

        obj_in = {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "rating": rating,
            "feedback_text": feedback_text,
        }
        return await self.create_async(db, obj_in=obj_in)


# Module-level singleton
feedback_rating_repository = FeedbackRatingRepository()
