# Import all the models, so that Base has them before being
# imported by Alembic or database engines.
from app.db.base_class import Base  # noqa
from app.models.user import User  # noqa
from app.models.bot import Bot  # noqa
from app.models.bot_version import BotVersion  # noqa
from app.models.bot_config import BotConfig  # noqa
from app.models.conversation import Conversation, Message  # noqa
from app.models.document import Document  # noqa
from app.models.widget_session import WidgetSession, WidgetSessionStatus  # noqa
from app.models.analytics_event import AnalyticsEvent  # noqa
from app.models.feedback_rating import FeedbackRating  # noqa
from app.models.knowledge_source import KnowledgeSource  # noqa
from app.models.ingestion_job import IngestionJob  # noqa
from app.models.url_crawl import UrlCrawl  # noqa
from app.models.export_job import ExportJob  # noqa
from app.models.audit_log import AuditLog  # noqa
from app.models.bot_manager import BotManager  # noqa




