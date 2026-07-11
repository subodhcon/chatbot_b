import uuid
import os
from fastapi import APIRouter, Depends, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_async_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.document import Document
from app.core.config import settings
from app.core.responses import api_success_response, api_error_response

router = APIRouter()

@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a training document (PDF or DOCX) to the knowledge base securely.
    """
    try:
        from app.services.file_upload import file_upload_service

        # Save and validate using FileUploadService
        unique_name, file_path, file_size = await file_upload_service.save_file(file)

        # Create document row in MongoDB
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        from datetime import datetime
        mongo_client = mongo_registry.get_client("documents", settings.MONGODB_URL)
        doc_id = str(uuid.uuid4())
        doc_data_mongo = {
            "_id": doc_id,
            "filename": file.filename,
            "file_path": file_path,
            "file_size": file_size,
            "created_by": str(current_user.id),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        await mongo_client["chatbot"]["documents"].insert_one(doc_data_mongo)
        db_doc = Document(doc_data_mongo)

        doc_data = {
            "id": str(db_doc.id),
            "filename": db_doc.filename,
            "file_size": db_doc.file_size,
            "created_at": db_doc.created_at.isoformat(),
        }

        return api_success_response(data=doc_data, status_code=status.HTTP_201_CREATED)

    except ValueError as e:
        return api_error_response(
            message=str(e),
            code="INVALID_FILE",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while uploading the document.",
            code="DOCUMENT_UPLOAD_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )



@router.get("", status_code=status.HTTP_200_OK)
async def list_documents(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all uploaded training documents.
    """
    try:
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("documents", settings.MONGODB_URL)
        cursor = mongo_client["chatbot"]["documents"].find({"created_by": str(current_user.id)}).sort("created_at", -1)
        documents = []
        async for doc_doc in cursor:
            documents.append(Document(doc_doc))

        doc_list = [
            {
                "id": str(doc.id),
                "filename": doc.filename,
                "file_size": doc.file_size,
                "created_at": doc.created_at.isoformat(),
            }
            for doc in documents
        ]

        return api_success_response(data=doc_list)

    except Exception as e:
        return api_error_response(
            message="An error occurred while listing documents.",
            code="DOCUMENT_LIST_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.delete("/{document_id}", status_code=status.HTTP_200_OK)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a training document from DB and storage.
    """
    try:
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("documents", settings.MONGODB_URL)
        doc_doc = await mongo_client["chatbot"]["documents"].find_one({
            "_id": str(document_id),
            "created_by": str(current_user.id)
        })

        if not doc_doc:
            return api_error_response(
                message="Document not found.",
                code="DOCUMENT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        doc = Document(doc_doc)

        # Delete from disk
        if os.path.exists(doc.file_path):
            try:
                os.remove(doc.file_path)
            except Exception:
                pass

        # Delete from DB
        await mongo_client["chatbot"]["documents"].delete_many({"_id": str(document_id)})

        return api_success_response(data={"id": str(document_id), "deleted": True})

    except Exception as e:
        return api_error_response(
            message="An error occurred while deleting the document.",
            code="DOCUMENT_DELETE_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
