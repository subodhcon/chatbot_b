import os
import uuid
from datetime import datetime
import logging
import json
import redis
from app.core.config import settings
from app.core.celery_app import celery_app
from app.tasks.base import BaseTask
from app.db.session import SessionLocal
from app.models.knowledge_source import KnowledgeSource, KnowledgeSourceStatus, KnowledgeSourceType
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.models.source_chunk import SourceChunk
from app.models.embedding import Embedding
from app.services.pdf_extraction import pdf_extraction_service
from app.services.docx_extraction import docx_extraction_service
from app.services.document_chunking import document_chunking_service
from app.services.openai_embeddings import openai_embedding_service

logger = logging.getLogger("app.tasks.ingestion")



def publish_ingestion_update(
    job_id: str,
    bot_id: str,
    source_id: str,
    status: str,
    progress: int,
    error_message: str = None,
) -> None:
    """
    Publishes an ingestion job update message to Redis pubsub channel.
    """
    try:
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        payload = {
            "job_id": str(job_id),
            "bot_id": str(bot_id),
            "source_id": str(source_id),
            "status": status,
            "progress": progress,
            "error_message": error_message,
        }
        r.publish("ingestion_updates", json.dumps(payload))
        logger.info(f"Published status update to Redis: {payload}")
    except Exception as e:
        logger.warning(f"Failed to publish ingestion update to Redis: {e}")


