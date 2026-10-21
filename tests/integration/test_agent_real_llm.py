import sys
import json
import time
import requests
from pathlib import Path
from typing import Any

# Đảm bảo in unicode tiếng Việt mượt mà trên console Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Thêm đường dẫn project root vào sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core import IncidentContext, AnalysisResult
from app.llm import LLMClient
from app.pipeline import IncidentPipeline, AgentRunner
from app.observability.records import ExecutionRecord


def check_ollama_available(base_url: str = "http://127.0.0.1:11434") -> bool:
    """Kiểm tra dịch vụ Ollama local có đang chạy không."""
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def run_benchmark_case(
    case_id: str,
    case_name: str,
    context: IncidentContext,
    ground_truth: dict[str, Any],
    pipeline: IncidentPipeline
) -> dict[str, Any]:
    """
    Thực thi 1 Benchmark Case với AgentRunner & IncidentPipeline.
    Đo thời gian, in chi tiết Observation, ExecutionRecord và đối chiếu Ground Truth.
    """
    print("\n" + "=" * 90)
    print(f" ▶ [{case_id}] {case_name.upper()}")
    print("=" * 90)
    print(f"  • Component : {context.component}")
    print(f"  • Error sơ bộ: {context.error}")
    print(f"  • Log ban đầu: {context.log}")
    print(f"  • Kỳ vọng GT : Loại lỗi='{ground_truth.get('expected_error_type')}', Detector={ground_truth.get('expected_detect')}")

    case_start = time.perf_counter()
    result: AnalysisResult = pipeline.run(context)
    case_duration_ms = (time.perf_counter() - case_start) * 1000

    rec: ExecutionRecord = result.execution_record

    # 1. In chi tiết quan sát thực thi (Observations & Tool Telemetry)
    print("\n" + "-" * 90)
    print(f" 🔍 [OBSERVATION & TELEMETRY CHO {case_id}]")
    print("-" * 90)
    if rec.tool_calls:
        print(f"  Tổng số tool đã thực thi: {len(rec.tool_calls)}")
        for idx, tc in enumerate(rec.tool_calls, 1):
            tool_name = tc.get("tool_name")
            arguments = tc.get("arguments", {})
            tool_res = tc.get("result", {})
            print(f"\n  [Observation {idx}] Tool: '{tool_name}' | Args: {json.dumps(arguments, ensure_ascii=False)}")
            print(f"  └─ Trạng thái: {'THÀNH CÔNG' if tool_res.get('success') else 'THẤT BẠI'}")
            print(f"  └─ Dữ liệu hệ thống phản hồi:")
            res_payload = tool_res.get("result", tool_res)
            print("     " + json.dumps(res_payload, indent=2, ensure_ascii=False).replace("\n", "\n     "))
    else:
        print("  (Không có Tool nào được gọi - Luồng xử lý không qua Agent Tool Loop)")

    # 2. In chi tiết ExecutionRecord (Observability)
    print("\n" + "-" * 90)
    print(f" 📊 [EXECUTION RECORD - DỮ LIỆU ĐO LƯỜNG TOÀN TRÌNH]")
    print("-" * 90)
    print(f"  • Execution ID          : {rec.execution_id}")
    print(f"  • Timestamp (UTC)       : {rec.timestamp}")
    print(f"  • Detector Filter       : {rec.detect_output} (Thời gian đo: {rec.detect_duration_ms:.2f} ms)")
    print(f"  • Final Status          : {rec.final_status}")
    print(f"  • Final Result Summary  : {rec.final_result or 'N/A'}")
    print(f"  • Tổng Tool Calls       : {len(rec.tool_calls)}")
    print(f"  • Tổng thời gian Pipeline: {rec.total_duration_ms:.2f} ms (~{rec.total_duration_ms / 1000:.2f}s)")

    if rec.attempts:
        for att in rec.attempts:
            print(f"  • Attempt #{att.attempt}        : Status={att.status}, Duration={att.duration_ms:.2f} ms, LLM={att.llm_duration_ms} ms")

    # 3. Đánh giá kết quả đối chiếu Ground Truth
    actual_error_type = result.analysis.error_type if result.analysis else "N/A"
    actual_facts = result.analysis.facts if result.analysis else []
    
    # Kiểm tra tính khớp Ground Truth
    detect_matched = (rec.detect_output == ground_truth["expected_detect"])
    
    # Kiểm tra tool: Đạt nếu gọi ít nhất 1 tool điều tra hợp lệ trong danh sách kỳ vọng
    tools_called = [tc["tool_name"] for tc in rec.tool_calls]
    expected_tools = ground_truth.get("expected_tools", [])
    if expected_tools:
        # Agent thông minh có thể gọi get_pipeline_logs trực tiếp hoặc cả status + logs
        tools_matched = any(t in tools_called for t in expected_tools)
    else:
        tools_matched = (len(tools_called) == 0)

    # Kiểm tra error_type (linh hoạt theo từ khóa)
    expected_kw = ground_truth.get("expected_keywords", [])
    if expected_kw:
        error_matched = any(kw.lower() in actual_error_type.lower() for kw in expected_kw)
    else:
        error_matched = (result.status == "SKIPPED")

    # Kiểm tra facts có chứa bằng chứng từ observation
    facts_matched = True
    required_fact_kw = ground_truth.get("fact_keywords", [])
    if required_fact_kw:
        facts_str = " ".join(actual_facts).lower()
        facts_matched = any(kw.lower() in facts_str for kw in required_fact_kw)

    passed = detect_matched and tools_matched and error_matched and facts_matched

    print("\n" + "-" * 90)
    print(f" 🎯 [ĐỐI CHIẾU GROUND TRUTH & CHẤT LƯỢNG AGENT]")
    print("-" * 90)
    print(f"  [1] Bộ lọc Detector  : {'✅ ĐẠT' if detect_matched else '❌ SAI'} (Thực tế: {rec.detect_output} vs Kỳ vọng: {ground_truth['expected_detect']})")
    print(f"  [2] Gọi Tools        : {'✅ ĐẠT' if tools_matched else '❌ SAI'} (Đã gọi: {tools_called} vs Kỳ vọng: {expected_tools})")
    print(f"  [3] Loại lỗi kết luận: {'✅ ĐẠT' if error_matched else '❌ SAI'} (Thực tế: '{actual_error_type}')")
    if actual_facts:
        print(f"  [4] Bằng chứng (Facts: {'✅ ĐẠT' if facts_matched else '❌ THIẾU'} (Facts: {actual_facts})")
    print(f"  => ĐÁNH GIÁ TỔNG THỂ : {'🏆 PASSED (ĐẠT CHUẨN)' if passed else '⚠️ FAILED (CHƯA ĐẠT)'}")

    return {
        "case_id": case_id,
        "case_name": case_name,
        "status": rec.final_status,
        "detect_output": rec.detect_output,
        "detect_duration_ms": rec.detect_duration_ms,
        "tools_called": tools_called,
        "error_type": actual_error_type,
        "facts_count": len(actual_facts),
        "total_duration_ms": rec.total_duration_ms,
        "passed": passed
    }


