import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from app.core.models import AnalysisResult, IncidentAnalysis

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


class AlertNotifier:
    """
    Module phụ trách thông báo và lưu trữ cảnh báo sự cố sau khi phân tích xong (RCA).
    - In ra màn hình Console định dạng trực quan.
    - Ghi log vào file alerts.log để lưu trữ lịch sử sự cố.
    """

    def __init__(self, log_file_path: str = "data/monitor/alerts.log"):
        self.log_file = Path(log_file_path)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def format_alert_message(self, result: AnalysisResult) -> str:
        """Định dạng kết quả phân tích thành thông điệp cảnh báo rõ ràng."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        lines = []
        lines.append("=" * 70)
        lines.append(f"🚨 [CẢNH BÁO SỰ CỐ PIPELINE] - {now_str}")
        lines.append("=" * 70)

        rec = result.execution_record
        if rec and rec.original_log:
            orig = rec.original_log
            lines.append(f"• Thành phần     : {orig.component}")
            lines.append(f"• Thông báo lỗi  : {orig.error}")
            # Hiển thị linh hoạt toàn bộ metadata/metrics của mọi công cụ (GitHub, Databricks, Airflow, v.v.)
            if orig.metrics:
                lines.append("• Thông tin ngữ cảnh:")
                for key, val in orig.metrics.items():
                    # Format tên key cho đẹp (vd: run_id -> Run Id, job_id -> Job Id)
                    pretty_key = key.replace("_", " ").title()
                    lines.append(f"   - {pretty_key:15}: {val}")

        if result.status == "SUCCESS" and result.analysis:
            a: IncidentAnalysis = result.analysis
            lines.append("-" * 70)
            lines.append("                KẾT QUẢ PHÂN TÍCH NGUYÊN NHÂN GỐC RỄ (RCA)")
            lines.append("-" * 70)
            lines.append(f"• Loại lỗi xác định   : {a.error_type}")
            lines.append(f"• Mức độ nghiêm trọng : {a.severity}")
            lines.append(f"• Độ tin cậy (AI)     : {round(a.confidence * 100, 1)}%")

            if a.facts:
                lines.append("• Bằng chứng thực tế  :")
                for f in a.facts:
                    lines.append(f"   - {f}")

            if a.possible_causes:
                lines.append("• Nguyên nhân có thể  :")
                for c in a.possible_causes:
                    lines.append(f"   - {c}")

            if a.recommendation:
                lines.append(f"• Đề xuất xử lý       : {a.recommendation}")

        elif result.status == "HUMAN_REVIEW_REQUIRED":
            lines.append("-" * 70)
            lines.append("⚠️ CẦN CON NGƯỜI CAN THIỆP (HUMAN REVIEW REQUIRED)")
            if result.human_review:
                lines.append(f"• Lý do: {result.human_review.reason}")
        else:
            lines.append("-" * 70)
            lines.append(f"Trạng thái phân tích: {result.status}")

        lines.append("=" * 70 + "\n")
        return "\n".join(lines)

    def _send_telegram(self, text: str) -> bool:
        """Gửi thông báo cảnh báo qua Telegram Bot API (hoàn toàn miễn phí)."""
        import requests
        from app.config import settings

        bot_token = settings.TELEGRAM_BOT_TOKEN
        chat_id = settings.TELEGRAM_CHAT_ID

        if not bot_token or not chat_id:
            # Chưa cấu hình Telegram -> Bỏ qua
            return False

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                print("📱 [TELEGRAM] Đã gửi thông báo sự cố về điện thoại thành công!")
                return True
            else:
                print(f"⚠️ [TELEGRAM WARN] Telegram API trả về lỗi: {resp.text}")
                return False
        except Exception as e:
            print(f"⚠️ [TELEGRAM WARN] Không thể kết nối tới Telegram API: {e}")
            return False

    def send_alert(self, result: AnalysisResult) -> str:
        """Gửi cảnh báo: In ra console, ghi file log và bắn về Telegram."""
        msg = self.format_alert_message(result)

        # 1. In ra Console
        print(msg)

        # 2. Ghi vào file log cảnh báo
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception as e:
            print(f"❌ [NOTIFIER ERROR] Không thể ghi file alert log: {e}")

        # 3. Bắn tin nhắn về điện thoại qua Telegram
        self._send_telegram(msg)

        return msg