@celery_app.task(bind=True, base=BaseTask, name="app.tasks.ingestion.ingest_knowledge_source")
def ingest_knowledge_source(self, job_id: str) -> str:
    """
    Background worker task to process a queued Knowledge Source Ingestion Job.
    Reads file, detects extension, runs extraction, and updates database statuses.
    """
    logger.info(f"Starting ingestion job: {job_id}")
    db = SessionLocal()
    try:
        # 1. Fetch Job
        job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
        if not job:
            logger.error(f"IngestionJob not found: {job_id}")
            return f"Job not found: {job_id}"

        # 2. Fetch KnowledgeSource
        source = db.query(KnowledgeSource).filter(KnowledgeSource.id == job.source_id).first()
        if not source:
            logger.error(f"KnowledgeSource not found: {job.source_id} for job {job_id}")
            job.status = IngestionJobStatus.failed
            job.error_message = "Associated KnowledgeSource not found."
            job.completed_at = datetime.utcnow()
            db.commit()
            return f"Source not found: {job.source_id}"

        # 3. Update status to processing
        job.status = IngestionJobStatus.processing
        job.progress = 10
        job.started_at = datetime.utcnow()
        source.status = KnowledgeSourceStatus.processing
        db.commit()
        publish_ingestion_update(job_id, source.bot_id, source.id, "processing", 10)

        # 4. Detect file path and existence
        file_path = source.file_path
        if not file_path or not os.path.exists(file_path):
            raise ValueError(f"Source file not found at path: {file_path}")

        # Update progress to 30%
        job.progress = 30
        db.commit()
        publish_ingestion_update(job_id, source.bot_id, source.id, "processing", 30)

        # 5. Extract text based on type
        if source.source_type == KnowledgeSourceType.pdf:
            logger.info(f"Extracting PDF text from: {file_path}")
            # Execute PyMuPDF extraction
            extracted = pdf_extraction_service.extract_pdf_content(file_path)
        elif source.source_type == KnowledgeSourceType.docx:
            logger.info(f"Extracting DOCX text from: {file_path}")
            # Execute python-docx extraction
            extracted = docx_extraction_service.extract_docx_content(file_path)
        elif source.source_type == KnowledgeSourceType.url:
            logger.info(f"Ingesting crawled URL text from: {file_path}")
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Crawled text file not found: {file_path}")
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            extracted = {"total_text": text}
        else:
            raise ValueError(f"Unsupported source type for ingestion: {source.source_type}")

        # Update progress to 50% (extraction complete)
        job.progress = 50
        db.commit()
        publish_ingestion_update(job_id, source.bot_id, source.id, "processing", 50)

        # 6. Chunk text content
        text_content = extracted.get("total_text", "")
        chunks = document_chunking_service.chunk_text(text_content)

        if chunks:
            chunk_contents = [c["content"] for c in chunks]
            try:
                # Generate embeddings in a batch
                embeddings_vectors = openai_embedding_service.generate_embeddings_batch(chunk_contents)
            except Exception as embed_err:
                logger.error(f"Failed to generate embeddings during ingestion: {embed_err}")
                raise embed_err

            # Update progress to 80% (embedding complete)
            job.progress = 80
            db.commit()
            publish_ingestion_update(job_id, source.bot_id, source.id, "processing", 80)

            # Save chunks and embeddings
            for idx, c in enumerate(chunks):
                db_chunk = SourceChunk(
                    id=uuid.uuid4(),
                    source_id=source.id,
                    chunk_index=c["chunk_index"],
                    content=c["content"],
                    token_count=c["token_count"]
                )
                db.add(db_chunk)
                db.flush()  # populate db_chunk.id

                # Store matching embedding vector if generated
                if idx < len(embeddings_vectors):
                    db_emb = Embedding(
                        id=uuid.uuid4(),
                        chunk_id=db_chunk.id,
                        embedding_vector=embeddings_vectors[idx]
                    )
                    db.add(db_emb)
                    db.flush()

        # Update progress to 90% (saving complete)
        job.progress = 90
        db.commit()
        publish_ingestion_update(job_id, source.bot_id, source.id, "processing", 90)

        # 7. Complete Job
        job.status = IngestionJobStatus.completed
        job.progress = 100
        job.completed_at = datetime.utcnow()
        source.status = KnowledgeSourceStatus.completed
        db.commit()
        publish_ingestion_update(job_id, source.bot_id, source.id, "completed", 100)

        logger.info(f"Ingestion job completed successfully: {job_id}")
        return f"Successfully ingested job {job_id}"


    except Exception as e:
        logger.exception(f"Error executing ingestion job {job_id}: {e}")
        try:
            db.rollback()
            # Reload job in a fresh session block if needed to update failure status
            job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
            if job:
                job.status = IngestionJobStatus.failed
                job.progress = 100
                job.error_message = str(e)
                job.completed_at = datetime.utcnow()
                
                source = db.query(KnowledgeSource).filter(KnowledgeSource.id == job.source_id).first()
                if source:
                    source.status = KnowledgeSourceStatus.failed
                    bot_id = source.bot_id
                    source_id = source.id
                else:
                    bot_id = None
                    source_id = None
                db.commit()
                if bot_id and source_id:
                    publish_ingestion_update(job_id, bot_id, source_id, "failed", 100, str(e))
        except Exception as rollback_err:
            logger.error(f"Failed to update failed status for job {job_id}: {rollback_err}")
            
        raise e

    finally:
        db.close()


