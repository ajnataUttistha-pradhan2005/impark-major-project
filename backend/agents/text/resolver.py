import unicodedata


def normalize(text: str) -> str:
    """Conservative normalization; no invented synonyms or model resolution."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())
