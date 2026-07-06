import os
import uuid
import logging
from typing import Tuple
from fastapi import UploadFile
from app.core.config import settings

logger = logging.getLogger("app.services.file_upload")

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB in bytes
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".csv"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/csv",
    "application/csv",
}

# Block executable, script, or system file extensions
DANGEROUS_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".bash", ".pl", ".py", ".js", ".vbs",
    ".scr", ".msi", ".jar", ".com", ".bin", ".elf", ".app"
}


class FileUploadService:
    """
    Service for handling secure document uploads (PDF, DOCX, CSV) to the Hostinger VPS uploads directory.
    """

    def __init__(self, upload_dir: str = settings.UPLOAD_DIR) -> None:
        self.upload_dir = upload_dir
        # Ensure uploads folder exists
        os.makedirs(self.upload_dir, exist_ok=True)

    async def validate_file(self, file: UploadFile) -> Tuple[str, int]:
        """
        Validates the file's extension, MIME type, size, and rejects dangerous names/extensions.
        Returns the file extension and total file size.
        Raises ValueError if validation fails.
        """
        filename = file.filename or ""

        # 1. Reject Null Bytes in filenames
        if "\x00" in filename:
            raise ValueError("Invalid filename structure.")

        # Extract extension
        _, ext = os.path.splitext(filename.lower())

        # 2. Validate Extension
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file extension: '{ext}'. "
                "Only PDF, DOCX, and CSV documents are supported."
            )

        # 3. Reject double extensions with dangerous files
        filename_lower = filename.lower()
        for dangerous in DANGEROUS_EXTENSIONS:
            if dangerous in filename_lower:
                raise ValueError("Potential malicious extension sequence detected.")

        # 4. Validate MIME Type
        content_type = file.content_type or ""
        if content_type not in ALLOWED_MIME_TYPES:
            raise ValueError(
                f"Unsupported content type: '{content_type}'. "
                "Expected application/pdf, DOCX openxml, or CSV content type."
            )

        # 5. Validate File Size robustly (seeking end-to-start)
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)

        if size > MAX_FILE_SIZE:
            size_mb = size / (1024 * 1024)
            raise ValueError(f"File size exceeds the 50MB maximum limit: {size_mb:.2f}MB.")

        if size == 0:
            raise ValueError("File is empty.")

        return ext, size

    def generate_unique_filename(self, filename: str) -> str:
        """
        Sanitizes and generates a collision-resistant unique filename using a UUID prefix.
        """
        # Strip directory path component (prevent path traversal)
        base = os.path.basename(filename)
        name_part, ext_part = os.path.splitext(base)

        # Clean special chars from basename
        safe_name = "".join(c for c in name_part if c.isalnum() or c in "._-")
        if not safe_name:
            safe_name = "uploaded_file"

        # Sanitize extension (only alphanumeric + dot)
        safe_ext = "".join(c for c in ext_part if c.isalnum() or c == ".")

        return f"{uuid.uuid4()}_{safe_name}{safe_ext}"


    async def save_file(self, file: UploadFile) -> Tuple[str, str, int]:
        """
        Validates, renames, and saves the uploaded file to the VPS uploads directory.
        Returns a tuple containing: (unique_filename, file_path, file_size).
        """
        # Validate file properties
        _, file_size = await self.validate_file(file)

        # Generate unique path
        unique_name = self.generate_unique_filename(file.filename or "document")
        file_path = os.path.join(self.upload_dir, unique_name)

        logger.info(f"Saving uploaded file to destination: {file_path}")
        try:
            # Read and write in 1MB chunks to keep memory usage low for large files
            with open(file_path, "wb") as buffer:
                while chunk := await file.read(1024 * 1024):
                    buffer.write(chunk)
        except Exception as e:
            logger.error(f"Failed to write uploaded file to disk: {e}")
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
            raise IOError("An error occurred while saving the uploaded document to storage.") from e

        return unique_name, file_path, file_size


# Module-level singleton
file_upload_service = FileUploadService()
