from typing import Optional, Any, Dict, Union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.repositories.base import BaseRepository
from app.models.user import User

class UserRepository(BaseRepository[User]):
    """
    User-specific data repository layer.
    Inherits sync and async base query operations from BaseRepository.
    """
    def __init__(self) -> None:
        super().__init__(User)

    async def get_user_by_id(self, db: AsyncSession, id: Any) -> Optional[User]:
        """
        Fetch a user by their UUID primary key.
        """
        return await self.get_async(db, id)

    async def get_user_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        """
        Query a user record by their unique email address (case-insensitive).
        """
        normalized_email = email.strip().lower() if email else ""
        result = await db.execute(select(User).filter(User.email == normalized_email))
        return result.scalars().first()

    async def create_user(self, db: AsyncSession, *, obj_in: Dict[str, Any]) -> User:
        """
        Insert a new user record into the database.
        """
        return await self.create_async(db, obj_in=obj_in)

    async def update_user(
        self, db: AsyncSession, *, db_obj: User, obj_in: Union[Dict[str, Any], Any]
    ) -> User:
        """
        Update fields of an existing user record.
        """
        return await self.update_async(db, db_obj=db_obj, obj_in=obj_in)

    async def delete_user(self, db: AsyncSession, *, id: Any) -> Optional[User]:
        """
        Delete a user record by their UUID.
        """
        return await self.remove_async(db, id=id)

user_repository = UserRepository()
