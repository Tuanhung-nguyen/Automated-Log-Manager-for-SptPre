import requests
import json
import time
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
        """Gọi Google Gemini 3.8 Flash qua REST API thuần với cơ chế tự động thử lại khi máy chủ bận (503/429)."""
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.gemini_api_key
        }
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

        max_retries = 3
        backoff_seconds = 2

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                if response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    print(f"⚠️ [GEMINI RETRY] Máy chủ Google phản hồi HTTP {response.status_code}. Tự động thử lại lần {attempt}/{max_retries} sau {backoff_seconds}s...")
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2
                    continue

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
                if attempt < max_retries:
                    print(f"⚠️ [GEMINI RETRY] Lỗi kết nối ({e}). Thử lại lần {attempt}/{max_retries} sau {backoff_seconds}s...")
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2
                else:
                    raise LLMAPIError(f"Gemini API request failed sau {max_retries} lần thử: {e}")

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
