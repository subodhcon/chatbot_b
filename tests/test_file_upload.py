import io
import pytest
from fastapi import UploadFile
from app.services.file_upload import FileUploadService

class MockFileObject(io.BytesIO):
    def __init__(self, initial_bytes=b""):
        super().__init__(initial_bytes)
        
    def seek(self, offset, whence=0):
        return super().seek(offset, whence)

@pytest.mark.asyncio
async def test_file_validation_success():
    service = FileUploadService(upload_dir="test_uploads")
    
    file_content = b"sample,csv,content\n1,2,3"
    file_obj = MockFileObject(file_content)
    
    upload_file = UploadFile(
        file=file_obj,
        filename="test.csv",
        headers={"content-type": "text/csv"}
    )
    
    ext, size = await service.validate_file(upload_file)
    assert ext == ".csv"
    assert size == len(file_content)

@pytest.mark.asyncio
async def test_file_validation_unsupported_ext():
    service = FileUploadService(upload_dir="test_uploads")
    
    file_obj = MockFileObject(b"some content")
    upload_file = UploadFile(
        file=file_obj,
        filename="malicious.exe",
        headers={"content-type": "application/octet-stream"}
    )
    
    with pytest.raises(ValueError) as exc_info:
        await service.validate_file(upload_file)
    assert "Unsupported file extension" in str(exc_info.value)

@pytest.mark.asyncio
async def test_file_validation_dangerous_double_extension():
    service = FileUploadService(upload_dir="test_uploads")
    
    file_obj = MockFileObject(b"some content")
    upload_file = UploadFile(
        file=file_obj,
        filename="test.exe.pdf",
        headers={"content-type": "application/pdf"}
    )
    
    with pytest.raises(ValueError) as exc_info:
        await service.validate_file(upload_file)
    assert "Potential malicious extension sequence detected" in str(exc_info.value)

@pytest.mark.asyncio
async def test_file_validation_null_byte():
    service = FileUploadService(upload_dir="test_uploads")
    
    file_obj = MockFileObject(b"some content")
    upload_file = UploadFile(
        file=file_obj,
        filename="test\x00.pdf",
        headers={"content-type": "application/pdf"}
    )
    
    with pytest.raises(ValueError) as exc_info:
        await service.validate_file(upload_file)
    assert "Invalid filename structure" in str(exc_info.value)

@pytest.mark.asyncio
async def test_file_validation_unsupported_mime():
    service = FileUploadService(upload_dir="test_uploads")
    
    file_obj = MockFileObject(b"some content")
    upload_file = UploadFile(
        file=file_obj,
        filename="test.pdf",
        headers={"content-type": "application/zip"} # Mismatch MIME
    )
    
    with pytest.raises(ValueError) as exc_info:
        await service.validate_file(upload_file)
    assert "Unsupported content type" in str(exc_info.value)

@pytest.mark.asyncio
async def test_file_validation_empty_file():
    service = FileUploadService(upload_dir="test_uploads")
    
    file_obj = MockFileObject(b"")
    upload_file = UploadFile(
        file=file_obj,
        filename="test.pdf",
        headers={"content-type": "application/pdf"}
    )
    
    with pytest.raises(ValueError) as exc_info:
        await service.validate_file(upload_file)
    assert "File is empty" in str(exc_info.value)

def test_unique_filename_generation():
    service = FileUploadService(upload_dir="test_uploads")
    filename = "../../../etc/passwd.pdf"
    unique_name = service.generate_unique_filename(filename)
    
    assert ".." not in unique_name
    assert "/" not in unique_name
    assert unique_name.endswith(".pdf")
