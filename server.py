import sys
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from app.config import settings
from app.llm import LLMClient
from app.pipeline import IncidentPipeline, AgentRunner
from app.monitor import AlertNotifier
from app.adapters import get_adapter, list_supported_sources
from app.core import IncidentContext

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
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


def _run_pipeline_async(ctx: IncidentContext):
    """Xử lý phân tích sự cố bằng AI ở Background Thread để webhook không bị timeout."""
    try:
        print(f"🚀 [KÍCH HOẠT PHÂN TÍCH TỰ ĐỘNG] Chuyển log sang Agent Pipeline...")
        result = pipeline.run(ctx)
        notifier.send_alert(result)
        print("✅ [BACKGROUND] Phân tích sự cố và gửi thông báo hoàn tất.")
    except Exception as err:
        print(f"❌ [BACKGROUND ERROR] Lỗi phân tích sự cố: {err}")


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
        # 1. Trích xuất tên nguồn từ URL: /webhook/<source_name>
        path_parts = self.path.strip("/").split("/")
        if len(path_parts) != 2 or path_parts[0] != "webhook":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Endpoint not found. Use POST /webhook/<source_name>")
            return

        source_name = path_parts[1].lower()

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

        print(f"\n📨 [WEBHOOK NHẬN ĐƯỢC] Gói tin từ nguồn: '{source_name.upper()}'")

        # 4. Giao toàn bộ việc bóc tách log cho chính Adapter của công cụ đó!
        context = adapter.parse_webhook_payload(payload)

        if context is None:
            # Không phải sự cố hoặc workflow thành công -> Bỏ qua
            print(f"ℹ️ [WEBHOOK BỎ QUA] Sự kiện từ '{source_name}' chạy thành công hoặc không phải lỗi.")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "IGNORED", "reason": "Not an incident"}).encode("utf-8"))
            return

        # 5. Có sự cố thật -> Phản hồi 200 OK ngay lập tức (< 100ms) để Databricks/GitHub không bị timeout
        print(f"🚨 [SỰ CỐ TỰ ĐỘNG PHÁT HIỆN]: {context.error}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ACCEPTED",
            "source": source_name,
            "message": "Incident received. AI analysis running in background."
        }).encode("utf-8"))

        # 6. Chạy Agent Pipeline không đồng bộ ở Background Thread
        thread = threading.Thread(target=_run_pipeline_async, args=(context,), daemon=True)
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
