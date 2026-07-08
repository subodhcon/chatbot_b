import pytest
from app.services.confidence_score import confidence_score_service

def test_hallucination_empty_answer_or_fallback():
    # If the answer is empty or matches fallback message, grounding/answer confidence should be 0.0
    fallback = "I am sorry, I cannot answer that."
    
    result = confidence_score_service.calculate_confidence(
        retrieved_chunks=[{"content": "The sky is blue."}],
        answer="I am sorry, I cannot answer that.",
        fallback_message=fallback
    )
    
    assert result["answer_confidence"] == 0.0
    assert result["combined_confidence"] == 0.0

def test_hallucination_high_grounding_overlap():
    # If all keywords in the answer overlap with the retrieved context chunks, answer_confidence should be 1.0 (no hallucination)
    retrieved_chunks = [
        {"content": "FastAPI is a modern, fast web framework for building APIs with Python."}
    ]
    answer = "FastAPI is a python web framework for building APIs."
    
    result = confidence_score_service.calculate_confidence(
        retrieved_chunks=retrieved_chunks,
        answer=answer,
        fallback_message="Fallback"
    )
    
    # High overlap should give high answer_confidence
    assert result["answer_confidence"] > 0.8

def test_hallucination_high_hallucination_mismatch():
    # If the answer contains facts not mentioned in the context (hallucination), answer_confidence should be low
    retrieved_chunks = [
        {"content": "FastAPI is a modern, fast web framework for building APIs with Python."}
    ]
    answer = "FastAPI was created by Microsoft in Seattle and is written in Ruby."
    
    result = confidence_score_service.calculate_confidence(
        retrieved_chunks=retrieved_chunks,
        answer=answer,
        fallback_message="Fallback"
    )
    
    # Significant hallucination/mismatch should lower the grounding confidence score
    assert result["answer_confidence"] < 0.4


def test_general_knowledge_hallucination():
    # User's uploaded knowledge context
    gk_knowledge = (
        "General Knowledge – 10 Questions and Answers\n"
        "1. What is the capital of India?\n"
        "Answer: New Delhi is the capital of India.\n"
        "2. Who is known as the Father of the Nation in India?\n"
        "Answer: Mahatma Gandhi is known as the Father of the Nation.\n"
        "3. What is the largest planet in our Solar System?\n"
        "Answer: Jupiter is the largest planet in the Solar System.\n"
        "4. What is the national animal of India?\n"
        "Answer: The Bengal Tiger is the national animal of India.\n"
        "5. Which language is used for web page structure?\n"
        "Answer: HTML is used for web page structure.\n"
        "6. What does CPU stand for?\n"
        "Answer: Central Processing Unit.\n"
        "7. Which company developed Windows?\n"
        "Answer: Microsoft developed Windows.\n"
        "8. What is the full form of AI?\n"
        "Answer: Artificial Intelligence.\n"
        "9. What is the boiling point of water?\n"
        "Answer: 100°C at standard atmospheric pressure.\n"
        "10. Who invented the telephone?\n"
        "Answer: Alexander Graham Bell is credited with inventing the telephone."
    )

    retrieved_chunks = [{"content": gk_knowledge}]

    # Case 1: Grounded answer (No Hallucination)
    grounded_answer = "New Delhi is the capital of India. Mahatma Gandhi is known as the Father of the Nation."
    res_grounded = confidence_score_service.calculate_confidence(
        retrieved_chunks=retrieved_chunks,
        answer=grounded_answer,
        fallback_message="Fallback"
    )
    # Grounded keywords (New, Delhi, capital, India, Mahatma, Gandhi, Father, Nation) all overlap perfectly
    assert res_grounded["answer_confidence"] > 0.8

    # Case 2: Hallucinated Answer (Incorrect facts)
    hallucinated_answer = "Mumbai is the capital of India. Netaji Subhas Chandra Bose is known as the Father of the Nation."
    res_hallucinated = confidence_score_service.calculate_confidence(
        retrieved_chunks=retrieved_chunks,
        answer=hallucinated_answer,
        fallback_message="Fallback"
    )
    # "Mumbai", "Netaji", "Subhas", "Chandra", "Bose" are hallucinations not present in the context.
    # Therefore, the confidence score should be significantly lower than the grounded case.
    assert res_hallucinated["answer_confidence"] < 0.6
    assert res_hallucinated["answer_confidence"] < res_grounded["answer_confidence"]

