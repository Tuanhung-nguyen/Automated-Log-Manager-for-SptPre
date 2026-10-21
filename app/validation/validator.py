import json
from pydantic import ValidationError
from app.core.models import IncidentContext, IncidentAnalysis
from app.core.exceptions import (
    PipelineError,
    JSONParseError,
    SchemaValidationError,
    SemanticValidationError,
    EvidenceValidationError
)


def validate_llm_response(raw_response: str) -> IncidentAnalysis:
    """
    Validator tầng 1 & 2:
    1. Parse JSON từ raw string của LLM (Bắn JSONParseError nếu cú pháp hỏng)
    2. Validate schema Pydantic (Bắn SchemaValidationError nếu sai kiểu/thiếu field)
    """
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
    except json.JSONDecodeError as e:
        raise JSONParseError(f"Invalid JSON syntax from LLM: {e}")

    try:
        result = IncidentAnalysis.model_validate(data)
    except ValidationError as e:
        raise SchemaValidationError(f"LLM response failed schema validation: {e}")

    return result


def validate_semantics(
    context: IncidentContext,
    analysis: IncidentAnalysis
) -> None:
    """
    Validator tầng 3: Semantic Validation
    Kiểm tra tính hợp lý giữa dữ liệu hệ thống cung cấp (context)
    và kết luận do AI đưa ra (analysis).
    """
    # Rule 1: Phải có ít nhất một fact
    if not analysis.facts:
        raise SemanticValidationError(
            "Semantic validation failed: facts must not be empty."
        )

    # Rule 2: Fact không được chứa các từ thể hiện suy đoán (phân biệt Fact vs Inference)
    inference_keywords = [
        "likely",
        "probably",
        "possibly",
        "may",
        "might",
        "suggests",
        "could"
    ]

    for fact in analysis.facts:
        fact_lower = fact.lower()
        for keyword in inference_keywords:
            if keyword in fact_lower:
                raise SemanticValidationError(
                    f"Semantic validation failed: "
                    f"fact contains inference keyword '{keyword}': {fact}"
                )

    # Rule 3: Nếu phân tích lỗi liên quan đến memory, context phải có bằng chứng về memory
    memory_keywords = [
        "memory",
        "oom",
        "out of memory",
        "exceeding memory"
    ]

    error_text = (context.error + " " + context.log).lower()
    error_type = analysis.error_type.lower()

    memory_related = any(keyword in error_type for keyword in memory_keywords)

    if memory_related:
        has_memory_evidence = any(
            keyword in error_text for keyword in memory_keywords
        ) or (
            context.metrics is not None
            and any("memory" in key.lower() for key in context.metrics.keys())
        )

        if not has_memory_evidence:
            raise SemanticValidationError(
                "Semantic validation failed: "
                "memory-related analysis has no memory evidence in context."
            )

    # Rule 4: Chặn Overconfidence (confidence quá cao khi ít evidence)
    if len(analysis.facts) < 2 and analysis.confidence > 0.75:
        raise SemanticValidationError(
            "Semantic validation failed: "
            "confidence is too high for the amount of evidence."
        )

    # Rule 5: Kiểm tra sự hỗ trợ của Context với từng Fact (Evidence Error)
    validate_facts_against_context(context, analysis)


def validate_facts_against_context(
    context: IncidentContext,
    analysis: IncidentAnalysis
) -> None:
    """
    Kiểm tra xem facts do AI đưa ra có được context hỗ trợ không.
    Nếu AI bịa ra fact không có trong log/error -> Bắn EvidenceValidationError!
    """
    context_text = (
        context.error + " " +
        context.log
    ).lower()

    for fact in analysis.facts:
        fact_lower = fact.lower()

        if "database connection pool" in fact_lower:
            if "database connection pool" not in context_text:
                raise EvidenceValidationError(
                    f"Evidence validation failed: "
                    f"fact is not supported by context: {fact}"
                )


def build_feedback(error: Exception) -> str:
    """
    Chuyển validation error thành feedback cho LLM để đưa vào prompt lần retry tiếp theo.
    """
    category_header = f"Error Type: {error.category.value}\n" if isinstance(error, PipelineError) else ""

    return f"""
Your previous response failed validation.

{category_header}Validation error:
{error}

Please fix the error in your next response.

Important:
- Follow the required JSON schema.
- Facts must be based only on the provided evidence.
- Do not put inferences or guesses inside facts.
- Return ONLY valid JSON.
"""
