import os
import logging
from typing import Dict, Any, List
import fitz  # PyMuPDF

logger = logging.getLogger("app.services.pdf_extraction")


class PDFExtractionService:
    """
    Service for extracting structured text and metadata from PDF documents using PyMuPDF.
    """

    def extract_pdf_content(self, file_path: str) -> Dict[str, Any]:
        """
        Extracts metadata and text from a PDF file.
        Returns a structured dictionary containing metadata, page-by-page text, and full text.
        Raises ValueError if the PDF is corrupted, password-protected, or unreadable.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found at path: {file_path}")

        doc = None
        try:
            # Open PDF document
            doc = fitz.open(file_path)

            if doc.is_encrypted:
                raise ValueError("PDF file is encrypted or password-protected.")

            # Validate page count
            page_count = len(doc)
            if page_count == 0:
                raise ValueError("PDF file contains no pages.")

            # Extract document metadata
            metadata = {
                "title": doc.metadata.get("title") or "",
                "author": doc.metadata.get("author") or "",
                "subject": doc.metadata.get("subject") or "",
                "keywords": doc.metadata.get("keywords") or "",
                "creator": doc.metadata.get("creator") or "",
                "producer": doc.metadata.get("producer") or "",
                "page_count": page_count,
            }

            pages: List[Dict[str, Any]] = []
            full_text_parts: List[str] = []

            # Extract text page by page
            for page_idx in range(page_count):
                page = doc.load_page(page_idx)
                # get_text() extracts plain Unicode text
                text = page.get_text().strip()
                
                pages.append({
                    "page_number": page_idx + 1,
                    "text": text,
                    "char_count": len(text),
                    "word_count": len(text.split()),
                })
                
                if text:
                    full_text_parts.append(text)

            total_text = "\n\n".join(full_text_parts)

            return {
                "metadata": metadata,
                "pages": pages,
                "total_text": total_text,
            }

        except Exception as e:
            logger.error(f"Failed to extract text from PDF '{file_path}': {e}", exc_info=True)
            if isinstance(e, ValueError):
                raise e
            raise ValueError(f"Failed to parse PDF file. It may be corrupted or invalid. Error: {str(e)}") from e

        finally:
            # Explicitly close the fitz document to release file handles/memory
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass


# Module-level singleton
pdf_extraction_service = PDFExtractionService()
