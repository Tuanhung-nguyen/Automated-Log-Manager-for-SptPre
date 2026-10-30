import sys
import json
import threading
from typing import Optional
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from app.config import settings
from app.llm import LLMClient
from app.pipeline import IncidentPipeline, AgentRunner
from app.monitor import AlertNotifier
from app.adapters import get_adapter, list_supported_sources
from app.core import IncidentContext

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass


def build_pipeline() -> IncidentPipeline:
    """Khởi tạo IncidentPipeline hoàn chỉnh kết nối với AgentRunner."""
    llm_client = LLMClient(
        model=settings.OLLAMA_MODEL,
        timeout=settings.LLM_TIMEOUT,
        temperature=settings.LLM_TEMPERATURE
    )
    runner = AgentRunner(client=llm_client, max_iterations=4)
    return IncidentPipeline(runner=runner)


# Khởi tạo Pipeline và Notifier dùng chung
pipeline = build_pipeline()
notifier = AlertNotifier()


def _record_success_async(ctx: IncidentContext, source_name: str, url_project: Optional[str] = None):
    """
    Lưu trữ trạng thái và log của lần chạy THÀNH CÔNG vào Supabase ở Background Thread.
    Giúp webhook response trả về ngay lập tức (<50ms) mà không bị nghẽn mạng hay timeout.
    """
    try:
        metrics = ctx.metrics or {}
        run_id = str(metrics.get("run_id", "unknown"))
        pipeline_name = metrics.get("job_name") or ctx.component or "Data Pipeline"
        duration_sec = float(metrics.get("duration_sec", 0.0))
        project_name = metrics.get("project_name") or url_project or getattr(settings, "DEFAULT_PROJECT_NAME", "default")

        print(f"✅ [BACKGROUND - RUN THÀNH CÔNG] Ghi nhận Pipeline '{pipeline_name}' (Run ID: {run_id}, Project: {project_name}) vào Supabase...", flush=True)

        from app.db import get_db
        db = get_db()
        if not db.is_configured:
            print("ℹ️ [SUPABASE SKIP] Chưa cấu hình Supabase URL/KEY, bỏ qua lưu DB.", flush=True)
            return

        # 1. Ghi nhận / Upsert vào bảng pipeline_runs
        db.upsert_pipeline_run(
            run_id=run_id,
            project_name=project_name,
            pipeline_name=pipeline_name,
            pipeline_id=str(metrics.get("job_id") or ""),
            source=metrics.get("source", source_name),
            status="SUCCESS",
            duration_sec=duration_sec,
            metadata=metrics
        )

        # 2. Ghi nhận vào bảng log_events:
        # Nếu payload gốc chứa danh sách các task con (sub-tasks của Databricks Job), lưu chi tiết từng task!
        raw_tasks = metrics.get("tasks") or []
        if isinstance(raw_tasks, list) and len(raw_tasks) > 0:
            saved_count = 0
            for task in raw_tasks:
                if isinstance(task, dict):
                    t_key = task.get("task_key") or task.get("task_name") or pipeline_name
                    t_dur = round(float(task.get("execution_duration", 0)) / 1000.0, 2) if task.get("execution_duration") else None
                    if db.insert_log_event(
                        run_id=run_id,
                        level="INFO",
                        task_name=t_key,
                        message=f"Task '{t_key}' completed successfully.",
                        payload={
                            "status": "SUCCESS",
                            "duration_sec": t_dur,
                            "task_key": t_key,
                            "pipeline_name": pipeline_name,
                            "project_name": project_name,
                            "raw_task": task
                        }
                    ):
                        saved_count += 1
            print(f"💾 [SUPABASE] Đã lưu {saved_count}/{len(raw_tasks)} task con thành công cho Run ID: {run_id}.", flush=True)
        else:
            # Nếu không có subtasks riêng lẻ, lấy tên pipeline/job thực tế làm task_name
            actual_task_name = metrics.get("task_name") or pipeline_name
            if db.insert_log_event(
                run_id=run_id,
                level="INFO",
                task_name=actual_task_name,
                message=f"Pipeline '{pipeline_name}' completed successfully.",
                payload={
                    "status": "SUCCESS",
                    "duration_sec": duration_sec,
                    "pipeline_name": pipeline_name,
                    "project_name": project_name,
                    **metrics
                }
            ):
                print(f"💾 [SUPABASE] Đã lưu log thành công cho Run ID: {run_id} (Task: {actual_task_name}).", flush=True)

    except Exception as db_err:
        import traceback
        print(f"⚠️ [SUPABASE SYNC WARN]: {db_err}", flush=True)
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()


