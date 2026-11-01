import re
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Any, Dict
from app.core.models import AnalysisResult, IncidentAnalysis
from app.config import settings

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def extract_error_snippet(log_text: Any, window_before: int = 10, window_after: int = 25) -> Optional[str]:
    """
    Cắt thông minh cửa sổ log xung quanh vị trí xuất hiện Exception / Error / Traceback.
    TỔNG QUÁT 100%: Dùng chung cho mọi nguồn (Databricks, GitHub, Airflow, dbt...)
    mà không phụ thuộc vào bất kỳ tên tool cụ thể nào.
    """
    if not log_text:
        return None
    if not isinstance(log_text, str):
        log_text = str(log_text)

    lines = log_text.splitlines()
    if not lines:
        return None

    error_patterns = [
        re.compile(r"traceback \(most recent call last\)", re.IGNORECASE),
        re.compile(r"(error|exception|fail|failed|failure):", re.IGNORECASE),
        re.compile(r"\[[A-Z0-9_]{4,}\]", re.IGNORECASE),
        re.compile(r"sqlstate:\s*\d+", re.IGNORECASE),
    ]

    error_idx = None
    for idx, line in enumerate(lines):
        for pattern in error_patterns:
            if pattern.search(line):
                error_idx = idx
                break
        if error_idx is not None:
            break

    if error_idx is None:
        return None

    start_idx = max(0, error_idx - window_before)
    end_idx = min(len(lines), error_idx + window_after + 1)
    return "\n".join(lines[start_idx:end_idx]).strip()



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
            lines.append(f"• Thông báo lỗi  : {orig.error or 'Không có lỗi (Thành công)'}")
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

    def _save_to_supabase(self, result: AnalysisResult) -> None:
        """Tự động đồng bộ toàn bộ sự cố vào Supabase Cloud (3 bảng: pipeline_runs, log_events, ai_diagnoses)."""
        try:
            from app.db import get_db
            db = get_db()
            if not db.is_configured:
                return

            rec = result.execution_record
            orig = rec.original_log if rec else None
            metrics = orig.metrics if orig else {}

            run_id = str(metrics.get("run_id") or (rec.execution_id if rec else "unknown_run"))
            project_name = metrics.get("project_name")
            if not project_name:
                repo_str = metrics.get("repository")
                if repo_str:
                    project_name = repo_str.split("/")[-1]
            if not project_name:
                project_name = getattr(settings, "DEFAULT_PROJECT_NAME", "default")

            pipeline_name = metrics.get("job_name") or (orig.component if orig else "Data Pipeline")
            pipeline_id = str(metrics.get("job_id") or "")
            source = metrics.get("source", "databricks")

            # 1. Lưu pipeline_runs
            pipeline_duration = float(metrics.get("duration_sec") or 0.0)
            if pipeline_duration == 0.0 and rec:
                pipeline_duration = round(rec.total_duration_ms / 1000.0, 2)

            db.upsert_pipeline_run(
                run_id=run_id,
                project_name=project_name,
                pipeline_name=pipeline_name,
                pipeline_id=pipeline_id,
                source=source,
                status="FAILED" if result.status != "SKIPPED" else "SUCCESS",
                start_time=metrics.get("start_time"),
                end_time=metrics.get("end_time"),
                duration_sec=pipeline_duration,
                metadata=metrics
            )

            # 2. Lưu log_events
            if orig:
                # Quét kết quả các tool của AI để tìm đoạn log lỗi thực sự (đồng nhất 100% với cách đưa vào prompt AI)
                detailed_error_log = None

                if rec and rec.tool_calls:
                    for tc in rec.tool_calls:
                        if isinstance(tc, dict):
                            # Biến mọi kết quả của tool thành văn bản y hệt như đưa vào prompt AI
                            tool_output_text = json.dumps(tc.get("result", ""), ensure_ascii=False)
                            snippet = extract_error_snippet(tool_output_text)
                            if snippet:
                                detailed_error_log = snippet
                                break

                # Tên task ưu tiên: failed_tasks từ metrics > tên component
                failed_tasks = metrics.get("failed_tasks", [])
                task_name = failed_tasks[0] if failed_tasks else (orig.component or "Main Pipeline")

                # Câu log ưu tiên: đoạn cắt lỗi thông minh > orig.log hoặc orig.error ban đầu
                final_log_message = (
                    detailed_error_log
                    if (result.status != "SKIPPED" and detailed_error_log)
                    else (orig.log or orig.error)
                )

                db.insert_log_event(
                    run_id=run_id,
                    level="ERROR" if result.status != "SKIPPED" else "INFO",
                    task_name=task_name,
                    message=final_log_message,
                    payload={
                        "event": "detailed_trace_extracted" if detailed_error_log else "ai_analysis_completed",
                        "status": "FAILED" if result.status != "SKIPPED" else "SUCCESS",
                        "component": orig.component,
                        "has_detailed_trace": bool(detailed_error_log),
                        "tool_calls": rec.tool_calls if rec else [],
                        "metrics": metrics
                    }
                )

            # 3. Lưu ai_diagnoses
            if result.status == "SUCCESS" and result.analysis:
                a = result.analysis
                tools_used = []
                if rec and rec.tool_calls:
                    for tc in rec.tool_calls:
                        if isinstance(tc, dict):
                            tools_used.append(tc)
                        elif hasattr(tc, "model_dump"):
                            tools_used.append(tc.model_dump())
                        else:
                            tools_used.append(str(tc))

                root_cause = getattr(a, "root_cause", None) or (a.possible_causes[0] if a.possible_causes else (a.inferences[0] if a.inferences else "Unknown Root Cause"))
                db.upsert_ai_diagnosis(
                    run_id=run_id,
                    error_type=a.error_type,
                    severity=a.severity,
                    confidence=float(a.confidence),
                    root_cause=root_cause,
                    recommendation=a.recommendation,
                    facts=a.facts,
                    possible_causes=a.possible_causes,
                    tools_used=tools_used,
                    iterations=len(tools_used) + 1,
                    duration_ms=rec.total_duration_ms if rec else 0.0
                )
        except Exception as e:
            print(f"⚠️ [SUPABASE SYNC WARN] Lỗi đồng bộ Supabase: {e}")

    def send_alert(self, result: AnalysisResult) -> str:
        """Gửi cảnh báo: In ra console, ghi file log, bắn về Telegram và đồng bộ vào Supabase."""
        msg = self.format_alert_message(result)

        # 1. In ra Console
        print(msg)

        # 2. Ghi vào file log cảnh báo
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception as e:
            print(f"❌ [NOTIFIER ERROR] Không thể ghi file alert log: {e}")

        # 3. Bắn tin nhắn về điện thoại qua Telegram (chỉ bắn khi có sự cố thật)
        if result.status != "SKIPPED":
            self._send_telegram(msg)

        # 4. Tự động đồng bộ toàn diện vào Supabase Cloud (3 bảng)
        self._save_to_supabase(result)

        return msg
