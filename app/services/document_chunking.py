import logging
from typing import List, Dict, Any

logger = logging.getLogger("app.services.document_chunking")


class DocumentChunkingService:
    """
    Service for partitioning extracted text into structured, overlapping chunks
    while preserving paragraph and sentence boundaries.
    """

    def chunk_text(
        self,
        text: str,
        chunk_size: int = 1000,
        overlap: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Partitions input text into overlapping chunks.
        Returns a list of dictionaries containing:
            - chunk_index: index of the chunk (0-indexed)
            - content: chunk text
            - token_count: word count or character length of the content (simple character count or word splits)
        """
        if not text:
            return []

        if chunk_size <= 0:
            raise ValueError("Chunk size must be greater than 0.")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("Overlap must be non-negative and less than chunk size.")

        chunks = []
        text_len = len(text)
        start = 0

        chunk_idx = 0
        while start < text_len:
            # Determine initial end index
            end = min(start + chunk_size, text_len)

            # If we are not at the end of the text, try to find a natural boundary to split on
            if end < text_len:
                # Search backwards for paragraph breaks first, then line breaks, then sentence breaks, then space
                boundary_found = False
                for separator in ["\n\n", "\n", ". ", " "]:
                    # Search within the overlap window to avoid making chunks too small
                    search_start = max(start, end - overlap)
                    last_sep_idx = text.rfind(separator, search_start, end)
                    
                    if last_sep_idx != -1:
                        # Split at the separator
                        end = last_sep_idx + len(separator)
                        boundary_found = True
                        break
                
                # If no boundary is found, we fall back to splitting exactly at chunk_size

            content = text[start:end].strip()
            if content:
                chunks.append({
                    "chunk_index": chunk_idx,
                    "content": content,
                    "token_count": len(content.split()),
                })
                chunk_idx += 1

            # Move start pointer forward, accounting for overlap
            next_start = end - overlap
            if next_start <= start:
                start = end
            else:
                start = next_start

        return chunks


# Module-level singleton
document_chunking_service = DocumentChunkingService()
