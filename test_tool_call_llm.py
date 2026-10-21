import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core import ToolCall
from app.llm import LLMClient

prompt = """
Bạn là AI hỗ trợ vận hành Data Engineering.

Bạn có thể sử dụng tool sau:

get_pipeline_status(pipeline_id)
- Lấy trạng thái pipeline.

Nếu cần thông tin từ pipeline, hãy trả về JSON đúng format:

{
    "tool_name": "...",
    "arguments": {...}
}

Nếu không cần tool, trả:

{
    "tool_name": null,
    "arguments": {}
}

Incident:
Pipeline etl_users đang có dấu hiệu thất bại.

Trả về ONLY valid JSON, không kèm bất kỳ giải thích, markdown fences hay text thừa nào.
"""

def main():
    print("Connecting to Ollama (qwen3:8b, timeout=600s)...")
    client = LLMClient(model="qwen3:8b", timeout=600, temperature=0.0)
    raw_response = client.generate(prompt)
    print("\n--- RAW RESPONSE TỪ LLM ---")
    print(raw_response)

    # Clean markdown fences nếu có
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        data = json.loads(cleaned)
        tool_call = ToolCall.model_validate(data)
        print("\n--- PARSED PYDANTIC TOOLCALL ---")
        print(f"Tool Name : {tool_call.tool_name}")
        print(f"Arguments : {tool_call.arguments}")
        print(f"Pydantic JSON:\n{tool_call.model_dump_json(indent=2)}")
        print("\n=> TEST TOOL CALL PASSED THÀNH CÔNG! 🎉")
    except Exception as e:
        print(f"\n=> Parse ToolCall thất bại: {e}")

if __name__ == "__main__":
    main()
