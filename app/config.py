import os
from pathlib import Path
from typing import Optional


def load_dotenv(env_path: Optional[Path] = None) -> None:
    """Đọc file .env và nạp các biến vào os.environ nếu chưa có."""
    if env_path is None:
        env_path = Path(__file__).resolve().parents[1] / ".env"

    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    # Không ghi đè nếu biến môi trường hệ thống đã tồn tại
                    if key not in os.environ:
                        os.environ[key] = val
        except Exception:
            pass


# Nạp biến môi trường từ .env ngay khi import module
load_dotenv()


class Settings:
    """Quản lý tập trung toàn bộ cấu hình, token và thông số nhạy cảm."""

    @property
    def GITHUB_TOKEN(self) -> Optional[str]:
        return os.getenv("GITHUB_TOKEN")

    @property
    def GITHUB_OWNER(self) -> str:
        return os.getenv("GITHUB_OWNER", "Tuanhung-nguyen")

    @property
    def GITHUB_REPO(self) -> str:
        return os.getenv("GITHUB_REPO", "Spotify_Premium")

    @property
    def OLLAMA_BASE_URL(self) -> str:
        return os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    @property
    def OLLAMA_MODEL(self) -> str:
        return os.getenv("OLLAMA_MODEL", "qwen3:8b")

    @property
    def LLM_TIMEOUT(self) -> int:
        return int(os.getenv("LLM_TIMEOUT", "600"))

    @property
    def LLM_TEMPERATURE(self) -> float:
        return float(os.getenv("LLM_TEMPERATURE", "0.0"))

    @property
    def POLL_INTERVAL_SECONDS(self) -> int:
        return int(os.getenv("POLL_INTERVAL_SECONDS", "300"))

    # ==========================================
    # Cấu hình Databricks Integration
    # ==========================================
    @property
    def DATABRICKS_HOST(self) -> Optional[str]:
        host = os.getenv("DATABRICKS_HOST")
        if host:
            # Tự động loại bỏ ký tự xuống dòng thừa hoặc dấu gạch chéo cuối URL (phòng tránh lỗi %0a như CASE_08)
            host = host.strip().rstrip("/")
            if not host.startswith("http://") and not host.startswith("https://"):
                host = f"https://{host}"
        return host

    @property
    def DATABRICKS_TOKEN(self) -> Optional[str]:
        token = os.getenv("DATABRICKS_TOKEN")
        return token.strip() if token else None

    # ==========================================
    # Cấu hình Telegram Notification
    # ==========================================
    @property
    def TELEGRAM_BOT_TOKEN(self) -> Optional[str]:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        return token.strip() if token else None

    @property
    def TELEGRAM_CHAT_ID(self) -> Optional[str]:
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        return chat_id.strip() if chat_id else None

    # ==========================================
    # Cấu hình Google Gemini Cloud LLM
    # ==========================================
    @property
    def GEMINI_API_KEY(self) -> Optional[str]:
        key = os.getenv("GEMINI_API_KEY")
        return key.strip() if key else None


settings = Settings()

