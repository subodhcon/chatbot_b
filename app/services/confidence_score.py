import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger("app.services.confidence_score")


class ConfidenceScoreService:
    """
    Service for calculating the confidence score of chatbot answers.
    Calculates retrieval confidence and grounding confidence, and combines them.
    """

    def calculate_confidence(
        self,
        retrieved_chunks: List[Dict[str, Any]],
        answer: str,
        fallback_message: str = None,
    ) -> Dict[str, Any]:
        """
        Calculates confidence metrics for a generated answer.
        Returns:
            Dict containing:
                - 'retrieval_confidence': float (0.0 to 1.0)
                - 'answer_confidence': float (0.0 to 1.0)
                - 'combined_confidence': float (0.0 to 1.0)
        """
        # 1. Calculate Retrieval Confidence (average of similarity scores)
        if not retrieved_chunks:
            retrieval_confidence = 0.0
        else:
            scores = []
            for item in retrieved_chunks:
                # Similarity score is present as "score" in VectorSearchService's dict
                score = item.get("score")
                if score is None:
                    # In case it is inside decorated chunk
                    score = item.get("similarity_score", 0.0)
                scores.append(float(score))
            retrieval_confidence = sum(scores) / len(scores) if scores else 0.0

        # 2. Calculate Answer Grounding Confidence
        if not answer or (fallback_message and answer.strip().lower() == fallback_message.strip().lower()):
            answer_confidence = 0.0
        else:
            # Simple keyword overlap method
            answer_words = set(re.findall(r"\w+", answer.lower()))
            
            # Common English stopwords and auxiliary/structural verbs to ignore
            stopwords = {
                "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", 
                "to", "for", "in", "on", "at", "by", "of", "with", "it", "its", 
                "this", "that", "they", "them", "you", "your", "my", "i", "we", "our",
                "can", "could", "would", "should", "will", "shall", "if", "have", "has", 
                "had", "do", "does", "did", "get", "got", "go", "make", "take", "about", 
                "more", "some", "any", "no", "not", "but", "also", "just", "very"
            }
            filtered_answer_words = answer_words - stopwords

            if not filtered_answer_words:
                answer_confidence = 1.0
            else:
                # Combine all retrieved chunk contents into a single set of lowercased words
                context_words = set()
                for item in retrieved_chunks:
                    chunk_data = item.get("chunk") or item
                    content = chunk_data.get("content") or ""
                    context_words.update(re.findall(r"\w+", content.lower()))

                grounded_words = filtered_answer_words.intersection(context_words)
                answer_confidence = len(grounded_words) / len(filtered_answer_words)

        # 3. Calculate Combined Confidence Score
        # Weighting: 40% retrieval confidence, 60% answer grounding confidence
        combined_confidence = (retrieval_confidence * 0.4) + (answer_confidence * 0.6)

        logger.info(
            f"Confidence calculated - Retrieval: {retrieval_confidence:.4f}, "
            f"Answer: {answer_confidence:.4f}, Combined: {combined_confidence:.4f}"
        )

        return {
            "retrieval_confidence": round(retrieval_confidence, 4),
            "answer_confidence": round(answer_confidence, 4),
            "combined_confidence": round(combined_confidence, 4),
        }


# Module-level singleton
confidence_score_service = ConfidenceScoreService()
