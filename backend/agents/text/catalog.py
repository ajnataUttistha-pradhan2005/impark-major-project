from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NameRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name_id: UUID
    plant_id: UUID
    plant_name: str
    name: str
    normalized_name: str
    source_normalized_alias: str | None = None
    alias_type: str | None = None
    language: str | None = None
    source_key: str


class SearchHit(BaseModel):
    record: NameRecord
    score: float
    method: str
