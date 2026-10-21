import requests
import json
from typing import Optional
from app.core.exceptions import LLMAPIError
from app.config import settings


class LLMClient:
    """
    LLMClient đa nền tảng:
    - Nếu có cấu hình GEMINI_API_KEY -> Tự động gọi Google Gemini 2.5 Flash (Cloud / Free 100%).
    - Nếu không -> Tự động fallback về Ollama Local (qwen3:8b).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        temperature: Optional[float] = None,
        gemini_api_key: Optional[str] = None
    ):
        self.gemini_api_key = gemini_api_key or settings.GEMINI_API_KEY
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = timeout if timeout is not None else settings.LLM_TIMEOUT
        self.temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE

    def _generate_gemini(self, prompt: str) -> str:
        """Gọi Google Gemini 2.5 Flash qua REST API thuần (không cần cài thêm SDK)."""
        # Endpoint Gemini 2.5 Flash chính thức
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.gemini_api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": self.temperature,
            }
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            # Trích xuất text từ response của Gemini
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
            raise LLMAPIError(f"Gemini API không trả về content: {data}")
        except requests.RequestException as e:
            raise LLMAPIError(f"Gemini API request failed: {e}")

    def _generate_ollama(self, prompt: str) -> str:
        """Gọi Ollama API Local."""
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": self.temperature,
                    }
                },
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            return data["response"]
        except requests.RequestException as e:
            raise LLMAPIError(f"Ollama API request failed: {e}")

    def generate(self, prompt: str) -> str:
        if self.gemini_api_key:
            return self._generate_gemini(prompt)
        return self._generate_ollama(prompt)
