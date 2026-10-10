from typing import cast

from fastapi import Request

from backend.database.neo4j.medicinal import MedicinalPlantRepository
from backend.services.errors import ServiceError


def get_plant_repository(request: Request) -> MedicinalPlantRepository:
    """Inject the bounded read repository, never the write client, into public routes."""
    repository = request.app.state.plant_repository
    if repository is None:
        raise ServiceError("DEPENDENCY_UNAVAILABLE", "Neo4j is not enabled", 503)
    return cast(MedicinalPlantRepository, repository)
