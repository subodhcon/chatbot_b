# Import all the models, so that Base has them before being
# imported by Alembic or database engines.
from app.db.base_class import Base  # noqa
from app.models.user import User  # noqa
from app.models.bot import Bot  # noqa
from app.models.bot_version import BotVersion  # noqa
from app.models.bot_config import BotConfig  # noqa
from app.models.audit_log import AuditLog  # noqa
from app.models.bot_manager import BotManager  # noqa
