import os
import httpx
import logging
from typing import List, Dict
from app.core.config import settings

logger = logging.getLogger("chat_agent")

class ChatAgentService:
    @staticmethod
    async def generate_response(
        system_prompt: str,
        tone: str,
        fallback_message: str,
        history: List[Dict[str, str]]
    ) -> str:
        """
        Generates a chatbot reply. 
        - If the key starts with AQ. or AIzaSy, calls Google's Gemini API directly.
        - If it's a standard key, calls OpenAI.
        - Otherwise, falls back to a smart local agent.
        """
        api_key = os.getenv("OPENAI_API_KEY", "") or getattr(settings, "OPENAI_API_KEY", "")
        
        system_instructions = (
            f"{system_prompt or 'You are a helpful assistant.'}\n"
            f"Adhere strictly to a conversational tone of: {tone or 'professional'}."
        )

        if api_key:
            try:
                # Detect Gemini key prefix
                if api_key.startswith("AIzaSy") or api_key.startswith("AQ."):
                    # Map history to Gemini format (role must be 'user' or 'model')
                    gemini_contents = []
                    for h in history:
                        role = "user" if h["role"] == "user" else "model"
                        gemini_contents.append({
                            "role": role,
                            "parts": [{"text": h["content"]}]
                        })
                    
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}",
                            headers={"Content-Type": "application/json"},
                            json={
                                "contents": gemini_contents,
                                "systemInstruction": {
                                    "parts": [{"text": system_instructions}]
                                }
                            },
                            timeout=15.0
                        )
                        
                        if response.status_code == 200:
                            res_json = response.json()
                            reply = res_json["candidates"][0]["content"]["parts"][0]["text"]
                            if reply:
                                return reply.strip()
                        else:
                            logger.error(f"Gemini API error: {response.status_code} - {response.text}")
                
                else:
                    # Default to OpenAI call
                    messages = [{"role": "system", "content": system_instructions}]
                    for h in history:
                        messages.append({"role": h["role"], "content": h["content"]})
                    
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            "https://api.openai.com/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "model": getattr(settings, "OPENAI_MODEL", "gpt-4o"),
                                "messages": messages,
                                "temperature": 0.7,
                                "max_tokens": 512,
                            },
                            timeout=15.0
                        )
                        
                        if response.status_code == 200:
                            res_json = response.json()
                            reply = res_json["choices"][0]["message"]["content"]
                            if reply:
                                return reply.strip()
                        else:
                            logger.error(f"OpenAI API error: {response.status_code} - {response.text}")
            except Exception as e:
                logger.error(f"Failed to generate AI response: {str(e)}")

        # Rule-based fallback simulator
        last_user_msg = ""
        for h in reversed(history):
            if h["role"] == "user":
                last_user_msg = h["content"].lower().strip()
                break
        
        # Simple keywords
        greetings = ["hi", "hello", "hey", "hola", "greetings", "good morning", "good afternoon"]
        if any(g in last_user_msg for g in greetings):
            if tone == "friendly":
                return "Hey! Hope you're having an awesome day. How can I help you? 😊"
            elif tone == "casual":
                return "Hey there! What's on your mind?"
            elif tone == "formal":
                return "Good day. Please state your inquiry so I may assist you."
            else:
                return "Hello. How can I help you today?"
        
        # Otherwise fallback message
        return fallback_message or "I'm sorry, I am unable to assist with that query at the moment."

chat_agent_service = ChatAgentService()
