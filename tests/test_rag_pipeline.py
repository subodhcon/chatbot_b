import pytest
from unittest.mock import MagicMock
from app.services.prompt_builder import PromptBuilderService
from app.services.confidence_score import confidence_score_service

def test_pandas_vs_pads_prompt_rules():
    """
    Test 1: Verify prompt_builder strictly includes instruction to separate 
    Pandas (priests) and Pads (places).
    """
    builder = PromptBuilderService()
    
    system_prompt = builder.build_system_prompt(
        base_system_prompt="Test persona",
        tone="professional",
        welcome_message="Hello",
        fallback_message="Fallback message"
    )
    
    # Assert that our distinction rule is present in the prompt
    assert "Distinguish carefully between 'Pandits' (Panda ji/Priests/People" in system_prompt
    assert "and 'Pads' (Pinddaan sthal/places/temples" in system_prompt
    assert "Do NOT list places when the user asks for Panda/Priest lists" in system_prompt

def test_list_formatting_rules():
    """
    Test 2: Verify prompt_builder strictly enforces markdown list formatting.
    """
    builder = PromptBuilderService()
    system_prompt = builder.build_system_prompt(
        base_system_prompt="Test persona",
        tone="professional",
        welcome_message="Hello",
        fallback_message="Fallback message"
    )
    
    assert "format them as a clean bulleted list" in system_prompt
    assert "using Markdown '*' or '-'" in system_prompt

def test_rag_semantic_matching_pandas():
    """
    Test 3: Verify confidence evaluator rates answers containing Pandas correctly
    when context contains Pandits list.
    """
    retrieved_chunks = [
        {"content": "Pandit Ji List: 131. Kanhaiya Lal Dubhalia, 132. Kanhaiya Lal Nakfofa, 133. Kanhaiya Lal Pathak"}
    ]
    
    # Answer strictly listing Pandas (No Places) - Grounded
    grounded_answer = "- Kanhaiya Lal Dubhalia\n- Kanhaiya Lal Nakfofa\n- Kanhaiya Lal Pathak"
    res_grounded = confidence_score_service.calculate_confidence(
        retrieved_chunks=retrieved_chunks,
        answer=grounded_answer,
        fallback_message="Fallback"
    )
    
    # Answer incorrectly listing Places instead of Pandas (Hallucination)
    hallucinated_answer = "- VishnuPad Temple\n- Dev Ghat\n- Kaach Pad"
    res_hallucinated = confidence_score_service.calculate_confidence(
        retrieved_chunks=retrieved_chunks,
        answer=hallucinated_answer,
        fallback_message="Fallback"
    )
    
    # Assert that the correct response has much higher confidence than the hallucination
    assert res_grounded["answer_confidence"] > 0.7
    assert res_hallucinated["answer_confidence"] < 0.3
    assert res_hallucinated["answer_confidence"] < res_grounded["answer_confidence"]

def test_rag_semantic_matching_places():
    """
    Test 4: Verify confidence evaluator rates places queries correctly.
    """
    retrieved_chunks = [
        {"content": "Pinddaan Sthals (Places): VishnuPad Temple, Dev Ghat, Kaach Pad"}
    ]
    
    # Grounded answer listing places
    grounded_answer = "- VishnuPad Temple\n- Dev Ghat\n- Kaach Pad"
    res_grounded = confidence_score_service.calculate_confidence(
        retrieved_chunks=retrieved_chunks,
        answer=grounded_answer,
        fallback_message="Fallback"
    )
    
    # Hallucinated answer listing priests instead
    hallucinated_answer = "- Kanhaiya Lal Dubhalia\n- Kanhaiya Lal Nakfofa"
    res_hallucinated = confidence_score_service.calculate_confidence(
        retrieved_chunks=retrieved_chunks,
        answer=hallucinated_answer,
        fallback_message="Fallback"
    )
    
    assert res_grounded["answer_confidence"] > 0.7
    assert res_hallucinated["answer_confidence"] < 0.3
    assert res_hallucinated["answer_confidence"] < res_grounded["answer_confidence"]

def test_out_of_context_fallback_detection():
    """
    Test 5: Verify calculate_confidence correctly flags out-of-context replies.
    """
    retrieved_chunks = [
        {"content": "Gaya Ji is famous for Pinddaan rituals perform by Pandas."}
    ]
    
    # Fallback message trigger
    res_fallback = confidence_score_service.calculate_confidence(
        retrieved_chunks=retrieved_chunks,
        answer="I cannot answer that based on the provided context.",
        fallback_message="I cannot answer that based on the provided context."
    )
    
    # Combined confidence should be zeroed out
    assert res_fallback["answer_confidence"] == 0.0
    assert res_fallback["combined_confidence"] == 0.0
