"""Application configuration.

All settings are loaded from environment variables or a ``.env`` file.
Defaults are provided for every field so the server starts without any
configuration when running locally.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object populated from environment variables / .env file.

    Fields are grouped by concern:
    - Server: host/port for uvicorn.
    - GitHub: webhook secret and API credentials.
    - GitLab: webhook token and API credentials.
    - Storage: SQLite path and default rules file.
    - LLM: provider selection and per-provider API keys/models.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8010

    github_webhook_secret: str = ""
    github_api_token: str = ""
    github_api_base_url: str = "https://api.github.com"

    gitlab_webhook_secret: str = ""
    gitlab_api_token: str = ""
    gitlab_api_base_url: str = "https://gitlab.com/api/v4"

    database_url: str = "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/pr_agent"
    database_path: str = "./data/pr_agent.db"
    webhook_payload_retention_days: int = 30
    analysis_log_retention_days: int = 90
    ai_cache_retention_days: int = 30
    ai_cache_ttl_seconds: int = 604800
    default_rules_file: str = "./rules/default_rules.json"
    review_guidelines_file: str = "./rules/review_guidelines.md"

    # Pipeline: comma-separated, ordered list of node names to run.
    # Leave blank to run the default full pipeline. Valid names:
    # ingest, metadata, diff, rules, risk, pr_checks, llm_summary, persist.
    # (review_comments and auto_merge run as separate guaranteed steps, not pipeline nodes.)
    pipeline_nodes: str = ""

    # Merge readiness: thresholds and blocking rules for the merge-readiness node.
    merge_ready_threshold: int = 80       # score >= this → MERGE_READY
    merge_review_threshold: int = 50      # score >= this (but < ready) → REVIEW_REQUIRED
    merge_block_on_critical: bool = True  # any critical finding → MERGE_BLOCKED regardless of score
    merge_block_on_checks_failed: bool = True  # pr_checks failure → MERGE_BLOCKED
    merge_readiness_comment_enabled: bool = True

    # API authentication: set a non-empty value to require X-API-Key on all
    # knowledge write endpoints and analysis read endpoints. Empty = no auth.
    api_key: str = ""

    # Review comments
    post_comments_enabled: bool = False
    max_inline_comments: int = 0  # 0 = no cap
    review_min_inline_severity: str = "medium"

    # Auto-merge: when a PR/MR contains only whitespace/alignment changes (no
    # semantic code change), merge it automatically. Real code changes are left
    # for human review. Disabled by default for safety.
    auto_merge_enabled: bool = False
    auto_merge_method: str = "merge"  # GitHub only: merge | squash | rebase
    auto_merge_comment_enabled: bool = True

    # Repo knowledge: auto-extract README + file structure and inject it into
    # the LLM review prompt so comments are grounded in what the repo actually
    # is. Cached in repo_context_entries and refreshed after the TTL below.
    repo_knowledge_enabled: bool = True
    repo_knowledge_ttl_seconds: int = 604800  # 7 days
    # How much of the README to include and how many dependencies to list when
    # building the cached repo-knowledge summary.
    repo_knowledge_max_readme_chars: int = 2500
    repo_knowledge_max_deps: int = 30

    # Review context: to review "what the PR changes vs what already exists",
    # fetch the full current content of the most-changed files and show fuller
    # diff hunks. Caps keep the prompt within a model's context budget; large
    # prompts are trimmed to review_prompt_char_budget so small/local models
    # (e.g. Ollama) still work.
    review_context_enabled: bool = True
    review_context_max_files: int = 25       # top changed files (by churn) to fetch in full
    review_context_max_file_chars: int = 8000  # per-file cap on fetched content
    review_prompt_char_budget: int = 120000  # overall soft cap on the review prompt
    review_multi_llm_enabled: bool = True
    review_multi_llm_max_agents: int = 3
    review_llm_batch_size: int = 5           # changed files per LLM review call
    review_llm_max_batches: int = 8          # cap total LLM review calls per PR
    review_llm_parallel_batches: int = 3
    review_llm_max_comments: int = 0       # 0 = no cap after severity filtering

    # LLM settings
    llm_provider: str = "openai"
    llm_timeout_seconds: int = 60
    llm_max_tokens: int = 2000
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_api_key: str = ""
    claude_model: str = "claude-3-5-sonnet-20241022"
    gemini_api_key: str = ""
    gemini_model: str = "gemini/gemini-1.5-pro"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "ollama/llama3"
    ollama_enabled: bool = False


settings = Settings()



"""Application configuration.

