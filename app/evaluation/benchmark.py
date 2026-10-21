from pydantic import BaseModel
from app.core.models import IncidentContext


class GroundTruth(BaseModel):
    """Ground Truth chuẩn do con người định nghĩa trước cho từng case benchmark."""
    incident: bool
    error_type: str | None = None
    required_facts: list[str] = []


class BenchmarkCase(BaseModel):
    """Ghép ngữ cảnh đầu vào (IncidentContext) với đáp án chuẩn (GroundTruth)."""
    case_id: str
    description: str
    context: IncidentContext
    ground_truth: GroundTruth


# =====================================================================
# BỘ 7 BENCHMARK CASES DỰA TRÊN PHASE 3 (SYNTHETIC BENCHMARK)
# =====================================================================
BENCHMARK_CASES: list[BenchmarkCase] = [
    BenchmarkCase(
        case_id="CASE_01",
        description="Spark / YARN memory limit exceeded",
        context=IncidentContext(
            timestamp="2026-09-17 14:20:31",
            component="Spark",
            error="ExecutorLostFailure",
            log="Container killed by YARN for exceeding memory limit.\nContainer memory used: 8192 MB\nContainer memory limit: 8192 MB",
            metrics={"memory_used_mb": 8192, "memory_limit_mb": 8192}
        ),
        ground_truth=GroundTruth(
            incident=True,
            error_type="MEMORY_LIMIT_EXCEEDED",
            required_facts=["Container killed by YARN", "memory limit"]
        )
    ),
    BenchmarkCase(
        case_id="CASE_02",
        description="Kafka consumer lag increasing",
        context=IncidentContext(
            timestamp="2026-09-17 15:10:00",
            component="Kafka Consumer",
            error="Consumer lag increasing",
            log="Consumer group orders-consumer has increasing lag.\nCurrent lag: 250000 messages.\nConsumer processing rate: 1200 msg/s.\nProducer rate: 3500 msg/s.",
            metrics={"consumer_lag": 250000, "consumer_rate": 1200, "producer_rate": 3500}
        ),
        ground_truth=GroundTruth(
            incident=True,
            error_type="KAFKA_CONSUMER_LAG",
            required_facts=["lag: 250000", "producer rate"]
        )
    ),
    BenchmarkCase(
        case_id="CASE_03",
        description="Database connection pool exhausted",
        context=IncidentContext(
            timestamp="2026-09-17 16:05:12",
            component="Application Database",
            error="Connection pool exhausted",
            log="Failed to acquire database connection.\nConnection pool is exhausted.\nActive connections: 100\nMaximum pool size: 100\nRequests waiting for connection: 47",
            metrics={"active_connections": 100, "max_pool_size": 100, "waiting_requests": 47}
        ),
        ground_truth=GroundTruth(
            incident=True,
            error_type="DB_CONNECTION_POOL_EXHAUSTED",
            required_facts=["Connection pool is exhausted", "Active connections: 100"]
        )
    ),
    BenchmarkCase(
        case_id="CASE_04",
        description="Pipeline execution timeout",
        context=IncidentContext(
            timestamp="2026-09-17 17:30:00",
            component="ETL Pipeline",
            error="Pipeline execution timeout",
            log="Pipeline exceeded configured execution timeout.\nExpected timeout: 30 minutes.\nActual execution time: 47 minutes.",
            metrics={"execution_time_minutes": 47, "timeout_limit_minutes": 30}
        ),
        ground_truth=GroundTruth(
            incident=True,
            error_type="PIPELINE_TIMEOUT",
            required_facts=["timeout", "47 minutes"]
        )
    ),
    BenchmarkCase(
        case_id="CASE_05",
        description="Spark Worker disk full",
        context=IncidentContext(
            timestamp="2026-09-17 18:45:20",
            component="Spark Worker",
            error="No space left on device",
            log="Failed to write shuffle data.\nNo space left on device.\nDisk usage: 99%\nAvailable disk space: 2 GB",
            metrics={"disk_usage_percent": 99, "available_disk_gb": 2}
        ),
        ground_truth=GroundTruth(
            incident=True,
            error_type="DISK_FULL",
            required_facts=["shuffle data", "No space left on device"]
        )
    ),
    BenchmarkCase(
        case_id="CASE_06",
        description="Data ingestion schema validation failed",
        context=IncidentContext(
            timestamp="2026-09-17 19:12:05",
            component="Data Ingestion",
            error="Schema validation failed",
            log='Schema validation failed for column "user_id".\nExpected type: integer.\nReceived type: string.\nRejected records: 1250.',
            metrics={"rejected_records": 1250}
        ),
        ground_truth=GroundTruth(
            incident=True,
            error_type="SCHEMA_VALIDATION_FAILED",
            required_facts=["user_id", "integer", "string"]
        )
    ),
    BenchmarkCase(
        case_id="CASE_07",
        description="Normal application run without incident",
        context=IncidentContext(
            timestamp="2026-09-17 20:00:00",
            component="Spark",
            error="None",
            log="Application started successfully.\nJob submitted successfully.\nStage 1 completed.\nStage 2 completed.\nApplication finished successfully.",
            metrics={"job_duration_minutes": 12}
        ),
        ground_truth=GroundTruth(
            incident=False,
            error_type=None,
            required_facts=[]
        )
    ),
    BenchmarkCase(
        case_id="CASE_08",
        description="GitHub Actions workflow failure: Databricks host DNS resolution error (trailing newline %0a)",
        context=IncidentContext(
            timestamp="2026-08-28 06:49:20",
            component="GitHub Actions Ingestion",
            error="Workflow Run Failed: ingest-spotify-personal",
            log="Workflow run #1 (run_id: 33149238175) of repository Spotify_Premium (owner: Tuanhung-nguyen) terminated with failure conclusion. Please investigate root cause.",
            metrics={"run_id": 33149238175, "repository": "Tuanhung-nguyen/Spotify_Premium"}
        ),
        ground_truth=GroundTruth(
            incident=True,
            error_type="CONNECTION_ERROR",
            required_facts=["dbc-725afd95-6af4.cloud.databricks.com%0a", "NameResolutionError"]
        )
    )
]
