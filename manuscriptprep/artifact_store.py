"""Artifact storage adapters for gateway-managed job outputs."""

from __future__ import annotations

import hashlib
from pathlib import Path

from manuscriptprep.api_models import ArtifactRef


class LocalArtifactStore:
    """Register local artifact paths and enrich them with durable metadata."""

    backend_name = "local-filesystem"

    def register(self, artifacts: list[ArtifactRef]) -> list[ArtifactRef]:
        enriched: list[ArtifactRef] = []
        for artifact in artifacts:
            path = Path(artifact.path)
            metadata = dict(artifact.metadata)
            metadata["storage_backend"] = self.backend_name
            if path.exists() and path.is_file():
                metadata["exists"] = True
                metadata["bytes"] = path.stat().st_size
                metadata["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                metadata["exists"] = False
            enriched.append(
                ArtifactRef(
                    name=artifact.name,
                    path=artifact.path,
                    kind=artifact.kind,
                    stage=artifact.stage,
                    metadata=metadata,
                )
            )
        return enriched