def _run_pipeline_async(ctx: IncidentContext, source_name: str, url_project: Optional[str] = None):
    """
    Xử lý sự cố THẤT BẠI bền vững (Resilient Incident Architecture - Write-Ahead Pattern):
    1. WRITE-AHEAD: Ghi nhận NGAY vào Supabase: pipeline_runs (FAILED) + log_events ban đầu.
       -> Bảo đảm 100% không mất dấu sự cố (Audit Trail) kể cả khi AI gặp sự cố/timeout.
    2. Chạy Agent Pipeline phân tích nguyên nhân gốc rễ (RCA) trong try...except an toàn.
    3. Nếu AI hoàn tất: Notifier tự động lưu ai_diagnoses, cập nhật traceback thật và bắn Telegram.
    4. Nếu AI gặp lỗi (timeout, LLM down...): Ghi nhận cảnh báo và gửi Telegram fallback cho kỹ sư trực.
    """
    metrics = ctx.metrics or {}
    run_id = str(metrics.get("run_id", "unknown"))
    pipeline_name = metrics.get("job_name") or ctx.component or "Data Pipeline"
    duration_sec = float(metrics.get("duration_sec", 0.0))
    project_name = metrics.get("project_name") or url_project or getattr(settings, "DEFAULT_PROJECT_NAME", "default")
    failed_tasks = metrics.get("failed_tasks", [])
    task_name = failed_tasks[0] if failed_tasks else (metrics.get("task_name") or pipeline_name)

    # 1. WRITE-AHEAD: Bảo toàn vết sự cố ngay lập tức vào Supabase Cloud
    try:
        from app.db import get_db
        db = get_db()
        if db.is_configured:
            # Ghi nhận pipeline_runs (FAILED)
            db.upsert_pipeline_run(
                run_id=run_id,
                project_name=project_name,
                pipeline_name=pipeline_name,
                pipeline_id=str(metrics.get("job_id") or ""),
                source=metrics.get("source", source_name),
                status="FAILED",
                duration_sec=duration_sec,
                metadata=metrics
            )
            # Ghi nhận log_events sự cố ban đầu
            db.insert_log_event(
                run_id=run_id,
                level="ERROR",
                task_name=task_name,
                message=ctx.error or ctx.log or f"Incident detected on pipeline '{pipeline_name}'",
                payload={
                    "event": "incident_detected",
                    "status": "FAILED",
                    "pipeline_name": pipeline_name,
                    "project_name": project_name,
                    "duration_sec": duration_sec,
                    "metrics": metrics
                }
            )
            print(f"💾 [SUPABASE - WRITE-AHEAD] Đã bảo toàn vết sự cố cho Run ID '{run_id}' (Project: {project_name}).", flush=True)
    except Exception as db_err:
        print(f"⚠️ [SUPABASE WRITE-AHEAD WARN]: {db_err}", flush=True)

    # 2. Chạy AI RCA Agent an toàn
    try:
        print(f"🚀 [KÍCH HOẠT PHÂN TÍCH TỰ ĐỘNG] Chuyển log sang Agent Pipeline: {ctx.error}", flush=True)
        result = pipeline.run(ctx)
        notifier.send_alert(result)
        print("✅ [BACKGROUND] Phân tích sự cố và gửi thông báo hoàn tất.", flush=True)
    except Exception as ai_err:
        import traceback
        print(f"❌ [AI PIPELINE ERROR] Quá trình AI phân tích RCA gặp lỗi: {ai_err}", flush=True)
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()

        # 3. FALLBACK KHI AI GẶP SỰ CỐ: Ghi nhận cảnh báo và bắn Telegram cứu hộ
        try:
            from app.db import get_db
            db = get_db()
            if db.is_configured:
                db.insert_log_event(
                    run_id=run_id,
                    level="WARNING",
                    task_name="AI_RCA_Agent",
                    message=f"AI Agent failed to analyze incident: {ai_err}",
                    payload={"error": str(ai_err), "project_name": project_name}
                )
        except Exception:
            pass

        # Bắn Telegram cứu cánh cho kỹ sư on-call
        try:
            fallback_text = (
                f"🚨 [CẢNH BÁO SỰ CỐ PIPELINE]\n"
                f"• Dự án (Project) : {project_name}\n"
                f"• Pipeline        : {pipeline_name}\n"
                f"• Run ID          : {run_id}\n"
                f"• Trạng thái      : THẤT BẠI (FAILED)\n"
                f"• Lỗi ban đầu     : {ctx.error or ctx.log}\n"
                f"⚠️ Lưu ý: AI RCA gặp sự cố nội bộ ({ai_err}). Kỹ sư vui lòng kiểm tra trực tiếp."
            )
            notifier._send_telegram(fallback_text)
        except Exception:
            pass


