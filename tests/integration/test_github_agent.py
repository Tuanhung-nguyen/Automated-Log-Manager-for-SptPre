import sys
import json
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

from app.llm import LLMClient
from app.tools.loop import run_tool_loop


def check_ollama_available(base_url: str = "http://127.0.0.1:11434") -> bool:
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def main():
    print("=" * 80)
    print("   TEST THỰC TẾ: AGENT GỌI GITHUB API THẬT ĐỂ KIỂM TRA WORKFLOW RUNS")
    print("=" * 80)

    if not check_ollama_available():
        print("❌ LỖI: Không kết nối được tới Ollama tại http://127.0.0.1:11434")
        sys.exit(1)

    print("✅ Đã kết nối Ollama service (Model: qwen3:8b, Temperature: 0.0)")

    # Khởi tạo LLMClient
    client = LLMClient(model="qwen3:8b", timeout=600, temperature=0.0)

    # Yêu cầu thực tế từ người dùng
    user_request = (
        "Kiểm tra 5 lần chạy GitHub Actions gần nhất của repository Spotify_Premium "
        "(chủ sở hữu Tuanhung-nguyen). Tóm tắt lần chạy nào thành công, thất bại hoặc đang chạy."
    )

    print(f"\n[YÊU CẦU NGƯỜI DÙNG]:\n\"{user_request}\"\n")

    # Kích hoạt Agent Tool Loop
    loop_result = run_tool_loop(
        context=user_request,
        client=client,
        max_iterations=4
    )

    print("=" * 80)
    print("               KẾT QUẢ ĐÁNH GIÁ 3 TIÊU CHÍ")
    print("=" * 80)

    # 1. Kiểm tra Agent có tự chọn get_github_workflow_runs không?
    tool_history = loop_result.get("tool_history", [])
    tools_called = [tc.tool_name for tc, _ in tool_history]
    criterion_1 = "get_github_workflow_runs" in tools_called
    print(f"1. Agent tự chọn tool: {'✅ ĐẠT' if criterion_1 else '❌ CHƯA ĐẠT'}")
    print(f"   • Danh sách tool đã gọi: {tools_called}")

    # 2. Tool có trả về dữ liệu thật từ GitHub không?
    real_data_obtained = False
    workflow_runs = []
    for tc, tr in tool_history:
        if tc.tool_name == "get_github_workflow_runs":
            res_data = tr.result.get("result", {})
            if "workflow_runs" in res_data and len(res_data["workflow_runs"]) > 0:
                real_data_obtained = True
                workflow_runs = res_data["workflow_runs"]
                print(f"2. Tool trả về dữ liệu thật từ GitHub: ✅ ĐẠT")
                print(f"   • Repository: {res_data.get('repository')}")
                print(f"   • Tổng số runs có sẵn: {res_data.get('total_count')}")
                print(f"   • Số runs lấy về: {len(workflow_runs)}")
                for r in workflow_runs[:3]:
                    print(f"     - Run #{r.get('run_number')} ({r.get('name')}): Status={r.get('status')}, Conclusion={r.get('conclusion')}")
                break

    if not real_data_obtained:
        print("2. Tool trả về dữ liệu thật từ GitHub: ❌ CHƯA ĐẠT")

    # 3. Agent có dựa trên kết quả đó để trả lời chính xác không?
    final_summary = loop_result.get("summary") or ""
    final_analysis = loop_result.get("analysis")
    has_answer = bool(final_summary or final_analysis)
    
    print(f"3. Agent tổng hợp và trả lời: {'✅ ĐẠT' if has_answer else '❌ CHƯA ĐẠT'}")
    if final_summary:
        print(f"\n[NỘI DUNG TỔNG HỢP TỪ AGENT]:\n{final_summary}\n")
    elif final_analysis:
        print(f"\n[NỘI DUNG PHÂN TÍCH TỪ AGENT]:\n{final_analysis.model_dump_json(indent=2)}\n")

    overall = criterion_1 and real_data_obtained and has_answer
    print("=" * 80)
    print(f"TỔNG KẾT: {'🏆 PASSED TOÀN BỘ 3 TIÊU CHÍ' if overall else '⚠️ CHƯA ĐẠT'}")
    print("=" * 80)


if __name__ == "__main__":
    main()
