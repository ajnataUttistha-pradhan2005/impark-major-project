"""Transport-safe formatting and a few model-independent response checks."""

import re

from backend.contracts.evidence import Evidence
from backend.orchestrator.deepagents.context import named_fact

_MATH = re.compile(r"\$([^$\n]{1,100})\$")
_COMMAND = re.compile(r"\\(?:text|mathrm|operatorname|mathbf|mathit)\{([^{}]+)\}")
_UNFINISHED = re.compile(
    r"\b(?:I (?:will|shall|need to|can) (?:use|query|look up|retrieve)|"
    r"let me (?:use|query|look up|retrieve))\b",
    re.IGNORECASE,
)
_EFFICACY = re.compile(r"\b(?:treats?|treating|cures?|prevents?)\b", re.IGNORECASE)
_CONFIDENCE = re.compile(r"\b(?:high|medium|low) confidence tier\b", re.IGNORECASE)
_INTERNAL_LOCK = re.compile(r"\b(?:locked|session lock)\b", re.IGNORECASE)
_UNSUPPORTED_BRIDGE = re.compile(
    r"\b(?:suggests|indicates|implies)\b[^.!?\n]{0,120}"
    r"\b(?:may possess|may be studied|has been studied|investigated|"
    r"potential to|capable of|mechanism|topical|systemic|active compound)\b"
    r"|\b(?:has been studied|investigated for|topical or systemic use)\b",
    re.IGNORECASE,
)
_FALSE_ABSENCE = re.compile(
    r"\b(?:no|not|couldn.t|didn.t|unable to|without)\b[^.!?\n]{0,100}"
    r"\b(?:records?|information|details|names?|aliases?|results?|data)\b"
    r"|\b(?:search|records?|data)\b[^.!?\n]{0,100}"
    r"\b(?:did not|does not|didn.t|doesn.t)\s+(?:return|show|include)",
    re.IGNORECASE,
)


def contradicts_retrieved_facts(text: str, evidence: list[Evidence]) -> bool:
    """A claimed absence needs revision when the same turn has positive records."""
    return bool(evidence) and bool(_FALSE_ABSENCE.search(text))


def clean_plaintext_math(text: str) -> str:
    """Render simple model-produced LaTeX as readable chat text."""
    def simplify(match: re.Match[str]) -> str:
        content = match.group(1)
        for _ in range(3):
            content = _COMMAND.sub(r"\1", content)
        return content.replace("\\_", "_").replace("\\%", "%")

    rendered = _MATH.sub(simplify, text)
    return "\n".join(
        line
        for line in rendered.splitlines()
        if not _INTERNAL_LOCK.search(line) and not line.lower().startswith("the question asks")
    ).strip()


def is_unfinished_plan(text: str) -> bool:
    return bool(_UNFINISHED.search(text)) and len(text) < 700


def needs_scientific_repair(text: str) -> bool:
    if _CONFIDENCE.search(text):
        return True
    if _UNSUPPORTED_BRIDGE.search(text):
        return True
    for sentence in re.split(r"[.!?\n]", text):
        if _EFFICACY.search(sentence) and not re.search(
            r"\b(?:not|no evidence|not proven|cannot|doesn't|do not)\b",
            sentence,
            re.IGNORECASE,
        ):
            return True
    return False


def attach_record_citations(
    text: str, focus_entities: list[str], evidence: list[Evidence]
) -> str:
    """Cite a previously recorded entity name, not its uncited general explanation."""
    by_name = {name: item for item in evidence if (name := named_fact(item))}
    for name in focus_entities:
        item = by_name.get(name)
        if item is None or name.casefold() not in text.casefold():
            continue
        marker = f"[{item.evidence_id}]"
        if marker in text:
            continue
        bold = re.compile(r"\*\*(" + re.escape(name) + r")\*\*", re.IGNORECASE)
        if bold.search(text):
            text = bold.sub(
                lambda match, citation=marker: f"**{match.group(1)}** {citation}",
                text,
                count=1,
            )
        else:
            text = re.sub(
                re.escape(name),
                lambda match, citation=marker: match.group() + f" {citation}",
                text,
                count=1,
                flags=re.IGNORECASE,
            )
    return text
