import re
import json
from typing import Optional, Any, Callable
from app.core import ToolCall, ToolResult, IncidentAnalysis
from app.llm import LLMClient
from app.tools.registry import get_tools_metadata
from app.tools.executor import run_tool_call
from app.tools.policy import evaluate_policy, PolicyDecision


def clean_json_response(raw_text: str) -> str:
    """Loại bỏ thẻ suy nghĩ <think>...</think>, markdown fences ```json ... ``` hoặc trích xuất khối JSON hợp lệ."""
    cleaned = raw_text.strip()

    # 1. Loại bỏ các thẻ suy nghĩ reasoning của LLM nếu có
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()

    # 2. Tìm khối markdown ```json ... ``` hoặc ``` ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 3. Loại bỏ ký hiệu fence ở đầu và cuối dòng nếu còn
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    # 4. Tìm cặp ngoặc { ... } ngoài cùng
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start : end + 1].strip()

    return cleaned


def build_tool_loop_prompt(
    context: str,
    tools_metadata: list[dict],
    tool_history: list[tuple[ToolCall, ToolResult]]
) -> str:
    """
    Xây dựng prompt động cho LLM theo từng vòng lặp:
    Bao gồm Context ban đầu + Danh sách Tools + Lịch sử các tool đã gọi và kết quả.
    """
    tools_json = json.dumps(tools_metadata, indent=2, ensure_ascii=False)
    analysis_schema = json.dumps(IncidentAnalysis.model_json_schema(), indent=2)

    history_text = ""
    if tool_history:
        history_text = "\nLỊCH SỬ CÁC CÔNG CỤ ĐÃ GỌI VÀ KẾT QUẢ TỪ HỆ THỐNG:\n"
        for idx, (tc, tr) in enumerate(tool_history, 1):
            history_text += f"""
[Lần gọi {idx}]
Tool: {tc.tool_name}
Tham số: {json.dumps(tc.arguments, ensure_ascii=False)}
Kết quả trả về:
{json.dumps(tr.result, indent=2, ensure_ascii=False)}
"""

    prompt = f"""
Bạn là AI hỗ trợ vận hành Data Engineering thông minh (Agent).

Ngữ cảnh sự cố:
{context}

Danh sách tools bạn có thể sử dụng:
{tools_json}
{history_text}

QUY TẮC ĐIỀU TRA SỰ CỐ (INVESTIGATION POLICY):
1. Bạn CHƯA ĐƯỢC kết luận nếu chưa có bằng chứng thực tế:
   - Nếu cần kiểm tra danh sách các lần chạy: Hãy gọi tool `get_github_workflow_runs`.
   - Nếu đã có run_id của lần chạy bị lỗi (failure) nhưng chưa biết job hoặc step nào gãy: Hãy gọi tool `get_github_workflow_jobs` với `run_id`.
   - Nếu đã xác định được job_id bị lỗi nhưng chưa có nội dung log console chi tiết: BẮT BUỘC phải gọi tiếp tool `get_github_job_logs` với `job_id` để đọc terminal traceback.
   - Nếu là pipeline nội bộ: Hãy gọi `get_pipeline_status` hoặc `get_pipeline_logs`.
   Trả về JSON:
   {{
       "action": "tool_call",
       "tool_name": "<tên tool trong danh sách>",
       "arguments": {{<các tham số tương ứng>}}
   }}

2. Khi bạn ĐÃ CÓ ĐẦY ĐỦ THÔNG TIN:
   - Nếu là phân tích sự cố (Incident RCA):
     Trả về JSON:
     {{
         "action": "final_answer",
         "analysis": <IncidentAnalysis JSON khớp với schema sau>
     }}
   - Nếu là yêu cầu kiểm tra, tra cứu hoặc tóm tắt trạng thái:
     Trả về JSON:
     {{
         "action": "final_answer",
         "summary": "<Tóm tắt chi tiết, rõ ràng dựa trên dữ liệu thực tế thu được từ các công cụ đã gọi>"
     }}

IncidentAnalysis JSON Schema (nếu là phân tích sự cố):
{analysis_schema}

Yêu cầu quan trọng: Trả về ONLY valid JSON, không kèm bất kỳ lời giải thích hay văn bản thừa nào ngoài JSON.
"""
    return prompt