All settings are loaded from environment variables or a ``.env`` file.
Defaults are provided for every field so the server starts without any
configuration when running locally.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object populated from environment variables / .env file.

    Fields are grouped by concern:
    - Server: host/port for uvicorn.
    - GitHub: webhook secret and API credentials.
    - GitLab: webhook token and API credentials.
    - Storage: SQLite path and default rules file.
    - LLM: provider selection and per-provider API keys/models.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8010

    github_webhook_secret: str = ""
    github_api_token: str = ""
    github_api_base_url: str = "https://api.github.com"

    gitlab_webhook_secret: str = ""
    gitlab_api_token: str = ""
    gitlab_api_base_url: str = "https://gitlab.com/api/v4"

    database_url: str = "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/pr_agent"
    database_path: str = "./data/pr_agent.db"
    webhook_payload_retention_days: int = 30
    analysis_log_retention_days: int = 90
    ai_cache_retention_days: int = 30
    ai_cache_ttl_seconds: int = 604800
    default_rules_file: str = "./rules/default_rules.json"
    review_guidelines_file: str = "./rules/review_guidelines.md"

    # Pipeline: comma-separated, ordered list of node names to run.
    # Leave blank to run the default full pipeline. Valid names:
    # ingest, metadata, diff, rules, risk, pr_checks, llm_summary, persist.
    # (review_comments and auto_merge run as separate guaranteed steps, not pipeline nodes.)
    pipeline_nodes: str = ""

    # Merge readiness: thresholds and blocking rules for the merge-readiness node.
    merge_ready_threshold: int = 80       # score >= this → MERGE_READY
    merge_review_threshold: int = 50      # score >= this (but < ready) → REVIEW_REQUIRED
    merge_block_on_critical: bool = True  # any critical finding → MERGE_BLOCKED regardless of score
    merge_block_on_checks_failed: bool = True  # pr_checks failure → MERGE_BLOCKED
    merge_readiness_comment_enabled: bool = True

    # API authentication: set a non-empty value to require X-API-Key on all
    # knowledge write endpoints and analysis read endpoints. Empty = no auth.
    api_key: str = ""

    # Review comments
    post_comments_enabled: bool = False
    max_inline_comments: int = 0  # 0 = no cap
    review_min_inline_severity: str = "medium"

    # Auto-merge: when a PR/MR contains only whitespace/alignment changes (no
    # semantic code change), merge it automatically. Real code changes are left
    # for human review. Disabled by default for safety.
    auto_merge_enabled: bool = False
    auto_merge_method: str = "merge"  # GitHub only: merge | squash | rebase
    auto_merge_comment_enabled: bool = True

    # Repo knowledge: auto-extract README + file structure and inject it into
    # the LLM review prompt so comments are grounded in what the repo actually
    # is. Cached in repo_context_entries and refreshed after the TTL below.
    repo_knowledge_enabled: bool = True
    repo_knowledge_ttl_seconds: int = 604800  # 7 days
    # How much of the README to include and how many dependencies to list when
    # building the cached repo-knowledge summary.
    repo_knowledge_max_readme_chars: int = 2500
    repo_knowledge_max_deps: int = 30

    # Review context: to review "what the PR changes vs what already exists",
    # fetch the full current content of the most-changed files and show fuller
    # diff hunks. Caps keep the prompt within a model's context budget; large
    # prompts are trimmed to review_prompt_char_budget so small/local models
    # (e.g. Ollama) still work.
    review_context_enabled: bool = True
    review_context_max_files: int = 25       # top changed files (by churn) to fetch in full
    review_context_max_file_chars: int = 8000  # per-file cap on fetched content
    review_prompt_char_budget: int = 120000  # overall soft cap on the review prompt
    review_multi_llm_enabled: bool = True
    review_multi_llm_max_agents: int = 3
    review_llm_batch_size: int = 5           # changed files per LLM review call
    review_llm_max_batches: int = 8          # cap total LLM review calls per PR
    review_llm_parallel_batches: int = 3
    review_llm_max_comments: int = 0       # 0 = no cap after severity filtering

    # LLM settings
    llm_provider: str = "openai"
    llm_timeout_seconds: int = 60
    llm_max_tokens: int = 2000
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_api_key: str = ""
    claude_model: str = "claude-3-5-sonnet-20241022"
    gemini_api_key: str = ""
    gemini_model: str = "gemini/gemini-1.5-pro"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "ollama/llama3"
    ollama_enabled: bool = False


