from uuid import NAMESPACE_URL, uuid5

import pytest

from backend.agents.text.catalog import NameRecord, SearchHit
from backend.agents.text.resolver import normalize
from backend.agents.text.search import HybridNameSearch


class SyntheticNames:
    def __init__(self):
        self.version = uuid5(NAMESPACE_URL, "synthetic")
        self.records = []
        for plant, aliases in {
            "Fixture neem": ["Neem", "Nimba", "नीम"],
            "Fixture tulsi": ["Tulsi", "Holy Basil", "तुलसी"],
            "Fixture bacopa": ["Brahmi"],
            "Fixture centella": ["Brahmi", "Gotu kola"],
        }.items():
            pid = uuid5(NAMESPACE_URL, plant)
            for alias in [plant, *aliases]:
                self.records.append(
                    NameRecord(
                        name_id=uuid5(pid, alias),
                        plant_id=pid,
                        plant_name=plant,
                        name=alias,
                        normalized_name=normalize(alias),
                        alias_type="fixture",
                        language="fixture",
                        source_key=alias,
                    )
                )

    async def generation(self):
        return self.version

    async def names(self, generation):
        return self.records

    async def lexical(self, generation, query, limit=40) -> list[SearchHit]:
        return []

    async def prefix(self, generation, query, limit=20):
        return [r for r in self.records if r.normalized_name.startswith(query)][:limit]


@pytest.fixture
def name_search():
    return HybridNameSearch(SyntheticNames())
