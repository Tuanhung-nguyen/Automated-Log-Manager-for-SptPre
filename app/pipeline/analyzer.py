import json
from app.core.models import IncidentContext, IncidentAnalysis
from app.llm.client import LLMClient


class IncidentAnalyzer:

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def build_prompt(
        self,
        context: IncidentContext,
        feedback: str | None = None
    ) -> str:
        """
        Chuyển IncidentContext thành prompt cho LLM, có thể kèm theo feedback từ lần thử trước.
        """
        metrics_text = ""
        if context.metrics:
            metrics_text = "\n".join(
                f"- {key}: {value}"
                for key, value in context.metrics.items()
            )

        schema_str = json.dumps(IncidentAnalysis.model_json_schema(), indent=2)

        prompt = f"""
        You are a Data Engineering incident analysis assistant.

        Analyze the following pipeline incident.

        Timestamp:
        {context.timestamp}

        Component:
        {context.component}

        Error:
        {context.error}

        Log:
        {context.log}

        Metrics:
        {metrics_text}

        Your task:
        1. Identify what happened based only on the provided evidence.
        2. Extract direct facts from the log and metrics. In "facts", include ONLY verifiable facts directly present in the log or metrics. Do NOT include unproven assumptions or speculative causes.
        3. Provide reasonable inferences based on facts.
        4. Suggest possible causes.
        5. Provide a recommendation.
        6. Estimate your confidence from 0.0 to 1.0.

        You MUST respond with ONLY a valid JSON object strictly matching this IncidentAnalysis JSON schema:
        {schema_str}
        """

        if feedback:
            prompt += f"""
                Previous attempt feedback:
                {feedback}

                Fix the previous error and return ONLY valid JSON.
                """

        return prompt

    def analyze(
        self,
        context: IncidentContext,
        feedback: str | None = None
    ) -> str:
        """
        Phân tích một IncidentContext bằng LLM và trả về raw response.
        """
        prompt = self.build_prompt(context, feedback)
        response = self.llm_client.generate(prompt)
        return response