settings = Settings()

"""Application configuration.

All settings are loaded from environment variables or a ``.env`` file.
Defaults are provided for every field so the server starts without any
configuration when running locally.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object populated from environment variables / .env file.

    Fields are grouped by concern:
    - Server: host/port for uvicorn.
    - GitHub: webhook secret and API credentials.
    - GitLab: webhook token and API credentials.
    - Storage: SQLite path and default rules file.
    - LLM: provider selection and per-provider API keys/models.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8010

    github_webhook_secret: str = ""
    github_api_token: str = ""
    github_api_base_url: str = "https://api.github.com"

    gitlab_webhook_secret: str = ""
    gitlab_api_token: str = ""
    gitlab_api_base_url: str = "https://gitlab.com/api/v4"

    database_url: str = "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/pr_agent"
    database_path: str = "./data/pr_agent.db"
    webhook_payload_retention_days: int = 30
    analysis_log_retention_days: int = 90
    ai_cache_retention_days: int = 30
    ai_cache_ttl_seconds: int = 604800
    default_rules_file: str = "./rules/default_rules.json"
    review_guidelines_file: str = "./rules/review_guidelines.md"

    # Pipeline: comma-separated, ordered list of node names to run.
    # Leave blank to run the default full pipeline. Valid names:
    # ingest, metadata, diff, rules, risk, pr_checks, llm_summary, persist.
    # (review_comments and auto_merge run as separate guaranteed steps, not pipeline nodes.)
    pipeline_nodes: str = ""

    # Merge readiness: thresholds and blocking rules for the merge-readiness node.
    merge_ready_threshold: int = 80       # score >= this → MERGE_READY
    merge_review_threshold: int = 50      # score >= this (but < ready) → REVIEW_REQUIRED
    merge_block_on_critical: bool = True  # any critical finding → MERGE_BLOCKED regardless of score
    merge_block_on_checks_failed: bool = True  # pr_checks failure → MERGE_BLOCKED
    merge_readiness_comment_enabled: bool = True

    # API authentication: set a non-empty value to require X-API-Key on all
    # knowledge write endpoints and analysis read endpoints. Empty = no auth.
    api_key: str = ""

    # Review comments
    post_comments_enabled: bool = False
    max_inline_comments: int = 0  # 0 = no cap
    review_min_inline_severity: str = "medium"

    # Auto-merge: when a PR/MR contains only whitespace/alignment changes (no
    # semantic code change), merge it automatically. Real code changes are left
    # for human review. Disabled by default for safety.
    auto_merge_enabled: bool = False
    auto_merge_method: str = "merge"  # GitHub only: merge | squash | rebase
    auto_merge_comment_enabled: bool = True

    # Repo knowledge: auto-extract README + file structure and inject it into
    # the LLM review prompt so comments are grounded in what the repo actually
    # is. Cached in repo_context_entries and refreshed after the TTL below.
    repo_knowledge_enabled: bool = True
    repo_knowledge_ttl_seconds: int = 604800  # 7 days
    # How much of the README to include and how many dependencies to list when
    # building the cached repo-knowledge summary.
    repo_knowledge_max_readme_chars: int = 2500
    repo_knowledge_max_deps: int = 30

    # Review context: to review "what the PR changes vs what already exists",
    # fetch the full current content of the most-changed files and show fuller
    # diff hunks. Caps keep the prompt within a model's context budget; large
    # prompts are trimmed to review_prompt_char_budget so small/local models
    # (e.g. Ollama) still work.
    review_context_enabled: bool = True
    review_context_max_files: int = 25       # top changed files (by churn) to fetch in full
    review_context_max_file_chars: int = 8000  # per-file cap on fetched content
    review_prompt_char_budget: int = 120000  # overall soft cap on the review prompt
    review_multi_llm_enabled: bool = True
    review_multi_llm_max_agents: int = 3
    review_llm_batch_size: int = 5           # changed files per LLM review call
    review_llm_max_batches: int = 8          # cap total LLM review calls per PR
    review_llm_parallel_batches: int = 3
    review_llm_max_comments: int = 0       # 0 = no cap after severity filtering

    # LLM settings
    llm_provider: str = "openai"
    llm_timeout_seconds: int = 60
    llm_max_tokens: int = 2000
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_api_key: str = ""
    claude_model: str = "claude-3-5-sonnet-20241022"
    gemini_api_key: str = ""
    gemini_model: str = "gemini/gemini-1.5-pro"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "ollama/llama3"
    ollama_enabled: bool = False


settings = Settings()

"""Application configuration.

