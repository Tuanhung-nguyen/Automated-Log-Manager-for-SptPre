import sys
import argparse
from app.config import settings
from app.llm import LLMClient
from app.pipeline import IncidentPipeline, AgentRunner
from app.monitor import AlertNotifier
from app.adapters import get_adapter, list_supported_sources

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def build_pipeline() -> IncidentPipeline:
    """Khởi tạo IncidentPipeline hoàn chỉnh kết nối với AgentRunner và LLMClient."""
    llm_client = LLMClient(
        model=settings.OLLAMA_MODEL,
        timeout=settings.LLM_TIMEOUT,
        temperature=settings.LLM_TEMPERATURE
    )
    runner = AgentRunner(client=llm_client, max_iterations=4)
    pipeline = IncidentPipeline(runner=runner)
    return pipeline


def main():
    supported = list_supported_sources()
    parser = argparse.ArgumentParser(
        description="CLI Công Cụ AI Điều Tra Sự Cố Pipeline Theo Yêu Cầu (On-Demand Investigation)"
    )
    parser.add_argument(
        "--source",
        type=str,
        default="github",
        help=f"Nền tảng/công cụ cần kiểm tra. Hiện hỗ trợ: {supported} (mặc định: github)"
    )
    parser.add_argument(
        "--id",
        type=str,
        required=True,
        help="Mã định danh sự cố cần phân tích ngay (run_id của GitHub Actions, job_id của Databricks, v.v.)"
    )
    parser.add_argument(
        "--owner",
        type=str,
        default=None,
        help="Owner/Tổ chức (mặc định lấy từ .env)"
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Tên Repository/Dự án (mặc định lấy từ .env)"
    )

    args = parser.parse_args()

    # 1. Lấy Adapter tương ứng qua get_adapter
    try:
        adapter = get_adapter(args.source)
    except ValueError as e:
        print(f"❌ [LỖI NGUỒN]: {e}")
        return

    print("=" * 80)
    print("      AI DATA ENGINEERING INCIDENT INVESTIGATOR (ON-DEMAND)")
    print("=" * 80)
    print(f"• Nền tảng (Source) : {adapter.source_name.upper()}")
    print(f"• Mã sự cố (ID)     : {args.id}")
    llm_info = "Google Gemini 3.8 Flash (Cloud)" if settings.GEMINI_API_KEY else f"{settings.OLLAMA_MODEL} ({settings.OLLAMA_BASE_URL})"
    print(f"• LLM Model         : {llm_info}")
    print("=" * 80)

    # 2. Lấy dữ liệu sự cố từ nguồn
    print(f"\n🔍 Đang lấy thông tin log của sự cố '{args.id}' từ {adapter.source_name}...")
    extra_kwargs = {}
    if args.owner:
        extra_kwargs["owner"] = args.owner
    if args.repo:
        extra_kwargs["repo"] = args.repo

    try:
        context = adapter.fetch_incident_context(args.id, **extra_kwargs)
    except Exception as e:
        print(f"❌ [LỖI LẤY LOG TỪ NGUỒN]: {e}")
        return

    # 3. Kích hoạt Agent Pipeline phân tích
    print(f"🚀 [KÍCH HOẠT PHÂN TÍCH] Đang chuyển log sang Agent Pipeline...")
    pipeline = build_pipeline()
    result = pipeline.run(context)

    # 4. Gửi/Lưu cảnh báo và kết thúc ngay
    notifier = AlertNotifier()
    notifier.send_alert(result)
    print("\n✅ Phân tích hoàn tất. Đã lưu log cảnh báo vào data/monitor/alerts.log.")


if __name__ == "__main__":
    main()
