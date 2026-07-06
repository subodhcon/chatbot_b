import uuid
import logging
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit_log import AuditLog

logger = logging.getLogger("app.services.audit")


class AuditService:
    """
    AuditService handles persistence of security/administrative audit events.
    """

    async def log_action(
        self,
        db: AsyncSession,
        *,
        user_id: Optional[uuid.UUID],
        action: str,
        entity_type: str,
        entity_id: Optional[uuid.UUID] = None,
        metadata_: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        """
        Create and record an administrative audit log.
        This writes to the db transaction but does not commit, allowing the action
        and the audit log to succeed or fail atomically.
        """
        try:
            log = AuditLog(
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                metadata_=metadata_,
            )
            db.add(log)
            logger.info(
                f"Audit logged: user_id={user_id} action={action} "
                f"entity_type={entity_type} entity_id={entity_id}"
            )
            return log
        except Exception as e:
            logger.error(f"Failed to create audit log for action '{action}': {e}")
            raise e


# Module-level singleton
audit_service = AuditService()
