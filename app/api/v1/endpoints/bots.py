import uuid
from typing import Any
from fastapi import APIRouter, Depends, status, Request, File, UploadFile, BackgroundTasks
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession
import os
from datetime import datetime
from app.core.config import settings

from app.db.session import get_async_db
from app.dependencies import get_current_user, has_bot_access
from app.utils.redis import get_redis
from app.models.user import User
from app.schemas.bot import (
    BotCreate,
    BotUpdate,
    BotResponse,
    BotDeleteConfirm,
    BotConfigUpdateRequest,
    BotConfigResponse,
    BotVersionResponse,
    BotConfigUpdateResponse,
    BotVersionRestoreResponse,
)
from app.services.bot import bot_service
from app.core.responses import api_success_response, api_error_response
from app.services.file_upload import file_upload_service
from app.services.source_purge import source_purge_service
from app.services.audit import audit_service
from app.core.security import encrypt_string
from app.utils.cache import get_cached_val, set_cached_val, invalidate_cache
from app.models.knowledge_source import KnowledgeSource, KnowledgeSourceType, KnowledgeSourceStatus
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.schemas.knowledge import KnowledgeUploadResponse, KnowledgeSourceResponse, IngestionJobResponse, IngestionStatusResponse, UrlCrawlRequest, UrlCrawlResponse, BulkDeleteRequest

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /bots — create a new bot
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_bot(
    bot_in: BotCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    redis: Any = Depends(get_redis),
):
    """
    Create a new Bot owned by the authenticated user.

    Business rules enforced by the service:
    - `name` must be non-empty.
    - The user may not exceed 10 bots.
    - A slug is auto-generated from the name.
    - A default BotConfig row is created immediately.
    """
    try:
        if current_user.role != "superadmin":
            return api_error_response(
                message="Only superadmin is authorized to create chatbots.",
                code="UNAUTHORIZED",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        # Test MongoDB Connection if custom mongo details provided
        if bot_in.use_custom_mongo and bot_in.mongo_uri:
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
                test_client = AsyncIOMotorClient(bot_in.mongo_uri, serverSelectionTimeoutMS=3000)
                await test_client.admin.command("ping")
                test_client.close()
            except Exception as conn_err:
                return api_error_response(
                    message=f"Failed to connect to MongoDB with the provided URI: {str(conn_err)}. Please verify your credentials and IP whitelist.",
                    code="MONGODB_CONNECTION_FAILED",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        bot = await bot_service.create_bot(
            db,
            name=bot_in.name,
            created_by=current_user.id,
            avatar_url=bot_in.avatar_url,
            is_active=bot_in.is_active,
            use_custom_mongo=bot_in.use_custom_mongo or False,
            mongo_uri=bot_in.mongo_uri,
            mongo_db_name=bot_in.mongo_db_name,
        )
        await audit_service.log_action(
            db,
            user_id=current_user.id,
            action="bot created",
            entity_type="bot",
            entity_id=bot.id,
            metadata_={"name": bot.name, "slug": bot.slug}
        )
        await db.commit()

        # Invalidate analytics cache since active bots count changed
        await invalidate_cache(redis, f"cache:analytics_summary:{current_user.id}")

        bot_data = jsonable_encoder(BotResponse.model_validate(bot))
        return api_success_response(data=bot_data, status_code=status.HTTP_201_CREATED)

    except PermissionError as e:
        return api_error_response(
            message=str(e),
            code="BOT_LIMIT_EXCEEDED",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    except ValueError as e:
        return api_error_response(
            message=str(e),
            code="INVALID_INPUT",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while creating the bot.",
            code="BOT_CREATE_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# GET /bots — list all bots for the authenticated user
# ---------------------------------------------------------------------------

@router.get("", status_code=status.HTTP_200_OK)
async def list_bots(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return all bots owned by the authenticated user.
    Supports pagination (skip/limit) and an active_only filter.
    """
    try:
        if current_user.role == "superadmin":
            bots = await bot_service.get_all_bots(
                db,
                created_by=None,
                active_only=active_only,
                skip=skip,
                limit=limit,
            )
        else:
            bots = await bot_service.get_managed_bots(
                db,
                user_id=current_user.id,
                active_only=active_only,
                skip=skip,
                limit=limit,
            )
        bots_data = [jsonable_encoder(BotResponse.model_validate(b)) for b in bots]
        return api_success_response(data=bots_data)

    except Exception as e:
        return api_error_response(
            message="An error occurred while fetching bots.",
            code="BOT_LIST_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# GET /bots/{bot_id} — get a single bot
# ---------------------------------------------------------------------------

@router.get("/{bot_id}", status_code=status.HTTP_200_OK)
async def get_bot(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch a single Bot by UUID.
    Returns 404 if the bot does not exist or does not belong to the user.
    """
    try:
        bot = await bot_service.get_bot(db, bot_id)

        # Authorization check — verify user has creator, manager, or superadmin access
        if not await has_bot_access(db, current_user, bot_id):
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        bot_data = jsonable_encoder(BotResponse.model_validate(bot))
        return api_success_response(data=bot_data)

    except ValueError:
        return api_error_response(
            message="Bot not found.",
            code="BOT_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while fetching the bot.",
            code="BOT_FETCH_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# PATCH /bots/{bot_id} — partial update
# ---------------------------------------------------------------------------

@router.patch("/{bot_id}", status_code=status.HTTP_200_OK)
async def update_bot(
    bot_id: uuid.UUID,
    bot_in: BotUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    redis: Any = Depends(get_redis),
):
    """
    Partially update a Bot (name, avatar_url, or is_active).
    Renaming auto-regenerates the slug.
    Returns 404 if the bot does not exist or does not belong to the user.
    """
    try:
        bot = await bot_service.get_bot(db, bot_id)

        if not await has_bot_access(db, current_user, bot_id):
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        updated_bot = await bot_service.update_bot(
            db,
            bot_id=bot_id,
            obj_in=bot_in.model_dump(exclude_unset=True),
        )
        await audit_service.log_action(
            db,
            user_id=current_user.id,
            action="bot updated",
            entity_type="bot",
            entity_id=updated_bot.id,
            metadata_={"name": updated_bot.name, "slug": updated_bot.slug}
        )
        await db.commit()

        # Invalidate caches
        await invalidate_cache(redis, f"cache:analytics_summary:{current_user.id}")
        await invalidate_cache(redis, f"cache:public_bot:{bot_id}")

        bot_data = jsonable_encoder(BotResponse.model_validate(updated_bot))
        return api_success_response(data=bot_data)

    except ValueError as e:
        return api_error_response(
            message=str(e),
            code="BOT_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while updating the bot.",
            code="BOT_UPDATE_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# DELETE /bots/{bot_id} — hard delete with confirmation
# ---------------------------------------------------------------------------

@router.delete("/{bot_id}", status_code=status.HTTP_200_OK)
async def delete_bot(
    bot_id: uuid.UUID,
    confirm: BotDeleteConfirm,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    redis: Any = Depends(get_redis),
):
    """
    Hard-delete a Bot and all associated data (config, versions) via CASCADE.

    The request body must include `confirm_name` matching the bot's current
    name exactly — this prevents accidental deletions.

    Returns 400 if the confirmation name does not match.
    Returns 404 if the bot does not exist or does not belong to the user.
    """
    try:
        bot = await bot_service.get_bot(db, bot_id)

        # Only superadmins are allowed to delete chatbots
        if current_user.role != "superadmin":
            return api_error_response(
                message="Only superadmin is authorized to delete chatbots.",
                code="UNAUTHORIZED",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        # Confirmation validation — name must match exactly (case-sensitive)
        if confirm.confirm_name != bot.name:
            return api_error_response(
                message=(
                    f"Confirmation name '{confirm.confirm_name}' does not match "
                    f"the bot name '{bot.name}'. Deletion cancelled."
                ),
                code="CONFIRMATION_REQUIRED",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        await audit_service.log_action(
            db,
            user_id=current_user.id,
            action="bot deleted",
            entity_type="bot",
            entity_id=bot_id,
            metadata_={"name": bot.name}
        )
        await bot_service.delete_bot(db, bot_id=bot_id)

        # Invalidate caches
        await invalidate_cache(redis, f"cache:analytics_summary:{current_user.id}")
        await invalidate_cache(redis, f"cache:bot_config:{bot_id}")
        await invalidate_cache(redis, f"cache:public_bot:{bot_id}")

        return api_success_response(
            data={"id": str(bot_id), "deleted": True, "name": bot.name}
        )

    except ValueError:
        return api_error_response(
            message="Bot not found.",
            code="BOT_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while deleting the bot.",
            code="BOT_DELETE_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# GET /bots/{bot_id}/config — fetch live configuration
# ---------------------------------------------------------------------------

@router.get("/{bot_id}/config", status_code=status.HTTP_200_OK)
async def get_bot_config(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    redis: Any = Depends(get_redis),
):
    """
    Fetch the current live configuration for a Bot.
    Returns 404 if the bot does not exist, is not owned by the user,
    or has no configuration record yet.
    """
    try:
        cache_key = f"cache:bot_config:{bot_id}"
        cached = await get_cached_val(redis, cache_key)
        if cached is not None:
            return api_success_response(data=cached)

        bot = await bot_service.get_bot(db, bot_id)

        if not await has_bot_access(db, current_user, bot_id):
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        config = await bot_service.get_config(db, bot_id)
        config_data = jsonable_encoder(BotConfigResponse.model_validate(config))
        # Cache configuration for 2 minutes
        await set_cached_val(redis, cache_key, config_data, expire_seconds=120)

        return api_success_response(data=config_data)


    except ValueError:
        return api_error_response(
            message="Bot or configuration not found.",
            code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while fetching the configuration.",
            code="CONFIG_FETCH_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# PATCH /bots/{bot_id}/config — update config + auto version snapshot
# ---------------------------------------------------------------------------

@router.patch("/{bot_id}/config", status_code=status.HTTP_200_OK)
async def update_bot_config(
    bot_id: uuid.UUID,
    config_in: BotConfigUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    redis: Any = Depends(get_redis),
):
    """
    Update the Bot's conversational configuration and automatically create
    an immutable version snapshot of the full config state.

    Accepted fields: greeting_message, fallback_message, tone.
    All fields are optional — only supplied fields are written.

    Returns the updated config alongside the new version snapshot.
    """
    try:
        bot = await bot_service.get_bot(db, bot_id)

        if not await has_bot_access(db, current_user, bot_id):
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Map greeting_message → welcome_message (DB column name)
        raw = config_in.model_dump(exclude_unset=True)
        update_data = {}
        if "greeting_message" in raw:
            update_data["welcome_message"] = raw.pop("greeting_message")
        
        # Encrypt MongoDB URI if updated
        if "mongo_uri" in raw and raw["mongo_uri"]:
            test_uri = raw["mongo_uri"]
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
                test_client = AsyncIOMotorClient(test_uri, serverSelectionTimeoutMS=3000)
                await test_client.admin.command("ping")
                test_client.close()
            except Exception as conn_err:
                return api_error_response(
                    message=f"Failed to connect to MongoDB with the provided URI: {str(conn_err)}. Please verify your credentials and IP whitelist.",
                    code="MONGODB_CONNECTION_FAILED",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            raw["mongo_uri"] = encrypt_string(raw["mongo_uri"])

        update_data.update(raw)  # fallback_message and tone pass through as-is

        updated_config, new_version = await bot_service.update_config_with_snapshot(
            db,
            bot_id=bot_id,
            obj_in=update_data,
        )

        await audit_service.log_action(
            db,
            user_id=current_user.id,
            action="configuration updated",
            entity_type="configuration",
            entity_id=updated_config.id,
            metadata_={
                "bot_id": str(bot_id),
                "version_number": new_version.version_number
            }
        )
        await db.commit()

        # Invalidate caches
        await invalidate_cache(redis, f"cache:bot_config:{bot_id}")
        await invalidate_cache(redis, f"cache:public_bot:{bot_id}")

        response_data = jsonable_encoder(
            BotConfigUpdateResponse(
                config=BotConfigResponse.model_validate(updated_config),
                version=BotVersionResponse.model_validate(new_version),
            )
        )
        return api_success_response(data=response_data)

    except ValueError:
        return api_error_response(
            message="Bot or configuration not found.",
            code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while updating the configuration.",
            code="CONFIG_UPDATE_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# GET /bots/{bot_id}/versions — version history
# ---------------------------------------------------------------------------

@router.get("/{bot_id}/versions", status_code=status.HTTP_200_OK)
async def list_bot_versions(
    bot_id: uuid.UUID,
    skip: int = 0,
    limit: int = 30,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the version history (configuration snapshots) for a Bot.

    Results are ordered newest-first (highest version_number first).
    Defaults to the latest 30 versions; use skip/limit for pagination.

    Returns 404 if the bot does not exist or does not belong to the user.
    """
    try:
        if not await has_bot_access(db, current_user, bot_id):
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        versions = await bot_service.get_version_history(
            db,
            bot_id,
            skip=skip,
            limit=limit,
        )

        versions_data = [
            jsonable_encoder(BotVersionResponse.model_validate(v)) for v in versions
        ]
        return api_success_response(
            data={
                "bot_id": str(bot_id),
                "total_returned": len(versions_data),
                "skip": skip,
                "limit": limit,
                "versions": versions_data,
            }
        )

    except ValueError:
        return api_error_response(
            message="Bot not found.",
            code="BOT_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while fetching version history.",
            code="VERSION_HISTORY_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# POST /bots/{bot_id}/versions/{version_id}/restore — restore a snapshot
# ---------------------------------------------------------------------------

@router.post("/{bot_id}/versions/{version_id}/restore", status_code=status.HTTP_200_OK)
async def restore_bot_version(
    bot_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    redis: Any = Depends(get_redis),
):
    """
    Restore the bot's live configuration to the state captured in a
    historical version snapshot.

    History is append-only — no existing version row is ever modified.
    The restore is recorded as a brand-new version entry whose
    `snapshot_json` includes `restored_from_version` and
    `restored_from_version_id` fields for full audit traceability.

    Returns the restored live config alongside the new version entry.

    Returns 404 if the bot or version does not exist / is not owned by the user.
    Returns 403 if the version belongs to a different bot.
    """
    try:
        if not await has_bot_access(db, current_user, bot_id):
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        restored_config, new_version = await bot_service.restore_version(
            db,
            bot_id=bot_id,
            version_id=version_id,
        )
        await audit_service.log_action(
            db,
            user_id=current_user.id,
            action="configuration restored",
            entity_type="configuration",
            entity_id=restored_config.id,
            metadata_={
                "bot_id": str(bot_id),
                "version_id": str(version_id),
                "version_number": new_version.snapshot_json.get("restored_from_version", 0)
            }
        )
        await db.commit()

        # Invalidate caches
        await invalidate_cache(redis, f"cache:bot_config:{bot_id}")
        await invalidate_cache(redis, f"cache:public_bot:{bot_id}")

        response_data = jsonable_encoder(
            BotVersionRestoreResponse(
                restored_config=BotConfigResponse.model_validate(restored_config),
                new_version=BotVersionResponse.model_validate(new_version),
                restored_from_version_number=(
                    new_version.snapshot_json.get("restored_from_version", 0)
                ),
            )
        )
        return api_success_response(data=response_data)

    except PermissionError as e:
        return api_error_response(
            message=str(e),
            code="VERSION_MISMATCH",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    except ValueError as e:
        return api_error_response(
            message=str(e),
            code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while restoring the version.",
            code="VERSION_RESTORE_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# POST /bots/avatar/upload — upload bot avatar
# ---------------------------------------------------------------------------

@router.post("/avatar/upload", status_code=status.HTTP_200_OK)
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Upload an avatar image (PNG or JPG/JPEG) up to 2MB.
    Stores the file in the local uploads directory.
    Returns the public HTTP URL to access the uploaded file.
    """
    try:
        # Validate format
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in [".png", ".jpg", ".jpeg"]:
            return api_error_response(
                message="Invalid file type. Only PNG, JPG, and JPEG images are allowed.",
                code="INVALID_FILE_TYPE",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Validate size
        max_size = 2 * 1024 * 1024
        contents = await file.read()
        if len(contents) > max_size:
            return api_error_response(
                message="File size exceeds the 2MB limit. Please upload a smaller image.",
                code="FILE_TOO_LARGE",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Generate unique filename
        filename = f"{uuid.uuid4()}{ext}"
        file_path = os.path.join(settings.UPLOAD_DIR, filename)

        # Write to disk
        with open(file_path, "wb") as f:
            f.write(contents)

        # Construct full URL
        avatar_url = f"{request.base_url}uploads/{filename}"

        return api_success_response(data={"avatar_url": avatar_url})

    except Exception as e:
        return api_error_response(
            message="An error occurred while uploading the avatar.",
            code="AVATAR_UPLOAD_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# POST /bots/{bot_id}/knowledge/upload — upload bot knowledge source
# ---------------------------------------------------------------------------

@router.post("/{bot_id}/knowledge/upload", status_code=status.HTTP_201_CREATED)
async def upload_bot_knowledge(
    bot_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload training documents (PDF or DOCX) for a specific bot.
    Validates file extension, type, and size limit of 50MB.
    Creates KnowledgeSource and IngestionJob database records, returns upload metadata.
    """
    try:
        # Check if the bot exists and belongs to current user
        if not await has_bot_access(db, current_user, bot_id):
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Save and validate using FileUploadService
        try:
            unique_name, file_path, file_size = await file_upload_service.save_file(file)
        except ValueError as e:
            return api_error_response(
                message=str(e),
                code="INVALID_FILE",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except IOError as e:
            return api_error_response(
                message=str(e),
                code="STORAGE_ERROR",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Determine source type
        _, ext = os.path.splitext(file.filename.lower())
        source_type = KnowledgeSourceType.pdf if ext == ".pdf" else KnowledgeSourceType.docx

        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("bots_endpoint", settings.MONGODB_URL)
        mongo_db = mongo_client["chatbot"]
        
        source_id = str(uuid.uuid4())
        source_doc = {
            "_id": source_id,
            "bot_id": str(bot_id),
            "source_type": source_type.value if hasattr(source_type, "value") else source_type,
            "source_name": file.filename or "document",
            "file_path": file_path,
            "file_size": file_size,
            "status": "queued",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        await mongo_db["knowledge_sources"].insert_one(source_doc)
        db_source = KnowledgeSource(source_doc)
        
        job_id = str(uuid.uuid4())
        job_doc = {
            "_id": job_id,
            "source_id": source_id,
            "status": "queued",
            "progress": 0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        await mongo_db["ingestion_jobs"].insert_one(job_doc)
        db_job = IngestionJob(job_doc)

        await audit_service.log_action(
            db,
            user_id=current_user.id,
            action="source uploaded",
            entity_type="source",
            entity_id=db_source.id,
            metadata_={"bot_id": str(bot_id), "source_name": db_source.source_name, "source_type": db_source.source_type}
        )

        # Trigger background ingestion task
        from app.tasks.ingestion import ingest_knowledge_source
        if settings.ENVIRONMENT == "development":
            background_tasks.add_task(ingest_knowledge_source.run, str(db_job.id))
        else:
            try:
                ingest_knowledge_source.delay(str(db_job.id))
            except Exception as celery_err:
                import logging
                logging.getLogger("app.api.bots").warning(
                    f"Failed to queue task in Celery, falling back to FastAPI BackgroundTasks: {celery_err}"
                )
                background_tasks.add_task(ingest_knowledge_source.run, str(db_job.id))

        # Serialize using Pydantic schemas
        response_data = KnowledgeUploadResponse(
            knowledge_source=KnowledgeSourceResponse.model_validate(db_source),
            ingestion_job=IngestionJobResponse.model_validate(db_job),
        )

        return api_success_response(
            data=jsonable_encoder(response_data),
            status_code=status.HTTP_201_CREATED,
        )

    except ValueError:
        # Handling bot service get_bot failure where bot_id might not exist
        return api_error_response(
            message="Bot not found.",
            code="BOT_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while uploading knowledge source.",
            code="KNOWLEDGE_UPLOAD_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# GET /bots/{bot_id}/knowledge — list bot knowledge sources
# ---------------------------------------------------------------------------

@router.get("/{bot_id}/knowledge", status_code=status.HTTP_200_OK)
async def list_bot_knowledge(
    bot_id: uuid.UUID,
    skip: int = 0,
    limit: int = 10,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all knowledge sources uploaded for a specific bot with pagination.
    """
    try:
        # Check if the bot exists and belongs to current user
        if not await has_bot_access(db, current_user, bot_id):
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        from sqlalchemy import func

        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("bots_endpoint", settings.MONGODB_URL)
        mongo_db = mongo_client["chatbot"]
        
        # Get total count of sources for pagination metadata
        total_count = await mongo_db["knowledge_sources"].count_documents({"bot_id": str(bot_id)})

        # Compute real statistics across the entire database
        completed_total = await mongo_db["knowledge_sources"].count_documents({"bot_id": str(bot_id), "status": "completed"})
        processing_total = await mongo_db["knowledge_sources"].count_documents({"bot_id": str(bot_id), "status": {"$in": ["processing", "queued"]}})
        failed_total = await mongo_db["knowledge_sources"].count_documents({"bot_id": str(bot_id), "status": "failed"})

        active_crawls = []
        if skip == 0:
            active_crawls_cursor = mongo_db["url_crawls"].find({
                "bot_id": str(bot_id),
                "status": {"$in": ["pending", "crawling"]}
            })
            async for doc in active_crawls_cursor:
                active_crawls.append({
                    "id": doc["_id"],
                    "bot_id": doc["bot_id"],
                    "source_type": "url",
                    "source_name": f"Crawling: {doc['start_url']}",
                    "file_size": None,
                    "created_at": doc["created_at"].isoformat() if isinstance(doc["created_at"], datetime) else str(doc["created_at"]),
                    "status": doc["status"],
                    "progress": 30 if doc["status"] == "crawling" else 10,
                    "error_message": None
                })

        # Fetch offset and limited items with their progress and error messages
        cursor = mongo_db["knowledge_sources"].find({"bot_id": str(bot_id)}).sort("created_at", -1).skip(skip).limit(limit)
        sources_data = []
        async for doc in cursor:
            source = KnowledgeSource(doc)
            job_doc = await mongo_db["ingestion_jobs"].find_one({"source_id": str(source.id)}, sort=[("created_at", -1)])
            progress = job_doc.get("progress") if job_doc else None
            error_message = job_doc.get("error_message") if job_doc else None
            
            data = jsonable_encoder(KnowledgeSourceResponse.model_validate(source))
            data["progress"] = progress
            data["error_message"] = error_message
            sources_data.append(data)

        # Prepend active crawls
        sources_data = active_crawls + sources_data
        total_count += len(active_crawls)

        return api_success_response(data={
            "total": total_count,
            "skip": skip,
            "limit": limit,
            "items": sources_data,
            "stats": {
                "completed": completed_total,
                "processing": processing_total + len(active_crawls),
                "failed": failed_total
            }
        })

    except ValueError:
        return api_error_response(
            message="Bot not found.",
            code="BOT_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while listing knowledge sources.",
            code="KNOWLEDGE_LIST_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# GET /bots/{bot_id}/knowledge/{source_id}/status — ingestion status
# ---------------------------------------------------------------------------

@router.get("/{bot_id}/knowledge/{source_id}/status", status_code=status.HTTP_200_OK)
async def get_ingestion_status(
    bot_id: uuid.UUID,
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get the ingestion status for a specific knowledge source.
    Returns the knowledge source metadata alongside the latest
    ingestion job's status, progress, and error message.
    """
    try:
        # Ownership check
        if not await has_bot_access(db, current_user, bot_id):
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Use service layer to fetch combined source + job data
        from app.services.ingestion import ingestion_service
        result = await ingestion_service.get_knowledge_source_with_status(
            db,
            source_id=source_id,
            bot_id=bot_id,
        )

        source = result["source"]
        job = result["job"]

        response_data = IngestionStatusResponse(
            knowledge_source=KnowledgeSourceResponse.model_validate(source),
            ingestion_job=IngestionJobResponse.model_validate(job) if job else None,
        )

        return api_success_response(data=jsonable_encoder(response_data))

    except ValueError as e:
        return api_error_response(
            message=str(e),
            code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while fetching ingestion status.",
            code="INGESTION_STATUS_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# GET /bots/{bot_id}/knowledge/jobs/{job_id} — single ingestion job status
# ---------------------------------------------------------------------------

@router.get("/{bot_id}/knowledge/jobs/{job_id}", status_code=status.HTTP_200_OK)
async def get_ingestion_job(
    bot_id: uuid.UUID,
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a single ingestion job's status, progress, and error message by job ID.
    Validates bot ownership before returning the result.
    """
    try:
        # Ownership check
        if not await has_bot_access(db, current_user, bot_id):
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Use service layer to fetch the job
        from app.services.ingestion import ingestion_service
        job = await ingestion_service.get_job_status(db, job_id=job_id)

        # Verify that this job belongs to a source owned by this bot
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("bots_endpoint", settings.MONGODB_URL)
        source = None
        if mongo_client:
            source_doc = await mongo_client["chatbot"]["knowledge_sources"].find_one({"_id": str(job.source_id)})
            if source_doc:
                source = KnowledgeSource(source_doc)
        if not source or source.bot_id != bot_id:
            return api_error_response(
                message="Ingestion job not found for this bot.",
                code="NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        job_data = jsonable_encoder(IngestionJobResponse.model_validate(job))
        return api_success_response(data=job_data)

    except ValueError as e:
        return api_error_response(
            message=str(e),
            code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while fetching the ingestion job.",
            code="INGESTION_JOB_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# POST /bots/{bot_id}/knowledge/crawl — start URL crawl job
# ---------------------------------------------------------------------------

@router.post("/{bot_id}/knowledge/crawl", status_code=status.HTTP_202_ACCEPTED)
async def start_url_crawl(
    bot_id: uuid.UUID,
    crawl_in: UrlCrawlRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Start a URL crawl job for a specific bot.
    Validates start URL and recursion depth.
    Creates a UrlCrawl record and triggers the background Celery task.
    """
    try:
        # Check if the bot exists and belongs to current user
        if not await has_bot_access(db, current_user, bot_id):
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Validate URL schema and netloc
        from urllib.parse import urlparse
        parsed = urlparse(str(crawl_in.url))
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return api_error_response(
                message="Invalid URL. Only HTTP and HTTPS protocols are supported.",
                code="INVALID_URL",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Import UrlCrawl and UrlCrawlStatus locally
        from app.models.url_crawl import UrlCrawl, UrlCrawlStatus

        # Normalize the start URL using the service
        from app.services.url_crawl import url_crawl_service
        normalized_url = url_crawl_service.normalize_url(str(crawl_in.url))

        # Create UrlCrawl record in MongoDB
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("bots_endpoint", settings.MONGODB_URL)
        mongo_db = mongo_client["chatbot"]

        crawl_id = str(uuid.uuid4())
        source_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())

        # Create a KnowledgeSource placeholder for the crawl job
        await mongo_db["knowledge_sources"].insert_one({
            "_id": source_id,
            "bot_id": str(bot_id),
            "source_type": "url",
            "source_name": f"Web Crawl: {normalized_url}",
            "url": normalized_url,
            "file_path": None,
            "file_size": 0,
            "status": "processing",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })

        # Create an IngestionJob placeholder for tracking
        await mongo_db["ingestion_jobs"].insert_one({
            "_id": job_id,
            "source_id": source_id,
            "status": "processing",
            "progress": 10,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })

        crawl_doc = {
            "_id": crawl_id,
            "bot_id": str(bot_id),
            "start_url": normalized_url,
            "crawl_depth": crawl_in.depth,
            "status": UrlCrawlStatus.pending.value,
            "source_id": source_id,
            "job_id": job_id,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        await mongo_db["url_crawls"].insert_one(crawl_doc)
        crawl_job = UrlCrawl(crawl_doc)

        await audit_service.log_action(
            db,
            user_id=current_user.id,
            action="crawl started",
            entity_type="source",
            entity_id=crawl_job.id,
            metadata_={
                "bot_id": str(bot_id),
                "start_url": normalized_url,
                "depth": crawl_in.depth
            }
        )

        await db.commit()

        # Trigger background Celery task
        from app.tasks.ingestion import crawl_website
        if settings.ENVIRONMENT == "development":
            background_tasks.add_task(crawl_website.run, str(crawl_job.id))
        else:
            try:
                crawl_website.delay(str(crawl_job.id))
            except Exception as celery_err:
                import logging
                logging.getLogger("app.api.bots").warning(
                    f"Failed to queue crawl task in Celery, falling back to FastAPI BackgroundTasks: {celery_err}"
                )
                background_tasks.add_task(crawl_website.run, str(crawl_job.id))

        response_data = UrlCrawlResponse.model_validate(crawl_job)
        return api_success_response(
            data=jsonable_encoder(response_data),
            status_code=status.HTTP_202_ACCEPTED,
        )

    except ValueError:
        return api_error_response(
            message="Bot not found.",
            code="BOT_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while starting the crawl job.",
            code="CRAWL_START_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# DELETE /bots/{bot_id}/knowledge/{source_id} — delete knowledge source
# ---------------------------------------------------------------------------

@router.delete("/{bot_id}/knowledge/{source_id}", status_code=status.HTTP_200_OK)
async def delete_bot_knowledge(
    bot_id: uuid.UUID,
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    redis: Any = Depends(get_redis),
):
    """
    Delete a specific knowledge source and fully purge all associated data:
    - Embedding vectors removed from the vector index
    - Source text chunks removed from the database
    - Physical file removed from disk (if applicable)
    - Redis cache keys invalidated for this bot and source

    Deleted content will not appear in any future RAG retrievals.
    """
    try:
        # Check if bot exists and belongs to user
        if not await has_bot_access(db, current_user, bot_id):
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Confirm the source exists and belongs to this bot before purge
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("bots_endpoint", settings.MONGODB_URL)
        source = None
        if mongo_client:
            source_doc = await mongo_client["chatbot"]["knowledge_sources"].find_one({
                "_id": str(source_id),
                "bot_id": str(bot_id),
            })
            if source_doc:
                source = KnowledgeSource(source_doc)
        if not source:
            return api_error_response(
                message="Knowledge source not found.",
                code="NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Run full purge — vectors, chunks, DB row, file, cache
        purge_result = await source_purge_service.purge_source(
            db,
            redis,
            source_id=source_id,
            bot_id=bot_id,
            file_path=source.file_path,
        )

        await audit_service.log_action(
            db,
            user_id=current_user.id,
            action="source deleted",
            entity_type="source",
            entity_id=source_id,
            metadata_={"bot_id": str(bot_id), "source_name": source.source_name}
        )
        await db.commit()

        return api_success_response(data={"deleted": True, **purge_result})

    except ValueError:
        return api_error_response(
            message="Bot not found.",
            code="BOT_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while deleting the knowledge source.",
            code="KNOWLEDGE_DELETE_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# POST /bots/{bot_id}/knowledge/bulk-delete — bulk delete knowledge sources
# ---------------------------------------------------------------------------

@router.post("/{bot_id}/knowledge/bulk-delete", status_code=status.HTTP_200_OK)
async def bulk_delete_bot_knowledge(
    bot_id: uuid.UUID,
    delete_in: BulkDeleteRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    redis: Any = Depends(get_redis),
):
    """
    Bulk delete specified knowledge sources and fully purge all associated data
    for each source:
    - Embedding vectors removed from the vector index
    - Source text chunks removed from the database
    - Physical files removed from disk (where applicable)
    - Redis cache keys invalidated per bot and source

    Deleted content will not appear in any future RAG retrievals.
    """
    try:
        # Check if bot exists and belongs to user
        if not await has_bot_access(db, current_user, bot_id):
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not delete_in.source_ids:
            return api_success_response(data={
                "deleted_count": 0,
                "source_ids": [],
                "total_chunks_deleted": 0,
                "total_vectors_deleted": 0,
            })

        # Fetch all specified knowledge sources that belong to this bot from MongoDB
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("bots_endpoint", settings.MONGODB_URL)
        sources = []
        if mongo_client:
            cursor = mongo_client["chatbot"]["knowledge_sources"].find({
                "_id": {"$in": [str(sid) for sid in delete_in.source_ids]},
                "bot_id": str(bot_id),
            })
            async for doc in cursor:
                sources.append(KnowledgeSource(doc))

        deleted_ids = []
        total_chunks = 0
        total_vectors = 0

        for source in sources:
            purge_result = await source_purge_service.purge_source(
                db,
                redis,
                source_id=source.id,
                bot_id=bot_id,
                file_path=source.file_path,
            )
            deleted_ids.append(purge_result["source_id"])
            total_chunks += purge_result["chunks_deleted"]
            total_vectors += purge_result["vectors_deleted"]
            await audit_service.log_action(
                db,
                user_id=current_user.id,
                action="source deleted",
                entity_type="source",
                entity_id=source.id,
                metadata_={"bot_id": str(bot_id), "source_name": source.source_name}
            )
        await db.commit()

        return api_success_response(
            data={
                "deleted_count": len(deleted_ids),
                "source_ids": deleted_ids,
                "total_chunks_deleted": total_chunks,
                "total_vectors_deleted": total_vectors,
            }
        )

    except ValueError:
        return api_error_response(
            message="Bot not found.",
            code="BOT_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while bulk deleting knowledge sources.",
            code="KNOWLEDGE_BULK_DELETE_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )



