"""Pipeline and stage registry for the early API slice."""

from __future__ import annotations

from manuscriptprep.api_models import PipelineDefinition, StageDefinition


PIPELINE_DEFINITIONS = {
    "ingest": PipelineDefinition(
        pipeline="ingest",
        stages=[
            StageDefinition(
                name="ingest",
                kind="service",
                description="Classify, extract, clean, and chunk a manuscript.",
                deterministic=True,
            ),
        ],
    ),
    "orchestrate": PipelineDefinition(
        pipeline="orchestrate",
        stages=[
            StageDefinition(
                name="orchestrate",
                kind="service",
                description="Run structure, dialogue, entities, and dossiers passes.",
                deterministic=False,
            ),
        ],
    ),
    "merge": PipelineDefinition(
        pipeline="merge",
        stages=[
            StageDefinition(
                name="merge",
                kind="service",
                description="Merge per-chunk outputs into book-level artifacts.",
                deterministic=True,
            ),
        ],
    ),
    "resolve": PipelineDefinition(
        pipeline="resolve",
        stages=[
            StageDefinition(
                name="resolve",
                kind="service",
                description="Resolve likely identity variants at book level.",
                deterministic=False,
            ),
        ],
    ),
    "report": PipelineDefinition(
        pipeline="report",
        stages=[
            StageDefinition(
                name="report",
                kind="service",
                description="Render a PDF report from merged artifacts.",
                deterministic=True,
            ),
        ],
    ),
    "manuscript-prep": PipelineDefinition(
        pipeline="manuscript-prep",
        stages=[
            StageDefinition(
                name="ingest",
                kind="service",
                description="Classify, extract, clean, and chunk a manuscript.",
                deterministic=True,
            ),
            StageDefinition(
                name="orchestrate",
                kind="service",
                description="Run structure, dialogue, entities, and dossiers passes.",
                deterministic=False,
            ),
            StageDefinition(
                name="merge",
                kind="service",
                description="Merge per-chunk outputs into book-level artifacts.",
                deterministic=True,
            ),
            StageDefinition(
                name="resolve",
                kind="service",
                description="Resolve likely identity variants at book level.",
                deterministic=False,
            ),
            StageDefinition(
                name="report",
                kind="service",
                description="Render a PDF report from merged artifacts.",
                deterministic=True,
            ),
        ],
    )
}


def list_pipelines() -> list[PipelineDefinition]:
    return list(PIPELINE_DEFINITIONS.values())


def get_pipeline_definition(name: str) -> PipelineDefinition | None:
    return PIPELINE_DEFINITIONS.get(name)
