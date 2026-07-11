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
import app.db.base # noqa
from app.models.knowledge_source import KnowledgeSource, KnowledgeSourceStatus, KnowledgeSourceType
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.models.url_crawl import UrlCrawl, UrlCrawlStatus
from app.services.pdf_extraction import pdf_extraction_service
from app.services.docx_extraction import docx_extraction_service
from app.services.document_chunking import document_chunking_service
from app.services.openai_embeddings import openai_embedding_service
from pymongo import MongoClient

logger = logging.getLogger("app.tasks.ingestion")


def publish_ingestion_update(
    job_id: str,
    bot_id: str,
    source_id: str,
    status: str,
    progress: int,
    error_message: str = None,
    source_name: str = None,
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
            "source_name": source_name,
        }
        r.publish("ingestion_updates", json.dumps(payload))
        logger.info(f"Published status update to Redis: {payload}")
    except Exception as e:
        logger.warning(f"Failed to publish ingestion update to Redis: {e}")


@celery_app.task(bind=True, base=BaseTask, name="app.tasks.ingestion.ingest_knowledge_source")
def ingest_knowledge_source(self, job_id: str) -> str:
    """
    Background worker task to process a queued Knowledge Source Ingestion Job.
    Reads file, detects extension, runs extraction, and updates MongoDB statuses.
    """
    logger.info(f"Starting ingestion job: {job_id}")
    mongo_client = MongoClient(settings.MONGODB_URL)
    mongo_db = mongo_client["chatbot"]
    db = SessionLocal()
    try:
        # 1. Fetch Job from MongoDB
        job_doc = mongo_db["ingestion_jobs"].find_one({"_id": str(job_id)})
        if not job_doc:
            logger.error(f"IngestionJob not found: {job_id}")
            return f"Job not found: {job_id}"
        job = IngestionJob(job_doc)

        # 2. Fetch KnowledgeSource from MongoDB
        source_doc = mongo_db["knowledge_sources"].find_one({"_id": str(job.source_id)})
        if not source_doc:
            logger.error(f"KnowledgeSource not found: {job.source_id} for job {job_id}")
            mongo_db["ingestion_jobs"].update_one(
                {"_id": str(job_id)},
                {"$set": {
                    "status": "failed",
                    "progress": 100,
                    "error_message": "Associated KnowledgeSource not found.",
                    "completed_at": datetime.utcnow()
                }}
            )
            return f"Source not found: {job.source_id}"
        source = KnowledgeSource(source_doc)

        # 3. Update status to processing in MongoDB
        mongo_db["ingestion_jobs"].update_one(
            {"_id": str(job_id)},
            {"$set": {
                "status": "processing",
                "progress": 10,
                "started_at": datetime.utcnow()
            }}
        )
        mongo_db["knowledge_sources"].update_one(
            {"_id": str(source.id)},
            {"$set": {"status": "processing"}}
        )
        job.status = IngestionJobStatus.processing
        job.progress = 10
        source.status = KnowledgeSourceStatus.processing
        publish_ingestion_update(job_id, source.bot_id, source.id, "processing", 10, source_name=source.source_name)

        # 4. Detect file path and existence
        file_path = source.file_path
        if not file_path or not os.path.exists(file_path):
            raise ValueError(f"Source file not found at path: {file_path}")

        # Update progress to 30%
        mongo_db["ingestion_jobs"].update_one(
            {"_id": str(job_id)},
            {"$set": {"progress": 30}}
        )
        job.progress = 30
        publish_ingestion_update(job_id, source.bot_id, source.id, "processing", 30, source_name=source.source_name)

        # 5. Extract text based on type
        if source.source_type == KnowledgeSourceType.pdf:
            logger.info(f"Extracting PDF text from: {file_path}")
            extracted = pdf_extraction_service.extract_pdf_content(file_path)
        elif source.source_type == KnowledgeSourceType.docx:
            logger.info(f"Extracting DOCX text from: {file_path}")
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

        # Update progress to 50%
        mongo_db["ingestion_jobs"].update_one(
            {"_id": str(job_id)},
            {"$set": {"progress": 50}}
        )
        job.progress = 50
        publish_ingestion_update(job_id, source.bot_id, source.id, "processing", 50, source_name=source.source_name)

        # 6. Chunk text content
        text_content = extracted.get("total_text", "")
        chunks = document_chunking_service.chunk_text(text_content)

        if chunks:
            chunk_contents = [c["content"] for c in chunks]
            try:
                embeddings_vectors = openai_embedding_service.generate_embeddings_batch(chunk_contents)
            except Exception as embed_err:
                logger.error(f"Failed to generate embeddings during ingestion: {embed_err}")
                raise embed_err

            # Update progress to 80%
            mongo_db["ingestion_jobs"].update_one(
                {"_id": str(job_id)},
                {"$set": {"progress": 80}}
            )
            job.progress = 80
            publish_ingestion_update(job_id, source.bot_id, source.id, "processing", 80, source_name=source.source_name)

            # Check if bot has custom MongoDB enabled
            from app.models.bot_config import BotConfig
            bot_config = db.query(BotConfig).filter(BotConfig.bot_id == source.bot_id).first()

            if bot_config and bot_config.use_custom_mongo:
                mongo_uri = bot_config.mongo_uri or settings.MONGODB_URL
                if mongo_uri:
                    logger.info(f"Routing chunks to MongoDB for bot {source.bot_id}")
                    from app.core.security import decrypt_string
                    
                    try:
                        if mongo_uri.startswith("mongodb://") or mongo_uri.startswith("mongodb+srv://"):
                            decrypted_uri = mongo_uri
                        else:
                            decrypted_uri = decrypt_string(mongo_uri)
                        
                        client = MongoClient(decrypted_uri, serverSelectionTimeoutMS=5000)
                        db_name = bot_config.mongo_db_name or "chatbot"
                        mongo_db_target = client[db_name]
                        chunks_collection = mongo_db_target["chunks"]

                        # Auto-create Atlas Search Index for Vector Search
                        try:
                            from pymongo.operations import SearchIndexModel
                            search_index = SearchIndexModel(
                                name="vector_index",
                                definition={
                                    "mappings": {
                                        "dynamic": True,
                                        "fields": {
                                            "embedding_vector": {
                                                "dimensions": 1536,
                                                "similarity": "cosine",
                                                "type": "knnVector"
                                            }
                                        }
                                    }
                                }
                            )
                            existing_indexes = list(chunks_collection.list_search_indexes())
                            if not any(idx.get("name") == "vector_index" for idx in existing_indexes):
                                chunks_collection.create_search_index(model=search_index)
                                logger.info("Successfully created/queued MongoDB Vector Search Index 'vector_index'")
                        except Exception as idx_err:
                            logger.info(f"MongoDB Search Index auto-creation (ignored if not Atlas): {idx_err}")

                        mongo_docs = []
                        for idx, c in enumerate(chunks):
                            doc = {
                                "_id": str(uuid.uuid4()),
                                "bot_id": str(source.bot_id),
                                "source_id": str(source.id),
                                "chunk_index": c["chunk_index"],
                                "content": c["content"],
                                "token_count": c["token_count"],
                                "created_at": datetime.utcnow()
                            }
                            if idx < len(embeddings_vectors):
                                doc["embedding_vector"] = embeddings_vectors[idx]
                            mongo_docs.append(doc)
                        
                        if mongo_docs:
                            chunks_collection.insert_many(mongo_docs)
                            logger.info(f"Successfully saved {len(mongo_docs)} chunks in MongoDB")
                    except Exception as mongo_err:
                        logger.error(f"Failed to save chunks in MongoDB: {mongo_err}")
                        raise mongo_err
                # Default MongoDB routing
                chunks_collection = mongo_db["chunks"]

                # Auto-create Atlas Search Index for Vector Search
                try:
                    from pymongo.operations import SearchIndexModel
                    search_index = SearchIndexModel(
                        name="vector_index",
                        definition={
                            "mappings": {
                                "dynamic": True,
                                "fields": {
                                    "embedding_vector": {
                                        "dimensions": 1536,
                                        "similarity": "cosine",
                                        "type": "knnVector"
                                    }
                                }
                            }
                        }
                    )
                    existing_indexes = list(chunks_collection.list_search_indexes())
                    if not any(idx.get("name") == "vector_index" for idx in existing_indexes):
                        chunks_collection.create_search_index(model=search_index)
                        logger.info("Successfully created/queued MongoDB Vector Search Index 'vector_index' in default DB")
                except Exception as idx_err:
                    logger.info(f"MongoDB Search Index auto-creation (ignored if not Atlas): {idx_err}")

                mongo_docs = []
                for idx, c in enumerate(chunks):
                    doc = {
                        "_id": str(uuid.uuid4()),
                        "bot_id": str(source.bot_id),
                        "source_id": str(source.id),
                        "chunk_index": c["chunk_index"],
                        "content": c["content"],
                        "token_count": c["token_count"],
                        "created_at": datetime.utcnow()
                    }
                    if idx < len(embeddings_vectors):
                        doc["embedding_vector"] = embeddings_vectors[idx]
                    mongo_docs.append(doc)
                if mongo_docs:
                    chunks_collection.insert_many(mongo_docs)
                    logger.info(f"Successfully saved {len(mongo_docs)} chunks in default MongoDB")

        # Update progress to 90% (saving complete)
        mongo_db["ingestion_jobs"].update_one(
            {"_id": str(job_id)},
            {"$set": {"progress": 90}}
        )
        publish_ingestion_update(job_id, source.bot_id, source.id, "processing", 90, source_name=source.source_name)

        # 7. Complete Job
        mongo_db["ingestion_jobs"].update_one(
            {"_id": str(job_id)},
            {"$set": {
                "status": "completed",
                "progress": 100,
                "completed_at": datetime.utcnow()
            }}
        )
        mongo_db["knowledge_sources"].update_one(
            {"_id": str(source.id)},
            {"$set": {"status": "completed"}}
        )
        publish_ingestion_update(job_id, source.bot_id, source.id, "completed", 100, source_name=source.source_name)

        logger.info(f"Ingestion job completed successfully: {job_id}")
        return f"Successfully ingested job {job_id}"

    except Exception as e:
        logger.exception(f"Error executing ingestion job {job_id}: {e}")
        try:
            mongo_db["ingestion_jobs"].update_one(
                {"_id": str(job_id)},
                {"$set": {
                    "status": "failed",
                    "progress": 100,
                    "error_message": str(e),
                    "completed_at": datetime.utcnow()
                }}
            )
            source_doc = mongo_db["knowledge_sources"].find_one({"_id": str(job.source_id)})
            if source_doc:
                mongo_db["knowledge_sources"].update_one(
                    {"_id": str(job.source_id)},
                    {"$set": {"status": "failed"}}
                )
                bot_id = source_doc.get("bot_id")
                source_id = source_doc.get("_id")
            else:
                bot_id = None
                source_id = None
            if bot_id and source_id:
                publish_ingestion_update(job_id, bot_id, source_id, "failed", 100, str(e), source_name=source_doc.get("source_name") if source_doc else None)
        except Exception as fail_err:
            logger.error(f"Failed to update failed status for job {job_id}: {fail_err}")

    finally:
        db.close()


