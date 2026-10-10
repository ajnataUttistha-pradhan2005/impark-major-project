import unicodedata


def normalize(text: str) -> str:
    """Conservative normalization; no invented synonyms or model resolution."""
    value = unicodedata.normalize("NFKC", text).casefold()
    # Unicode combining marks are essential to Indic scripts; \w alone drops them.
    value = "".join(c if unicodedata.category(c)[0] in "LNM" else " " for c in value)
    return " ".join(value.split())