All settings are loaded from environment variables or a ``.env`` file.
Defaults are provided for every field so the server starts without any
configuration when running locally.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object populated from environment variables / .env file.

    Fields are grouped by concern:
    - Server: host/port for uvicorn.
    - GitHub: webhook secret and API credentials.
    - GitLab: webhook token and API credentials.
    - Storage: SQLite path and default rules file.
    - LLM: provider selection and per-provider API keys/models.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8010

    github_webhook_secret: str = ""
    github_api_token: str = ""
    github_api_base_url: str = "https://api.github.com"

    gitlab_webhook_secret: str = ""
    gitlab_api_token: str = ""
    gitlab_api_base_url: str = "https://gitlab.com/api/v4"

    database_url: str = "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/pr_agent"
    database_path: str = "./data/pr_agent.db"
    webhook_payload_retention_days: int = 30
    analysis_log_retention_days: int = 90
    ai_cache_retention_days: int = 30
    ai_cache_ttl_seconds: int = 604800
    default_rules_file: str = "./rules/default_rules.json"
    review_guidelines_file: str = "./rules/review_guidelines.md"

    # Pipeline: comma-separated, ordered list of node names to run.
    # Leave blank to run the default full pipeline. Valid names:
    # ingest, metadata, diff, rules, risk, pr_checks, llm_summary, persist.
    # (review_comments and auto_merge run as separate guaranteed steps, not pipeline nodes.)
    pipeline_nodes: str = ""

    # Merge readiness: thresholds and blocking rules for the merge-readiness node.
    merge_ready_threshold: int = 80       # score >= this → MERGE_READY
    merge_review_threshold: int = 50      # score >= this (but < ready) → REVIEW_REQUIRED
    merge_block_on_critical: bool = True  # any critical finding → MERGE_BLOCKED regardless of score
    merge_block_on_checks_failed: bool = True  # pr_checks failure → MERGE_BLOCKED
    merge_readiness_comment_enabled: bool = True

    # API authentication: set a non-empty value to require X-API-Key on all
    # knowledge write endpoints and analysis read endpoints. Empty = no auth.
    api_key: str = ""

    # Review comments
    post_comments_enabled: bool = False
    max_inline_comments: int = 0  # 0 = no cap
    review_min_inline_severity: str = "medium"

    # Auto-merge: when a PR/MR contains only whitespace/alignment changes (no
    # semantic code change), merge it automatically. Real code changes are left
    # for human review. Disabled by default for safety.
    auto_merge_enabled: bool = False
    auto_merge_method: str = "merge"  # GitHub only: merge | squash | rebase
    auto_merge_comment_enabled: bool = True

    # Repo knowledge: auto-extract README + file structure and inject it into
    # the LLM review prompt so comments are grounded in what the repo actually
    # is. Cached in repo_context_entries and refreshed after the TTL below.
    repo_knowledge_enabled: bool = True
    repo_knowledge_ttl_seconds: int = 604800  # 7 days
    # How much of the README to include and how many dependencies to list when
    # building the cached repo-knowledge summary.
    repo_knowledge_max_readme_chars: int = 2500
    repo_knowledge_max_deps: int = 30

    # Review context: to review "what the PR changes vs what already exists",
    # fetch the full current content of the most-changed files and show fuller
    # diff hunks. Caps keep the prompt within a model's context budget; large
    # prompts are trimmed to review_prompt_char_budget so small/local models
    # (e.g. Ollama) still work.
    review_context_enabled: bool = True
    review_context_max_files: int = 25       # top changed files (by churn) to fetch in full
    review_context_max_file_chars: int = 8000  # per-file cap on fetched content
    review_prompt_char_budget: int = 120000  # overall soft cap on the review prompt
    review_multi_llm_enabled: bool = True
    review_multi_llm_max_agents: int = 3
    review_llm_batch_size: int = 5           # changed files per LLM review call
    review_llm_max_batches: int = 8          # cap total LLM review calls per PR
    review_llm_parallel_batches: int = 3
    review_llm_max_comments: int = 0       # 0 = no cap after severity filtering

    # LLM settings
    llm_provider: str = "openai"
    llm_timeout_seconds: int = 60
    llm_max_tokens: int = 2000
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_api_key: str = ""
    claude_model: str = "claude-3-5-sonnet-20241022"
    gemini_api_key: str = ""
    gemini_model: str = "gemini/gemini-1.5-pro"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "ollama/llama3"
    ollama_enabled: bool = False


