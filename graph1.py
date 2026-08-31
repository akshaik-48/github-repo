"""PR analysis pipeline graph.
Defines :func:`run_pr_pipeline`, which executes a **config-driven** sequence of
pipeline nodes on a shared :class:`~app.pr_pipeline.state.PRAgentState`.
Which nodes run, and in what order, is determined by (in priority order):

1. The ``node_names`` argument passed to :func:`run_pr_pipeline` (per-request
   customization).
2. ``settings.pipeline_nodes`` -- a comma-separated list of node names.
3. :data:`~app.pr_pipeline.registry.DEFAULT_PIPELINE` when neither is provided.

Node names are resolved to classes via
:data:`~app.pr_pipeline.registry.NODE_REGISTRY`.  Available nodes:
- ``ingest``          -- validate & filter the event.
- ``metadata``        -- fetch PR metadata from the API.
- ``diff``            -- fetch per-file diffs.
- ``rules``           -- load scoring rules.
- ``risk``            -- compute risk score.
- ``llm_summary``     -- generate AI summary.
- ``persist``         -- write results to SQLite.

Review comments are intentionally **not** part of this pipeline. They run as a
separate, guaranteed step via :func:`run_review_comments` so that review
feedback is still produced/posted even when the main pipeline fails.
"""
from __future__ import annotations
from collections.abc import Iterable
from app.config import settings
from app.pr_pipeline.nodes.auto_merge import AutoMergeNode
from app.pr_pipeline.nodes.review_comments import GenerateReviewCommentsNode
from app.pr_pipeline.registry import build_pipeline, parse_pipeline_config
from app.pr_pipeline.state import PRAgentState

async def run_pr_pipeline(
    state: PRAgentState,
    node_names: Iterable[str] | None = None,
) -> PRAgentState:
    """Run the configured pipeline nodes sequentially and return the enriched
    state.
    ``node_names`` overrides ``settings.pipeline_nodes`` for this call, enabling
    per-request pipeline customization.  When both are omitted, the default full
    pipeline runs.  Nodes skip gracefully when status is ignored/rejected.
    """
    names = parse_pipeline_config(settings.pipeline_nodes if node_names is None else node_names)
    nodes = build_pipeline(names)

    state.emit("pipeline", stage="pipeline", status="start", nodes=",".join(names))
    for node in nodes:
        state = await node.run(state)
    state.emit("pipeline", stage="pipeline", status="done", nodes=",".join(names))
    return state

async def run_review_comments(state: PRAgentState) -> PRAgentState:
    """Run the review-comments step independently of the main pipeline.

    Kept separate from :func:`run_pr_pipeline` so review feedback is generated
    and posted even when the pipeline itself fails partway through. Operates on
    whatever state is available; the underlying node skips gracefully when
    required data (metadata/files) is missing.
    """
    return await GenerateReviewCommentsNode().run(state)

async def run_auto_merge(state: PRAgentState) -> PRAgentState:
    """Run the auto-merge decision step independently of the main pipeline.

    Classifies the change set and, when it is whitespace/alignment-only (and
    ``settings.auto_merge_enabled`` is set), merges the PR/MR. Real code changes
    are left for human review. Skips gracefully when metadata/files are missing.
    """
    return await AutoMergeNode().run(state)