class GenericWebhookHandler(BaseHTTPRequestHandler):
    """
    HTTP Request Handler ĐA NỀN TẢNG (Generic Dispatcher):
    Tự động phân phối gói tin Webhook tới đúng Adapter tương ứng dựa trên URL:
    POST /webhook/<source_name> (ví dụ: /webhook/github, /webhook/databricks, /webhook/airflow)
    """

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            supported = list_supported_sources()
            self.wfile.write(json.dumps({
                "status": "UP",
                "message": "Incident AI Server is running",
                "supported_sources": supported
            }).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        # 1. Trích xuất tên nguồn và query params từ URL (vd: /webhook/databricks?project=sales_etl)
        from urllib.parse import urlparse, parse_qs
        parsed_url = urlparse(self.path)
        path_parts = parsed_url.path.strip("/").split("/")
        if len(path_parts) != 2 or path_parts[0] != "webhook":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Endpoint not found. Use POST /webhook/<source_name>")
            return

        source_name = path_parts[1].lower()
        query_params = parse_qs(parsed_url.query)
        url_project = (query_params.get("project", [None])[0] or self.headers.get("X-Project-Name"))

        # 2. Lấy Adapter tương ứng từ Registry
        try:
            adapter = get_adapter(source_name)
        except ValueError as e:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ERROR", "message": str(e)}).encode("utf-8"))
            return

        # 3. Đọc dữ liệu JSON gửi về
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {}

        if url_project and isinstance(payload, dict) and "project_name" not in payload:
            payload["project_name"] = url_project

        print(f"\n📨 [WEBHOOK NHẬN ĐƯỢC] Gói tin từ nguồn: '{source_name.upper()}' (Project: {url_project or 'auto'})", flush=True)

        # 4. Bóc tách log và trạng thái qua Adapter
        context = adapter.parse_webhook_payload(payload)

        if context is None:
            # Gói tin không liên quan tới pipeline run
            print(f"ℹ️ [WEBHOOK BỎ QUA] Sự kiện từ '{source_name}' không liên quan tới lần chạy pipeline.", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "IGNORED", "reason": "Not a pipeline run"}).encode("utf-8"))
            return

        metrics = context.metrics or {}
        run_id = str(metrics.get("run_id", "unknown"))
        pipeline_name = metrics.get("job_name", context.component)
        status = metrics.get("status", "FAILED")
        duration_sec = float(metrics.get("duration_sec", 0.0))
        project_name = metrics.get("project_name") or url_project or getattr(settings, "DEFAULT_PROJECT_NAME", "default")

        # 5. Nếu là run THÀNH CÔNG: Phản hồi 200 OK ngay (< 50ms) để caller không bị timeout,
        # sau đó đẩy tác vụ lưu Supabase vào Background Thread.
        if status == "SUCCESS":
            print(f"✅ [RUN THÀNH CÔNG] Pipeline '{pipeline_name}' (Run ID: {run_id}, Project: {project_name}) chạy thành công.", flush=True)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ACCEPTED",
                "pipeline_status": "SUCCESS",
                "run_id": run_id,
                "message": "Success run received. Recording to database in background."
            }).encode("utf-8"))

            # Chạy lưu DB không đồng bộ ở background thread
            thread = threading.Thread(
                target=_record_success_async,
                args=(context, source_name, url_project),
                daemon=True
            )
            thread.start()
            return

        # 6. Có sự cố thật -> Phản hồi 200 OK ngay lập tức (< 100ms) để Databricks/GitHub không bị timeout
        print(f"🚨 [SỰ CỐ TỰ ĐỘNG PHÁT HIỆN]: {context.error} (Run ID: {run_id})", flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ACCEPTED",
            "source": source_name,
            "message": "Incident received. AI analysis running in background."
        }).encode("utf-8"))

        # 7. Chạy Agent Pipeline không đồng bộ ở Background Thread (AI RCA + Telegram + Supabase)
        thread = threading.Thread(
            target=_run_pipeline_async,
            args=(context, source_name, url_project),
            daemon=True
        )
        thread.start()


def run_server(port: int = 8000):
    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, GenericWebhookHandler)
    supported = list_supported_sources()

    print("=" * 80)
    print("      AI INCIDENT OBSERVABILITY - GENERIC WEBHOOK SERVER")
    print("=" * 80)
    print(f"• Cổng lắng nghe (Port)   : http://localhost:{port}")
    print(f"• Các nguồn hỗ trợ hiện tại: {supported}")
    print(f"• Quy tắc Endpoint        : POST http://localhost:{port}/webhook/<tên_nguồn>")
    print(f"• Ví dụ                   : POST http://localhost:{port}/webhook/github")
    print(f"• Healthcheck             : GET  http://localhost:{port}/health")
    print("=" * 80 + "\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Đã dừng Webhook Server.")
        httpd.server_close()


if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", "8000"))
    run_server(port=port)