settings = Settings()

"""Application configuration.

All settings are loaded from environment variables or a ``.env`` file.
Defaults are provided for every field so the server starts without any
configuration when running locally.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object populated from environment variables / .env file.

    Fields are grouped by concern:
    - Server: host/port for uvicorn.
    - GitHub: webhook secret and API credentials.
    - GitLab: webhook token and API credentials.
    - Storage: SQLite path and default rules file.
    - LLM: provider selection and per-provider API keys/models.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8010

    github_webhook_secret: str = ""
    github_api_token: str = ""
    github_api_base_url: str = "https://api.github.com"

    gitlab_webhook_secret: str = ""
    gitlab_api_token: str = ""
    gitlab_api_base_url: str = "https://gitlab.com/api/v4"

    database_url: str = "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/pr_agent"
    database_path: str = "./data/pr_agent.db"
    webhook_payload_retention_days: int = 30
    analysis_log_retention_days: int = 90
    ai_cache_retention_days: int = 30
    ai_cache_ttl_seconds: int = 604800
    default_rules_file: str = "./rules/default_rules.json"
    review_guidelines_file: str = "./rules/review_guidelines.md"

    # Pipeline: comma-separated, ordered list of node names to run.
    # Leave blank to run the default full pipeline. Valid names:
    # ingest, metadata, diff, rules, risk, pr_checks, llm_summary, persist.
    # (review_comments and auto_merge run as separate guaranteed steps, not pipeline nodes.)
    pipeline_nodes: str = ""

    # Merge readiness: thresholds and blocking rules for the merge-readiness node.
    merge_ready_threshold: int = 80       # score >= this → MERGE_READY
    merge_review_threshold: int = 50      # score >= this (but < ready) → REVIEW_REQUIRED
    merge_block_on_critical: bool = True  # any critical finding → MERGE_BLOCKED regardless of score
    merge_block_on_checks_failed: bool = True  # pr_checks failure → MERGE_BLOCKED
    merge_readiness_comment_enabled: bool = True

    # API authentication: set a non-empty value to require X-API-Key on all
    # knowledge write endpoints and analysis read endpoints. Empty = no auth.
    api_key: str = ""

    # Review comments
    post_comments_enabled: bool = False
    max_inline_comments: int = 0  # 0 = no cap
    review_min_inline_severity: str = "medium"

    # Auto-merge: when a PR/MR contains only whitespace/alignment changes (no
    # semantic code change), merge it automatically. Real code changes are left
    # for human review. Disabled by default for safety.
    auto_merge_enabled: bool = False
    auto_merge_method: str = "merge"  # GitHub only: merge | squash | rebase
    auto_merge_comment_enabled: bool = True

    # Repo knowledge: auto-extract README + file structure and inject it into
    # the LLM review prompt so comments are grounded in what the repo actually
    # is. Cached in repo_context_entries and refreshed after the TTL below.
    repo_knowledge_enabled: bool = True
    repo_knowledge_ttl_seconds: int = 604800  # 7 days
    # How much of the README to include and how many dependencies to list when
    # building the cached repo-knowledge summary.
    repo_knowledge_max_readme_chars: int = 2500
    repo_knowledge_max_deps: int = 30

    # Review context: to review "what the PR changes vs what already exists",
    # fetch the full current content of the most-changed files and show fuller
    # diff hunks. Caps keep the prompt within a model's context budget; large
    # prompts are trimmed to review_prompt_char_budget so small/local models
    # (e.g. Ollama) still work.
    review_context_enabled: bool = True
    review_context_max_files: int = 25       # top changed files (by churn) to fetch in full
    review_context_max_file_chars: int = 8000  # per-file cap on fetched content
    review_prompt_char_budget: int = 120000  # overall soft cap on the review prompt
    review_multi_llm_enabled: bool = True
    review_multi_llm_max_agents: int = 3
    review_llm_batch_size: int = 5           # changed files per LLM review call
    review_llm_max_batches: int = 8          # cap total LLM review calls per PR
    review_llm_parallel_batches: int = 3
    review_llm_max_comments: int = 0       # 0 = no cap after severity filtering

    # LLM settings
    llm_provider: str = "openai"
    llm_timeout_seconds: int = 60
    llm_max_tokens: int = 2000
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_api_key: str = ""
    claude_model: str = "claude-3-5-sonnet-20241022"
    gemini_api_key: str = ""
    gemini_model: str = "gemini/gemini-1.5-pro"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "ollama/llama3"
    ollama_enabled: bool = False


settings = Settings()

"""Application configuration.

