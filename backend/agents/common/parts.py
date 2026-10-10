"""Application part tokens mapped to the verified Neo4j PlantPart vocabulary."""

PART_NAMES: dict[str, tuple[str, ...]] = {
    "leaf": ("leaf", "leaves"),
    "root": ("root", "roots"),
    "bark": ("bark",),
    "flower": ("flower", "flowers"),
    "seed": ("seed", "seeds"),
    "fruit": ("fruit", "fruits"),
    "stem": ("stem", "stems"),
    "rhizome": ("rhizome", "rhizomes"),
    "shoot": ("shoot", "shoots"),
    "tuber": ("tuber", "tubers"),
    "wood": ("wood",),
    "gall": ("gall", "galls"),
    "culture": ("culture", "cultures"),
    "aerial_part": ("aerial part", "aerial parts"),
    "plant_exudate": ("plant exudate", "plant exudates", "exudate", "exudates"),
    "whole_plant": ("whole plant",),
    "unknown_part": ("unknown part",),
}