def run_tool_loop(
    context: str,
    client: Optional[LLMClient] = None,
    max_iterations: int = 4,
    approval_callback: Optional[Callable[[ToolCall], bool]] = None
) -> dict[str, Any]:
    """
    Vòng lặp Agent Tool Loop tích hợp Policy & Human Approval:
    LLM -> ToolCall -> Policy Check:
       - ALLOW: Tự động thực thi an toàn
       - REQUIRE_APPROVAL: Chờ Human Approval (qua approval_callback)
       - DENY: Từ chối thực thi
    -> ToolResult -> LLM -> Lặp cho tới khi Final Answer hoặc đạt max_iterations.
    """
    if client is None:
        client = LLMClient(model="qwen3:8b", timeout=600, temperature=0.0)

    tools_metadata = get_tools_metadata()
    tool_history: list[tuple[ToolCall, ToolResult]] = []
    final_analysis: Optional[IncidentAnalysis] = None
    final_summary: Optional[str] = None

    print("\n" + "=" * 80)
    print("   BẮT ĐẦU AGENT TOOL LOOP (CÓ POLICY & HUMAN APPROVAL)")
    print("=" * 80)
    print(f"Ngữ cảnh ban đầu: {context.strip()}")
    print(f"Số vòng lặp tối đa: {max_iterations}")

    for iteration in range(1, max_iterations + 1):
        print("\n" + "=" * 80)
        print(f" [VÒNG LẶP {iteration}/{max_iterations}] Đang gửi yêu cầu tới LLM...")
        print("=" * 80)

        prompt = build_tool_loop_prompt(context, tools_metadata, tool_history)
        raw_response = client.generate(prompt)
        cleaned = clean_json_response(raw_response)

        try:
            data = json.loads(cleaned)
        except Exception as e:
            print(f"❌ [LỖI JSON VÒNG {iteration}] Không parse được JSON từ LLM: {e}")
            print(f"Phản hồi thô:\n{raw_response}")
            break

        action = data.get("action")
        tool_name = data.get("tool_name")

        # Trường hợp 1: LLM đề xuất gọi Tool
        if action == "tool_call" or (tool_name and tool_name in [t["name"] for t in tools_metadata]):
            args = data.get("arguments", {})
            t_name = tool_name or data.get("tool_name")
            tool_call = ToolCall(tool_name=t_name, arguments=args)

            print(f"\n🤖 [LLM ĐỀ XUẤT HÀNH ĐỘNG]")
            print(f"   • Tên Tool  : {tool_call.tool_name}")
            print(f"   • Tham số   : {json.dumps(tool_call.arguments, ensure_ascii=False)}")

            # Đánh giá Policy Guardrail
            decision = evaluate_policy(tool_call.tool_name)
            approved = False

            if decision == PolicyDecision.ALLOW:
                print(f"\n🛡️ [POLICY GUARDRAIL: ALLOW]")
                print(f"   -> Tool '{tool_call.tool_name}' an toàn (READ), tự động phê duyệt thực thi.")
                approved = True
            elif decision == PolicyDecision.REQUIRE_APPROVAL:
                print(f"\n🛡️ [POLICY GUARDRAIL: REQUIRE_APPROVAL]")
                print(f"   -> Tool '{tool_call.tool_name}' có rủi ro (WRITE), cần Người quản trị phê duyệt!")
                if approval_callback:
                    approved = approval_callback(tool_call)
                else:
                    approved = False
                decision_str = "ĐỒNG Ý (Approved)" if approved else "TỪ CHỐI (Rejected)"
                print(f"   -> Quyết định phê duyệt: {decision_str}")
            else:
                print(f"\n🛡️ [POLICY GUARDRAIL: DENY]")
                print(f"   -> Tool '{tool_call.tool_name}' bị cấm hoàn toàn!")
                approved = False

            # Thực thi Tool
            tool_result = run_tool_call(tool_call, approved=approved)
            print(f"\n⚙️ [KẾT QUẢ THỰC THI TOOL (OBSERVATION)]")
            formatted_res = json.dumps(tool_result.result, indent=2, ensure_ascii=False)
            print(f"{formatted_res}")

            # Ghi nhận vào lịch sử hội thoại
            tool_history.append((tool_call, tool_result))

        # Trường hợp 2: LLM đưa ra Final Answer
        elif action == "final_answer" or "analysis" in data or "error_type" in data or "summary" in data:
            analysis_data = data.get("analysis", data)
            if isinstance(analysis_data, dict) and "error_type" in analysis_data and "component" in analysis_data:
                final_analysis = IncidentAnalysis.model_validate(analysis_data)
                print(f"\n🎯 [KẾT LUẬN CUỐI CÙNG TỪ LLM (FINAL ANSWER - RCA)] (sau {iteration} vòng lặp)")
                print(f"   • Component      : {final_analysis.component}")
                print(f"   • Error Type     : {final_analysis.error_type}")
                print(f"   • Severity       : {final_analysis.severity}")
                print(f"   • Facts          : {final_analysis.facts}")
                print(f"   • Inferences     : {final_analysis.inferences}")
                print(f"   • Possible Causes: {final_analysis.possible_causes}")
                print(f"   • Recommendation : {final_analysis.recommendation}")
                print(f"   • Confidence     : {final_analysis.confidence * 100}%")
            else:
                final_summary = data.get("summary") or data.get("answer") or str(analysis_data)
                print(f"\n🎯 [KẾT LUẬN CUỐI CÙNG TỪ LLM (FINAL ANSWER - SUMMARY)] (sau {iteration} vòng lặp)")
                print(f"   {final_summary}")
            break

        else:
            print(f"⚠️ [VÒNG {iteration}] Phản hồi không xác định được hành động: {data}")
            break

    print("\n" + "=" * 80)
    if final_analysis or final_summary:
        print("   AGENT TOOL LOOP HOÀN THÀNH THÀNH CÔNG! 🎉")
        print(f"   • Tổng số tool đã gọi: {len(tool_history)}")
        if final_analysis:
            print(f"   • Kết luận chính: {final_analysis.error_type} ({final_analysis.component})")
        if final_summary:
            print(f"   • Nội dung tóm tắt: {final_summary[:120]}...")
    else:
        print(f"   AGENT TOOL LOOP DỪNG SAU {max_iterations} VÒNG (CHƯA HOÀN TẤT KẾT LUẬN).")
    print("=" * 80 + "\n")

    return {
        "success": (final_analysis is not None) or (final_summary is not None),
        "iterations": iteration,
        "tool_history": tool_history,
        "analysis": final_analysis,
        "summary": final_summary
    }