All settings are loaded from environment variables or a ``.env`` file.
Defaults are provided for every field so the server starts without any
configuration when running locally.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object populated from environment variables / .env file.

    Fields are grouped by concern:
    - Server: host/port for uvicorn.
    - GitHub: webhook secret and API credentials.
    - GitLab: webhook token and API credentials.
    - Storage: SQLite path and default rules file.
    - LLM: provider selection and per-provider API keys/models.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8010

    github_webhook_secret: str = ""
    github_api_token: str = ""
    github_api_base_url: str = "https://api.github.com"

    gitlab_webhook_secret: str = ""
    gitlab_api_token: str = ""
    gitlab_api_base_url: str = "https://gitlab.com/api/v4"

    database_url: str = "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/pr_agent"
    database_path: str = "./data/pr_agent.db"
    webhook_payload_retention_days: int = 30
    analysis_log_retention_days: int = 90
    ai_cache_retention_days: int = 30
    ai_cache_ttl_seconds: int = 604800
    default_rules_file: str = "./rules/default_rules.json"
    review_guidelines_file: str = "./rules/review_guidelines.md"

    # Pipeline: comma-separated, ordered list of node names to run.
    # Leave blank to run the default full pipeline. Valid names:
    # ingest, metadata, diff, rules, risk, pr_checks, llm_summary, persist.
    # (review_comments and auto_merge run as separate guaranteed steps, not pipeline nodes.)
    pipeline_nodes: str = ""

    # Merge readiness: thresholds and blocking rules for the merge-readiness node.
    merge_ready_threshold: int = 80       # score >= this → MERGE_READY
    merge_review_threshold: int = 50      # score >= this (but < ready) → REVIEW_REQUIRED
    merge_block_on_critical: bool = True  # any critical finding → MERGE_BLOCKED regardless of score
    merge_block_on_checks_failed: bool = True  # pr_checks failure → MERGE_BLOCKED
    merge_readiness_comment_enabled: bool = True

    # API authentication: set a non-empty value to require X-API-Key on all
    # knowledge write endpoints and analysis read endpoints. Empty = no auth.
    api_key: str = ""

    # Review comments
    post_comments_enabled: bool = False
    max_inline_comments: int = 0  # 0 = no cap
    review_min_inline_severity: str = "medium"

    # Auto-merge: when a PR/MR contains only whitespace/alignment changes (no
    # semantic code change), merge it automatically. Real code changes are left
    # for human review. Disabled by default for safety.
    auto_merge_enabled: bool = False
    auto_merge_method: str = "merge"  # GitHub only: merge | squash | rebase
    auto_merge_comment_enabled: bool = True

    # Repo knowledge: auto-extract README + file structure and inject it into
    # the LLM review prompt so comments are grounded in what the repo actually
    # is. Cached in repo_context_entries and refreshed after the TTL below.
    repo_knowledge_enabled: bool = True
    repo_knowledge_ttl_seconds: int = 604800  # 7 days
    # How much of the README to include and how many dependencies to list when
    # building the cached repo-knowledge summary.
    repo_knowledge_max_readme_chars: int = 2500
    repo_knowledge_max_deps: int = 30

    # Review context: to review "what the PR changes vs what already exists",
    # fetch the full current content of the most-changed files and show fuller
    # diff hunks. Caps keep the prompt within a model's context budget; large
    # prompts are trimmed to review_prompt_char_budget so small/local models
    # (e.g. Ollama) still work.
    review_context_enabled: bool = True
    review_context_max_files: int = 25       # top changed files (by churn) to fetch in full
    review_context_max_file_chars: int = 8000  # per-file cap on fetched content
    review_prompt_char_budget: int = 120000  # overall soft cap on the review prompt
    review_multi_llm_enabled: bool = True
    review_multi_llm_max_agents: int = 3
    review_llm_batch_size: int = 5           # changed files per LLM review call
    review_llm_max_batches: int = 8          # cap total LLM review calls per PR
    review_llm_parallel_batches: int = 3
    review_llm_max_comments: int = 0       # 0 = no cap after severity filtering

    # LLM settings
    llm_provider: str = "openai"
    llm_timeout_seconds: int = 60
    llm_max_tokens: int = 2000
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_api_key: str = ""
    claude_model: str = "claude-3-5-sonnet-20241022"
    gemini_api_key: str = ""
    gemini_model: str = "gemini/gemini-1.5-pro"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "ollama/llama3"
    ollama_enabled: bool = False


