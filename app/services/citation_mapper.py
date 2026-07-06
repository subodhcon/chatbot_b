import re
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("app.services.citation_mapper")


class CitationMappingService:
    """
    Service to track retrieved chunks and map citation keys (e.g., [1], [2])
    found within LLM answers back to original database source metadata (PDF, DOCX, URL).
    """

    def format_chunks(self, retrieved_chunks: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str]:
        """
        Formats retrieved chunks by prefixing them with a citation key like [1], [2], etc.
        Returns:
            Tuple of:
            - List of decorated chunk dictionaries (with 'citation_key' key added).
            - A combined string formatted block ready for user prompt injection.
        """
        formatted_chunks = []
        context_lines = []

        for idx, item in enumerate(retrieved_chunks):
            # Resolve properties from VectorSearchService response structure
            chunk_data = item.get("chunk") or item
            source_data = item.get("source") or {}

            chunk_id = chunk_data.get("id")
            content = chunk_data.get("content") or ""
            source_id = source_data.get("id")
            source_name = source_data.get("source_name") or "Unknown Source"
            source_type = source_data.get("source_type") or "unknown"
            url = source_data.get("url")

            citation_index = idx + 1
            citation_key = f"[{citation_index}]"

            decorated_chunk = {
                "citation_key": citation_key,
                "citation_index": citation_index,
                "chunk_id": chunk_id,
                "content": content,
                "source_id": source_id,
                "source_name": source_name,
                "source_type": source_type,
                "url": url,
            }
            formatted_chunks.append(decorated_chunk)

            # Build a clear text boundary format for the prompt builder
            context_lines.append(
                f"--- CONTEXT BLOCK {citation_key} (Source: {source_name}, Type: {source_type}) ---\n"
                f"{content.strip()}"
            )

        context_str = "\n\n".join(context_lines) if context_lines else "No relevant context found."
        return formatted_chunks, context_str

    def extract_citations(
        self,
        answer: str,
        formatted_chunks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Parses LLM answer text to extract the citation numbers (e.g. [1], [2]).
        Maps these references to the list of decorated chunks to determine which sources were cited.
        Returns:
            Dict containing:
            - 'clean_answer': The original answer string.
            - 'citations': A list of unique dictionary items of sources cited in the response.
        """
        if not answer or not formatted_chunks:
            return {
                "clean_answer": answer or "",
                "citations": []
            }

        # Find all patterns of bracketed digits: [1], [2], [1, 2], [1][2], etc.
        # Also clean or match numbers inside brackets
        raw_matches = re.findall(r"\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]", answer)
        
        cited_indices = set()
        for match in raw_matches:
            # Handle comma-separated citations like [1, 2]
            parts = match.split(",")
            for part in parts:
                try:
                    cited_indices.add(int(part.strip()))
                except ValueError:
                    continue

        # Alternatively, handle adjacent brackets like [1][2]
        # (covered by the regex findall above since they match individually)

        cited_sources = {}
        for chunk in formatted_chunks:
            idx = chunk.get("citation_index")
            if idx in cited_indices:
                source_id = chunk.get("source_id")
                if source_id and source_id not in cited_sources:
                    # Keep track of unique cited sources
                    cited_sources[source_id] = {
                        "source_id": str(source_id),
                        "source_name": chunk.get("source_name"),
                        "source_type": chunk.get("source_type"),
                        "url": chunk.get("url"),
                    }

        return {
            "clean_answer": answer,
            "citations": list(cited_sources.values())
        }


# Module-level singleton
citation_mapping_service = CitationMappingService()