def main():
    print("=" * 90)
    print("      BENCHMARK ĐÁNH GIÁ AGENT RUNNER VỚI LLM THẬT (OLLAMA QWEN3:8B)")
    print("      Đo lường thời gian, quan sát Observation & kiểm tra ExecutionRecord")
    print("=" * 90)

    # 1. Kiểm tra kết nối Ollama
    if not check_ollama_available():
        print("❌ LỖI: Không kết nối được tới Ollama tại http://127.0.0.1:11434")
        print("💡 Hãy đảm bảo bạn đã khởi động Ollama trên máy: `ollama run qwen3:8b`")
        sys.exit(1)

    print("✅ Đã kết nối thành công tới Ollama service.")
    print("🧠 Model sử dụng: qwen3:8b (Temperature: 0.0)")

    # 2. Khởi tạo LLMClient thật và AgentRunner
    llm_client = LLMClient(model="qwen3:8b", timeout=600, temperature=0.0)
    agent_runner = AgentRunner(client=llm_client, max_iterations=4)
    pipeline = IncidentPipeline(runner=agent_runner)

    # 3. Định nghĩa 3 Benchmark Cases đại diện
    test_cases = [
        # CASE A: Sự cố Database Connection
        {
            "id": "CASE-A",
            "name": "Sự cố kết nối Database (Connection Timeout)",
            "context": IncidentContext(
                timestamp="2026-10-13 01:30:00",
                component="ETL Pipeline",
                error="Pipeline failure alert",
                log="Job pipe_orders_etl failed on step transform_daily_orders. Please investigate root cause."
            ),
            "ground_truth": {
                "expected_detect": True,
                "expected_tools": ["get_pipeline_status", "get_pipeline_logs"],
                "expected_error_type": "Database Connection Timeout / Refused",
                "expected_keywords": ["database", "connection", "timeout", "refused", "db"],
                "fact_keywords": ["5432", "timeout", "connection refused", "postgresql"]
            }
        },
        # CASE B: Sự cố Memory / Out of Memory (OOM)
        {
            "id": "CASE-B",
            "name": "Sự cố tràn bộ nhớ (Spark OOM / Memory Limit)",
            "context": IncidentContext(
                timestamp="2026-10-13 01:35:00",
                component="Spark Processing",
                error="Executor task failure alert",
                log="Job pipe_spark_memory failed with exit code 137 on executor task. Please investigate."
            ),
            "ground_truth": {
                "expected_detect": True,
                "expected_tools": ["get_pipeline_status", "get_pipeline_logs"],
                "expected_error_type": "OutOfMemoryError / Memory Limit Exceeded",
                "expected_keywords": ["memory", "oom", "outofmemory", "heap", "yarn"],
                "fact_keywords": ["heap", "memory", "outofmemoryerror", "yarn", "executor"]
            }
        },
        # CASE C: Log bình thường (Healthy Pipeline) -> Detector chặn sớm
        {
            "id": "CASE-C",
            "name": "Log bình thường không có sự cố (Normal Execution)",
            "context": IncidentContext(
                timestamp="2026-10-13 01:40:00",
                component="Data Ingestion",
                error="",
                log="Job pipe_orders_sync completed successfully. Processed 250,000 records in 45s without incident."
            ),
            "ground_truth": {
                "expected_detect": False,
                "expected_tools": [],
                "expected_error_type": "SKIPPED",
                "expected_keywords": [],
                "fact_keywords": []
            }
        }
    ]

    benchmark_records = []

    # 4. Chạy từng Case
    for tc in test_cases:
        record = run_benchmark_case(
            case_id=tc["id"],
            case_name=tc["name"],
            context=tc["context"],
            ground_truth=tc["ground_truth"],
            pipeline=pipeline
        )
        benchmark_records.append(record)

    # 5. Bảng tổng kết Benchmark toàn diện
    print("\n" + "=" * 95)
    print("                 BẢNG TỔNG KẾT BENCHMARK TOÀN TRÌNH (PHASE 5 AGENT)")
    print("=" * 95)
    print(f"{'Case ID':<8} | {'Trạng thái':<10} | {'Detector':<9} | {'Tools Gọi':<22} | {'Thời gian (s)':<14} | {'Kết quả':<10}")
    print("-" * 95)

    all_passed = True
    for r in benchmark_records:
        tools_str = ",".join(r["tools_called"]) if r["tools_called"] else "None (Skipped)"
        passed_str = "PASSED ✅" if r["passed"] else "FAILED ❌"
        if not r["passed"]:
            all_passed = False
        print(f"{r['case_id']:<8} | {r['status']:<10} | {str(r['detect_output']):<9} | {tools_str:<22} | {r['total_duration_ms']/1000:<14.2f} | {passed_str:<10}")

    print("=" * 95)
    if all_passed:
        print("🎉 TẤT CẢ 3 BENCHMARK CASES ĐÃ VƯỢT QUA XUẤT SẮC!")
        print("Hệ thống đã chứng minh: Agent tự chọn đúng tool, phân tích đúng nguyên nhân, và Detector lọc sớm hiệu quả.")
    else:
        print("⚠️ Một số test cases cần điều chỉnh prompt hoặc ngưỡng kiểm tra.")
    print("=" * 95)


if __name__ == "__main__":
    main()
