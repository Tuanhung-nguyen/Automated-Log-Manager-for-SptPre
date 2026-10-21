import sys
import json
import time
import requests
from pathlib import Path

# Đảm bảo in unicode tiếng Việt mượt mà trên console Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Thêm project root vào sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core import IncidentContext, AnalysisResult
from app.llm import LLMClient
from app.pipeline import IncidentPipeline, AgentRunner
from app.config import settings


def check_ollama_available(base_url: Optional[str] = None) -> bool:
    base_url = base_url or settings.OLLAMA_BASE_URL
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def main():
    print("=" * 90)
    print("   KIỂM THỬ THỰC TẾ: AGENT ĐIỀU TRA SỰ CỐ THẬT TỪ GITHUB ACTIONS WORKFLOW")
    print(f"   Repository: {settings.GITHUB_OWNER}/{settings.GITHUB_REPO} | Run #1 (ID: 33149238175)")
    print("=" * 90)

    if not check_ollama_available():
        print(f"❌ LỖI: Không kết nối được tới Ollama tại {settings.OLLAMA_BASE_URL}")
        sys.exit(1)

    print(f"✅ Đã kết nối Ollama service (Model: {settings.OLLAMA_MODEL})")

    # Khởi tạo LLMClient thật và AgentRunner
    llm_client = LLMClient()
    agent_runner = AgentRunner(client=llm_client, max_iterations=4)
    pipeline = IncidentPipeline(runner=agent_runner)

    # Chuẩn bị IncidentContext từ sự cố thực tế
    incident_context = IncidentContext(
        timestamp="2026-08-28 06:49:20",
        component="GitHub Actions Ingestion",
        error="Workflow Run Failed: ingest-spotify-personal",
        log=f"Workflow run #1 (run_id: 33149238175) of repository {settings.GITHUB_REPO} (owner: {settings.GITHUB_OWNER}) terminated with failure conclusion. Please investigate root cause."
    )

    print("\n[BƯỚC 1] Tiếp nhận sự cố vào IncidentPipeline:")
    print(f" • Component : {incident_context.component}")
    print(f" • Error     : {incident_context.error}")
    print(f" • Log sơ bộ : {incident_context.log}")

    print("\n[BƯỚC 2] Kích hoạt AgentRunner điều tra tự chủ qua các Tool GitHub API...")
    start_time = time.perf_counter()
    result: AnalysisResult = pipeline.run(incident_context)
    duration_s = time.perf_counter() - start_time

    rec = result.execution_record

    # In kết quả chi tiết
    print("\n" + "=" * 90)
    print("              BÁO CÁO KẾT QUẢ ĐIỀU TRA TOÀN TRÌNH TỪ AGENT")
    print("=" * 90)
    print(f"Trạng thái Pipeline   : {result.status}")
    print(f"Mã thực thi (ID)      : {rec.execution_id}")
    print(f"Tổng thời gian chạy   : {rec.total_duration_ms:.2f} ms (~{duration_s:.1f}s)")
    print(f"Tổng số Tool đã gọi   : {len(rec.tool_calls)}")

    for idx, tc in enumerate(rec.tool_calls, 1):
        print(f"\n [TOOL CALL #{idx}]:")
        print(f"  • Tool Name : {tc.get('tool_name')}")
        print(f"  • Arguments : {json.dumps(tc.get('arguments', {}), ensure_ascii=False)}")
        res_preview = str(tc.get('result', {}))
        if len(res_preview) > 300:
            res_preview = res_preview[:300] + "... (truncated)"
        print(f"  • Result Preview: {res_preview}")

    if result.analysis:
        analysis = result.analysis
        print("\n" + "-" * 90)
        print("         BÁO CÁO PHÂN TÍCH NGUYÊN NHÂN GỐC (RCA) THIẾT LẬP BỞI AGENT")
        print("-" * 90)
        print(f"Thành phần (Component) : {analysis.component}")
        print(f"Loại lỗi (Error Type)  : {analysis.error_type}")
        print(f"Mức độ (Severity)      : {analysis.severity}")
        print(f"Bằng chứng (Facts)     : {analysis.facts}")
        print(f"Suy luận (Inferences)  : {analysis.inferences}")
        print(f"Nguyên nhân khả dĩ     : {analysis.possible_causes}")
        print(f"Khuyến nghị xử lý      : {analysis.recommendation}")
        print(f"Độ tự tin              : {analysis.confidence * 100}%")
    else:
        print("\n⚠️ Không tạo được báo cáo RCA hoàn chỉnh.")

    print("\n" + "=" * 90)
    tools_called = [tc.get('tool_name') for tc in rec.tool_calls]
    step_jobs_called = "get_github_workflow_jobs" in tools_called
    step_logs_called = "get_github_job_logs" in tools_called
    print("ĐÁNH GIÁ CÁC TIÊU CHÍ:")
    print(f"  1. Gọi tool khoanh vùng Jobs ({'get_github_workflow_jobs'}): {'✅ ĐẠT' if step_jobs_called else '❌ CHƯA GỌI'}")
    print(f"  2. Gọi tool tải Log chi tiết ({'get_github_job_logs'}):     {'✅ ĐẠT' if step_logs_called else '❌ CHƯA GỌI'}")
    print(f"  3. Hoàn tất RCA với LLM thật:                                 {'✅ ĐẠT' if result.analysis else '❌ CHƯA ĐẠT'}")
    print("=" * 90)


if __name__ == "__main__":
    main()