@celery_app.task(bind=True, base=BaseTask, name="app.tasks.ingestion.crawl_url_task")
def crawl_url_task(self, crawl_id: str) -> str:
    """
    Background Celery task to execute a web crawling job.
    Uses url_crawl_service to recursively fetch pages, creates KnowledgeSource
    records, and triggers ingestion jobs for each crawled page.
    """
    logger.info(f"Starting URL crawl task: {crawl_id}")
    db = SessionLocal()
    try:
        from app.models.url_crawl import UrlCrawl, UrlCrawlStatus
        from app.services.url_crawl import url_crawl_service
        import uuid
        import httpx

        # 1. Fetch Crawl record
        crawl = db.query(UrlCrawl).filter(UrlCrawl.id == crawl_id).first()
        if not crawl:
            logger.error(f"UrlCrawl record not found: {crawl_id}")
            return f"Crawl record not found: {crawl_id}"

        # 2. Update status to crawling
        crawl.status = UrlCrawlStatus.crawling
        db.commit()

        # 3. Perform Crawling
        # Check if robots.txt allows crawling the seed URL beforehand
        if not url_crawl_service.can_crawl(crawl.start_url):
            raise ValueError("Crawling this URL is disallowed by the website's robots.txt rules.")

        # Test reachability of the seed URL to capture direct errors
        try:
            resp = httpx.get(
                crawl.start_url,
                timeout=10.0,
                headers={"User-Agent": url_crawl_service.user_agent},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                raise ValueError(f"HTTP error {resp.status_code} when trying to access the URL.")
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type:
                raise ValueError("The URL may be unreachable or not return HTML.")
        except httpx.RequestError as req_err:
            raise ValueError("Failed to reach the website. Please check the URL or try again later.")

        crawled_pages = url_crawl_service.crawl(
            start_url=crawl.start_url,
            max_depth=crawl.crawl_depth
        )

        if not crawled_pages:
            raise ValueError("No content could be crawled. The URL may be unreachable or not return HTML.")

        logger.info(f"Crawl completed. Found {len(crawled_pages)} pages.")

        # 4. For each page crawled, create KnowledgeSource and IngestionJob
        for url, text in crawled_pages.items():
            filename = f"{uuid.uuid4()}_crawl.txt"
            file_path = os.path.join(settings.UPLOAD_DIR, filename)
            
            os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(text)

            source = KnowledgeSource(
                id=uuid.uuid4(),
                bot_id=crawl.bot_id,
                source_type=KnowledgeSourceType.url,
                source_name=url,
                url=url,
                file_path=file_path,
                file_size=len(text.encode("utf-8")),
                status=KnowledgeSourceStatus.queued,
            )
            db.add(source)
            db.flush()

            job = IngestionJob(
                id=uuid.uuid4(),
                source_id=source.id,
                status=IngestionJobStatus.queued,
                progress=0,
            )
            db.add(job)
            db.flush()

            db.commit()

            # Trigger background ingestion task
            ingest_knowledge_source.delay(str(job.id))

        # 5. Complete Crawl
        crawl.status = UrlCrawlStatus.completed
        db.commit()
        return f"Successfully crawled {len(crawled_pages)} pages for crawl {crawl_id}"

    except Exception as e:
        logger.exception(f"Error executing crawl job {crawl_id}: {e}")
        try:
            db.rollback()
            from app.models.url_crawl import UrlCrawl, UrlCrawlStatus
            crawl = db.query(UrlCrawl).filter(UrlCrawl.id == crawl_id).first()
            if crawl:
                crawl.status = UrlCrawlStatus.failed
                db.add(crawl)

                # Create a failed KnowledgeSource representing the seed URL
                import uuid
                from app.models.knowledge_source import KnowledgeSource, KnowledgeSourceStatus, KnowledgeSourceType
                from app.models.ingestion_job import IngestionJob, IngestionJobStatus
                
                source = KnowledgeSource(
                    id=uuid.uuid4(),
                    bot_id=crawl.bot_id,
                    source_type=KnowledgeSourceType.url,
                    source_name=crawl.start_url,
                    url=crawl.start_url,
                    file_path=None,
                    file_size=0,
                    status=KnowledgeSourceStatus.failed,
                )
                db.add(source)
                db.flush()

                job = IngestionJob(
                    id=uuid.uuid4(),
                    source_id=source.id,
                    status=IngestionJobStatus.failed,
                    progress=100,
                    error_message=str(e),
                    completed_at=datetime.utcnow(),
                )
                db.add(job)
                db.flush()
                
                db.commit()
                
                # Broadcast status update
                publish_ingestion_update(
                    job_id=str(job.id),
                    bot_id=str(crawl.bot_id),
                    source_id=str(source.id),
                    status="failed",
                    progress=100,
                    error_message=str(e),
                )
        except Exception as rollback_err:
            logger.error(f"Failed to update failed status for crawl {crawl_id}: {rollback_err}")
        raise e
    finally:
        db.close()

