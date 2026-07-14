import logging
import re
from typing import List, Dict, Any
import tiktoken

logger = logging.getLogger("app.services.document_chunking")


class DocumentChunkingService:
    """
    Service for partitioning extracted text into structured, overlapping chunks
    while preserving paragraph and sentence boundaries based on token counts.
    """

    def chunk_text(
        self,
        text: str,
        chunk_size: int = 3000,
        overlap: int = 600,
    ) -> List[Dict[str, Any]]:
        """
        Partitions input text into overlapping chunks based on tokens.
        If parameters look like character counts (e.g. default 3000/600),
        they are automatically scaled to approximate token values.
        """
        if not text:
            return []

        # Scale character parameters to approximate tokens if necessary
        if chunk_size >= 1500:
            chunk_size = max(100, chunk_size // 4)
        if overlap >= 300:
            overlap = max(0, overlap // 4)

        if chunk_size <= 0:
            raise ValueError("Chunk size must be greater than 0.")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("Overlap must be non-negative and less than chunk size.")

        try:
            encoding = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.warning(f"Failed to load tiktoken encoding; falling back to word counts: {e}")
            encoding = None

        def get_token_count(t: str) -> int:
            if encoding:
                return len(encoding.encode(t))
            return len(t.split())

        # Split text into segments: paragraphs, newlines, and sentences
        raw_segments = re.split(r'(\n\n|\n|\. |\? |\! )', text)
        
        # Reconstruct segments to keep separators with preceding text
        segments = []
        temp = ""
        for item in raw_segments:
            if not item:
                continue
            if item in ["\n\n", "\n", ". ", "? ", "! "]:
                temp += item
                segments.append(temp)
                temp = ""
            else:
                if temp:
                    segments.append(temp)
                temp = item
        if temp:
            segments.append(temp)

        # Filter out empty segments
        segments = [s for s in segments if s.strip()]
        if not segments:
            return []

        chunks = []
        current_chunk_segments = []
        current_chunk_tokens = 0
        chunk_idx = 0

        for segment in segments:
            seg_tokens = get_token_count(segment)
            
            # If a single segment is larger than the chunk size, split it directly
            if seg_tokens > chunk_size:
                if current_chunk_segments:
                    content = "".join(current_chunk_segments).strip()
                    if content:
                        chunks.append({
                            "chunk_index": chunk_idx,
                            "content": content,
                            "token_count": current_chunk_tokens
                        })
                        chunk_idx += 1
                    current_chunk_segments = []
                    current_chunk_tokens = 0
                
                # Split large segment by tokens/words
                if encoding:
                    seg_token_ids = encoding.encode(segment)
                    start_idx = 0
                    while start_idx < len(seg_token_ids):
                        end_idx = min(start_idx + chunk_size, len(seg_token_ids))
                        chunk_ids = seg_token_ids[start_idx:end_idx]
                        chunk_text = encoding.decode(chunk_ids)
                        chunks.append({
                            "chunk_index": chunk_idx,
                            "content": chunk_text.strip(),
                            "token_count": len(chunk_ids)
                        })
                        chunk_idx += 1
                        start_idx = end_idx - overlap if end_idx < len(seg_token_ids) else end_idx
                else:
                    words = segment.split()
                    start_idx = 0
                    while start_idx < len(words):
                        end_idx = min(start_idx + chunk_size, len(words))
                        chunk_text = " ".join(words[start_idx:end_idx])
                        chunks.append({
                            "chunk_index": chunk_idx,
                            "content": chunk_text.strip(),
                            "token_count": end_idx - start_idx
                        })
                        chunk_idx += 1
                        start_idx = end_idx - overlap if end_idx < len(words) else end_idx
                continue

            # If adding this segment exceeds chunk_size, output the current chunk
            if current_chunk_tokens + seg_tokens > chunk_size:
                content = "".join(current_chunk_segments).strip()
                if content:
                    chunks.append({
                        "chunk_index": chunk_idx,
                        "content": content,
                        "token_count": current_chunk_tokens
                    })
                    chunk_idx += 1
                
                # Implement overlap backtracking
                overlap_segments = []
                overlap_tokens = 0
                for prev_seg in reversed(current_chunk_segments):
                    prev_tokens = get_token_count(prev_seg)
                    if overlap_tokens + prev_tokens <= overlap:
                        overlap_segments.insert(0, prev_seg)
                        overlap_tokens += prev_tokens
                    else:
                        break
                
                current_chunk_segments = overlap_segments
                current_chunk_tokens = overlap_tokens

            current_chunk_segments.append(segment)
            current_chunk_tokens += seg_tokens

        # Emit the remaining chunk if any
        if current_chunk_segments:
            content = "".join(current_chunk_segments).strip()
            if content:
                chunks.append({
                    "chunk_index": chunk_idx,
                    "content": content,
                    "token_count": current_chunk_tokens
                })

        return chunks


# Module-level singleton
document_chunking_service = DocumentChunkingService()
