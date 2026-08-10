"""Pipeline node registry.
Maps short, stable node *names* to their node classes and defines the default
execution order.  This is what makes the pipeline config-driven: the pipeline
that actually runs is assembled from a list of these names (see
:func:`app.pr_pipeline.graph.run_pr_pipeline`), which can come from
``settings.pipeline_nodes`` or be passed in per request.

Every node class shares the same minimal interface::

    class SomeNode:
        async def run(self, state: PRAgentState) -> PRAgentState: ...

To register a new node, add an entry to :data:`NODE_REGISTRY` and (optionally)
include its name in :data:`DEFAULT_PIPELINE`.
"""
from __future__ import annotations

from collections.abc import Iterable

from app.pr_pipeline.nodes.diff import ExtractDiffsNode
from app.pr_pipeline.nodes.ingest import IngestWebhookNode
from app.pr_pipeline.nodes.llm_summary import GenerateLLMSummaryNode
from app.pr_pipeline.nodes.merge_readiness import MergeReadinessNode
from app.pr_pipeline.nodes.metadata import CollectMetadataNode
from app.pr_pipeline.nodes.persist import PersistResultNode
from app.pr_pipeline.nodes.pr_checks import PRChecksNode
from app.pr_pipeline.nodes.risk import CalculateRiskNode
from app.pr_pipeline.nodes.rules import LoadRulesNode

# Stable name -> node class. Names are what users put in configuration.
# NOTE: review comments are intentionally NOT a pipeline node. They run as a
# separate, guaranteed step (see ``run_review_comments``) so review feedback is
# still produced even when the main pipeline fails.
NODE_REGISTRY: dict[str, type] = {
    "ingest": IngestWebhookNode,
    "metadata": CollectMetadataNode,
    "diff": ExtractDiffsNode,
    "rules": LoadRulesNode,
    "risk": CalculateRiskNode,
    "pr_checks": PRChecksNode,
    "llm_summary": GenerateLLMSummaryNode,
    "merge_readiness": MergeReadinessNode,
    "persist": PersistResultNode,
}

# Default pipeline when no explicit configuration is provided.
DEFAULT_PIPELINE: list[str] = [
    "ingest",
    "metadata",
    "diff",
    "rules",
    "risk",
    "pr_checks",
    "llm_summary",
    "merge_readiness",
    "persist",
]


def parse_pipeline_config(raw: str | Iterable[str] | None) -> list[str]:
    """Normalise a pipeline configuration into an ordered list of node names.

    Accepts a comma-separated string (as read from an env var), an iterable of
    names, or ``None`` / empty (which selects :data:`DEFAULT_PIPELINE`).
    """
    if not raw:
        return list(DEFAULT_PIPELINE)
    if isinstance(raw, str):
        names = [part.strip() for part in raw.split(",")]
    else:
        names = [str(part).strip() for part in raw]
    names = [name for name in names if name]
    return names or list(DEFAULT_PIPELINE)


def build_pipeline(node_names: Iterable[str]) -> list[object]:
    """Instantiate the ordered node objects for ``node_names``.

    Raises :class:`ValueError` if any name is not present in
    :data:`NODE_REGISTRY`, so misconfiguration fails fast and clearly.
    """
    names = list(node_names)
    unknown = [name for name in names if name not in NODE_REGISTRY]
    if unknown:
        available = ", ".join(sorted(NODE_REGISTRY))
        raise ValueError(
            f"Unknown pipeline node(s): {', '.join(unknown)}. "
            f"Available nodes: {available}."
        )
    return [NODE_REGISTRY[name]() for name in names]
