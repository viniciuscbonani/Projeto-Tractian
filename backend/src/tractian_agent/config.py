from __future__ import annotations

import json
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_host: str = "127.0.0.1"
    app_port: int = 8001
    app_database_path: Path = Path("runtime/tractian-agent.sqlite3")
    graph_checkpoint_path: Path = Path("runtime/langgraph-checkpoints.sqlite3")
    industrial_api_url: str = "http://127.0.0.1:8000"
    industrial_api_timeout_seconds: float = 8.0
    default_seed: str = "complete"
    demo_cases_path: Path | None = None
    benchmark_report_path: Path = Path(
        "results/latest-expanded-development-sample5-seed1.json"
    )
    model_version_map: dict[str, str] = Field(
        default_factory=lambda: {"3.2.1": "mdl_vib_v3", "specialist_v1": "mdl_vib_v3"}
    )
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_provider: str = "custom"
    groq_api_key: str | None = None
    llm_classifier_model: str | None = None
    llm_source_selector_model: str | None = None
    llm_investigator_model: str | None = None
    llm_writer_model: str | None = None
    llm_judge_model: str | None = None
    llm_timeout_seconds: float = 90.0
    llm_max_rate_limit_wait_seconds: float = 65.0
    llm_max_tool_rounds: int = 8
    llm_investigator_max_tokens: int = 1600
    max_source_queries: int = 3
    max_source_documents: int = 2
    max_analysis_details: int = 4
    max_review_revisions: int = 1
    # Compatibilidade com configurações anteriores. Os modelos por papel têm prioridade.
    llm_model: str | None = None
    runtime_judge_model: str | None = None
    max_reinvestigations: int = 1
    pipeline_version: str = "multiagent-groq-v23"
    result_reuse_ttl_seconds: int = 900
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:4173"]
    )

    @field_validator("model_version_map", mode="before")
    @classmethod
    def parse_version_map(cls, value: object) -> object:
        return json.loads(value) if isinstance(value, str) else value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        return [item.strip() for item in value.split(",")] if isinstance(value, str) else value

    @property
    def llm_enabled(self) -> bool:
        return bool(
            self.llm_base_url
            and self.effective_llm_api_key
            and all(
                (
                    self.classifier_model,
                    self.source_selector_model,
                    self.investigator_model,
                    self.writer_model,
                    self.judge_model,
                )
            )
        )

    @property
    def effective_llm_api_key(self) -> str | None:
        """Seleciona a credencial sem misturar chaves de provedores distintos."""
        if self.llm_provider.strip().lower() == "groq":
            return self.groq_api_key
        return self.llm_api_key

    @property
    def uses_groq(self) -> bool:
        return self.llm_provider.strip().lower() == "groq"

    @property
    def classifier_model(self) -> str | None:
        return self.llm_classifier_model or self.llm_model

    @property
    def investigator_model(self) -> str | None:
        return self.llm_investigator_model or self.llm_model

    @property
    def source_selector_model(self) -> str | None:
        return self.llm_source_selector_model or self.classifier_model

    @property
    def writer_model(self) -> str | None:
        return self.llm_writer_model or self.llm_model

    @property
    def judge_model(self) -> str | None:
        return self.llm_judge_model or self.runtime_judge_model or self.llm_model

    @property
    def pipeline_signature(self) -> str:
        """Versão efetiva usada para decidir se um resultado ainda pode ser reutilizado."""
        payload = "|".join(
            str(value or "")
            for value in (
                self.pipeline_version,
                self.llm_provider,
                self.llm_base_url,
                self.classifier_model,
                self.source_selector_model,
                self.investigator_model,
                self.judge_model,
                self.writer_model,
                self.max_source_queries,
                self.max_source_documents,
                self.max_analysis_details,
                self.max_review_revisions,
                self.llm_max_tool_rounds,
                self.llm_investigator_max_tokens,
                json.dumps(self.model_version_map, sort_keys=True),
            )
        )
        return sha256(payload.encode("utf-8")).hexdigest()[:16]


@lru_cache
def get_settings() -> Settings:
    return Settings()