settings = Settings()

"""Application configuration.

All settings are loaded from environment variables or a ``.env`` file.
Defaults are provided for every field so the server starts without any
configuration when running locally.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object populated from environment variables / .env file.

    Fields are grouped by concern:
    - Server: host/port for uvicorn.
    - GitHub: webhook secret and API credentials.
    - GitLab: webhook token and API credentials.
    - Storage: SQLite path and default rules file.
    - LLM: provider selection and per-provider API keys/models.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8010

    github_webhook_secret: str = ""
    github_api_token: str = ""
    github_api_base_url: str = "https://api.github.com"

    gitlab_webhook_secret: str = ""
    gitlab_api_token: str = ""
    gitlab_api_base_url: str = "https://gitlab.com/api/v4"

    database_url: str = "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/pr_agent"
    database_path: str = "./data/pr_agent.db"
    webhook_payload_retention_days: int = 30
    analysis_log_retention_days: int = 90
    ai_cache_retention_days: int = 30
    ai_cache_ttl_seconds: int = 604800
    default_rules_file: str = "./rules/default_rules.json"
    review_guidelines_file: str = "./rules/review_guidelines.md"

    # Pipeline: comma-separated, ordered list of node names to run.
    # Leave blank to run the default full pipeline. Valid names:
    # ingest, metadata, diff, rules, risk, pr_checks, llm_summary, persist.
    # (review_comments and auto_merge run as separate guaranteed steps, not pipeline nodes.)
    pipeline_nodes: str = ""

    # Merge readiness: thresholds and blocking rules for the merge-readiness node.
    merge_ready_threshold: int = 80       # score >= this → MERGE_READY
    merge_review_threshold: int = 50      # score >= this (but < ready) → REVIEW_REQUIRED
    merge_block_on_critical: bool = True  # any critical finding → MERGE_BLOCKED regardless of score
    merge_block_on_checks_failed: bool = True  # pr_checks failure → MERGE_BLOCKED
    merge_readiness_comment_enabled: bool = True

    # API authentication: set a non-empty value to require X-API-Key on all
    # knowledge write endpoints and analysis read endpoints. Empty = no auth.
    api_key: str = ""

    # Review comments
    post_comments_enabled: bool = False
    max_inline_comments: int = 0  # 0 = no cap
    review_min_inline_severity: str = "medium"

    # Auto-merge: when a PR/MR contains only whitespace/alignment changes (no
    # semantic code change), merge it automatically. Real code changes are left
    # for human review. Disabled by default for safety.
    auto_merge_enabled: bool = False
    auto_merge_method: str = "merge"  # GitHub only: merge | squash | rebase
    auto_merge_comment_enabled: bool = True

    # Repo knowledge: auto-extract README + file structure and inject it into
    # the LLM review prompt so comments are grounded in what the repo actually
    # is. Cached in repo_context_entries and refreshed after the TTL below.
    repo_knowledge_enabled: bool = True
    repo_knowledge_ttl_seconds: int = 604800  # 7 days
    # How much of the README to include and how many dependencies to list when
    # building the cached repo-knowledge summary.
    repo_knowledge_max_readme_chars: int = 2500
    repo_knowledge_max_deps: int = 30

    # Review context: to review "what the PR changes vs what already exists",
    # fetch the full current content of the most-changed files and show fuller
    # diff hunks. Caps keep the prompt within a model's context budget; large
    # prompts are trimmed to review_prompt_char_budget so small/local models
    # (e.g. Ollama) still work.
    review_context_enabled: bool = True
    review_context_max_files: int = 25       # top changed files (by churn) to fetch in full
    review_context_max_file_chars: int = 8000  # per-file cap on fetched content
    review_prompt_char_budget: int = 120000  # overall soft cap on the review prompt
    review_multi_llm_enabled: bool = True
    review_multi_llm_max_agents: int = 3
    review_llm_batch_size: int = 5           # changed files per LLM review call
    review_llm_max_batches: int = 8          # cap total LLM review calls per PR
    review_llm_parallel_batches: int = 3
    review_llm_max_comments: int = 0       # 0 = no cap after severity filtering

    # LLM settings
    llm_provider: str = "openai"
    llm_timeout_seconds: int = 60
    llm_max_tokens: int = 2000
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_api_key: str = ""
    claude_model: str = "claude-3-5-sonnet-20241022"
    gemini_api_key: str = ""
    gemini_model: str = "gemini/gemini-1.5-pro"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "ollama/llama3"
    ollama_enabled: bool = False


settings = Settings()

