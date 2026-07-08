import logging
from typing import Dict, Any

logger = logging.getLogger("app.services.fallback")


class FallbackResponseService:
    """
    Service to manage fallback response selections and human escalation eligibility tracking.
    """

    def process_fallback(
        self,
        user_question: str,
        generated_answer: str,
        confidence_metrics: Dict[str, float],
        confidence_threshold: float,
        fallback_message: str = None,
    ) -> Dict[str, Any]:
        """
        Determines the appropriate response and escalation status.
        Returns:
            Dict containing:
                - 'answer': Selected response text (str)
                - 'escalation_eligible': Boolean indicating if user should be escalated (bool)
        """
        user_q_lower = user_question.strip().lower()
        combined_confidence = confidence_metrics.get("combined_confidence", 0.0)

        # 1. Detect Low Confidence
        is_low_confidence = combined_confidence < confidence_threshold

        # 2. Detect Escalation Triggers (explicit human representative keywords)
        escalation_keywords = {"human", "agent", "representative", "support", "person", "operator", "helpdesk", "escalate"}
        has_escalation_trigger = any(kw in user_q_lower for kw in escalation_keywords)

        # 3. Detect if it is a general greeting (we shouldn't escalate simple hellos)
        greetings = {"hi", "hello", "hey", "hola", "greetings", "good morning", "good afternoon", "hi there", "hello there"}
        is_greeting = user_q_lower in greetings or any(user_q_lower == g for g in greetings)

        # 4. Determine Escalation Eligibility
        if is_greeting:
            # For greetings, only escalate if user explicitly asked for human help
            escalation_eligible = has_escalation_trigger
        else:
            # If no sources are configured/retrieved (combined_confidence is 0.0), do not trigger handoff
            # unless user explicitly asked for it via escalation keywords.
            if combined_confidence == 0.0:
                escalation_eligible = has_escalation_trigger
            else:
                escalation_eligible = is_low_confidence or has_escalation_trigger

        # 4. Fallback Response Selection
        # If low confidence or explicitly asked for human, we return fallback message if configured
        selected_answer = generated_answer
        if escalation_eligible:
            # Check if user asked for contact/agent/support info specifically
            contact_keywords = {"contact", "agent", "connect", "support", "speak", "reach", "phone", "email", "address", "call"}
            if any(kw in user_q_lower for kw in contact_keywords):
                selected_answer = (
                    "You can reach out to the Confluxaa team via:\n"
                    "• 📧 **Email:** contact@confluxaa.com\n"
                    "• 🌐 **Website:** www.confluxaa.com (by filling out the contact form)\n"
                    "• 📍 **Office Address:** Bangalore, Karnataka, India"
                )
            elif fallback_message:
                selected_answer = fallback_message

        logger.info(
            f"Fallback processed - Low Confidence: {is_low_confidence} (Score: {combined_confidence:.4f} vs Thresh: {confidence_threshold:.4f}), "
            f"Trigger found: {has_escalation_trigger}, Escalation Eligible: {escalation_eligible}"
        )

        return {
            "answer": selected_answer,
            "escalation_eligible": escalation_eligible,
        }


# Module-level singleton
fallback_response_service = FallbackResponseService()