@celery_app.task(bind=True, base=BaseTask, name="app.tasks.ingestion.crawl_website")
def crawl_website(self, crawl_id: str) -> str:
    """
    Background Celery task to execute a web crawling job.
    Uses url_crawl_service to recursively fetch pages, creates KnowledgeSource
    records, and triggers ingestion jobs for each crawled page.
    """
    logger.info(f"Starting URL crawl task: {crawl_id}")
    mongo_client = MongoClient(settings.MONGODB_URL)
    mongo_db = mongo_client["chatbot"]
    try:
        from app.models.url_crawl import UrlCrawl, UrlCrawlStatus
        from app.services.url_crawl import url_crawl_service
        import uuid
        import httpx

        # 1. Fetch Crawl record from MongoDB
        crawl_doc = mongo_db["url_crawls"].find_one({"_id": str(crawl_id)})
        if not crawl_doc:
            logger.error(f"UrlCrawl record not found: {crawl_id}")
            return f"Crawl record not found: {crawl_id}"
        crawl = UrlCrawl(crawl_doc)

        # 2. Update status to crawling
        mongo_db["url_crawls"].update_one(
            {"_id": str(crawl_id)},
            {"$set": {"status": "crawling"}}
        )
        # Notify frontend via WebSocket that crawl has started
        publish_ingestion_update(
            job_id=str(crawl_id),
            bot_id=str(crawl.bot_id),
            source_id=str(crawl_id),
            status="crawling",
            progress=5,
            source_name=f"Crawling: {crawl.start_url}",
        )

        # 3. Perform Crawling
        if not url_crawl_service.can_crawl(crawl.start_url):
            raise ValueError("Crawling this URL is disallowed by the website's robots.txt rules.")

        # Test reachability of the seed URL
        try:
            resp = httpx.get(
                crawl.start_url,
                timeout=10.0,
                headers={
                    "User-Agent": url_crawl_service.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1"
                },
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

            source_id = str(uuid.uuid4())
            mongo_db["knowledge_sources"].insert_one({
                "_id": source_id,
                "bot_id": str(crawl.bot_id),
                "source_type": "url",
                "source_name": url,
                "url": url,
                "file_path": file_path,
                "file_size": len(text.encode("utf-8")),
                "status": "queued",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })

            job_id = str(uuid.uuid4())
            mongo_db["ingestion_jobs"].insert_one({
                "_id": job_id,
                "source_id": source_id,
                "status": "queued",
                "progress": 0,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })

            # Trigger background ingestion task
            if settings.ENVIRONMENT == "development":
                ingest_knowledge_source.run(job_id)
            else:
                ingest_knowledge_source.delay(job_id)

        # 5. Complete Crawl
        mongo_db["url_crawls"].update_one(
            {"_id": str(crawl_id)},
            {"$set": {"status": "completed"}}
        )
        # Notify frontend via WebSocket that crawl completed — triggers re-fetch
        publish_ingestion_update(
            job_id=str(crawl_id),
            bot_id=str(crawl.bot_id),
            source_id=str(crawl_id),
            status="completed",
            progress=100,
            source_name=f"Crawling: {crawl.start_url}",
        )
        return f"Successfully crawled {len(crawled_pages)} pages for crawl {crawl_id}"

    except Exception as e:
        logger.exception(f"Error executing crawl job {crawl_id}: {e}")
        try:
            mongo_db["url_crawls"].update_one(
                {"_id": str(crawl_id)},
                {"$set": {"status": "failed"}}
            )
            # Notify frontend about the failure
            if 'crawl' in locals() and crawl:
                publish_ingestion_update(
                    job_id=str(crawl_id),
                    bot_id=str(crawl.bot_id),
                    source_id=str(crawl_id),
                    status="failed",
                    progress=0,
                    source_name=f"Crawling: {crawl.start_url}",
                    error_message=str(e),
                )
            # Create a failed KnowledgeSource representing the seed URL
            source_id = str(uuid.uuid4())
            mongo_db["knowledge_sources"].insert_one({
                "_id": source_id,
                "bot_id": str(crawl.bot_id) if 'crawl' in locals() and crawl else None,
                "source_type": "url",
                "source_name": crawl.start_url if 'crawl' in locals() and crawl else "Web Crawl",
                "url": crawl.start_url if 'crawl' in locals() and crawl else "",
                "file_path": None,
                "file_size": 0,
                "status": "failed",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })

            job_id = str(uuid.uuid4())
            mongo_db["ingestion_jobs"].insert_one({
                "_id": job_id,
                "source_id": source_id,
                "status": "failed",
                "progress": 100,
                "error_message": str(e),
                "completed_at": datetime.utcnow(),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
        except Exception as rollback_err:
            logger.error(f"Failed to update failed status for crawl {crawl_id}: {rollback_err}")
