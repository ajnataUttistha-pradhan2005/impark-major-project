"""Readable deterministic answer when a local model cannot stay within the evidence.

This renderer uses the semantic role of each graph relationship. It does not
paraphrase arbitrary source text into stronger claims or manufacture citations.
"""

import json
from collections import defaultdict

from backend.contracts.response import FinalResponse, ResponseContext
from backend.llm.part_glossary import PART_MEANINGS
from backend.llm.verbalize import AnswerFact


def _claim(fact: AnswerFact) -> dict[str, object]:
    try:
        data = json.loads(fact.evidence.claim)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _field(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    clean = str(value).strip()[:100]
    return "" if clean.casefold() in {"na", "n/a", "none", "null", "-"} else clean


def _marker(index: int) -> str:
    return f"[{index}]"


def concise_answer(context: ResponseContext, facts: list[AnswerFact]) -> FinalResponse | None:
    """Explain only typed relationships that have a safe local interpretation."""
    if not facts:
        return None
    kinds = {fact.kind for fact in facts}
    plant = context.resolved_plant.label if context.resolved_plant else "this plant"
    shown: list[AnswerFact] = []
    if kinds == {"GET_THERAPEUTIC_USES"} and all(fact.term for fact in facts):
        groups: dict[tuple[str, str], list[AnswerFact]] = defaultdict(list)
        for fact in facts[: 2 if context.answer_style == "explanation" else 4]:
            category = "condition" if fact.category.casefold() in {"", "diseases"} else "topic"
            groups[(fact.part or "plant", category)].append(fact)
        clauses = []
        for (part, category), entries in groups.items():
            terms = ", ".join(
                f"{fact.term} {_marker(len(shown) + index)}"
                for index, fact in enumerate(entries, 1)
            )
            shown.extend(entries)
            subject = f"the {part}" if part != "plant" else "the plant"
            label = "related topics" if category == "topic" else "recorded topics"
            clauses.append(f"{subject} is linked with {label} such as {terms}")
        if context.answer_style == "explanation":
            text = (
                "A reported-use link connects a plant part to a named topic; it does "
                "not measure a benefit. For example, for " + plant + ", " + "; ".join(clauses) + "."
            )
        else:
            text = f"For {plant}, " + "; ".join(clauses) + ". "
            text += (
                "Here, linked means the plant part is associated with that topic; "
                "it does not tell us whether the plant treats it."
            )
        if len(facts) > len(shown) and context.answer_style != "explanation":
            text += " There are additional entries; ask about a plant part to explore them."
    elif kinds <= {"GET_BIOACTIVITY", "GET_EVIDENCE"}:
        examples = []
        metrics = set()
        for fact in facts:
            data = _claim(fact)
            metric = _field(data, "standard_type")
            value = _field(data, "standard_value")
            unit = _field(data, "standard_units")
            if not metric or not value:
                continue
            if metric.casefold() in metrics:
                continue
            metrics.add(metric.casefold())
            subject = next(
                (
                    str(node["phytochemical_name"])
                    for node in fact.evidence.graph_nodes
                    if node.get("phytochemical_name")
                ),
                "a plant compound",
            )
            target = next(
                (
                    str(node["target_name"])
                    for node in fact.evidence.graph_nodes
                    if node.get("target_name")
                ),
                "",
            )
            target_phrase = f" in a test involving {target}" if target else ""
            examples.append(
                f"{subject} has a reported {metric} of {value} {unit}{target_phrase} "
                f"{_marker(len(shown) + 1)}"
            )
            shown.append(fact)
            if len(shown) == (1 if context.answer_style == "explanation" else 2):
                break
        if not examples:
            return None
        definitions = []
        if "ic50" in metrics:
            definitions.append(
                "IC50 names the concentration that produced 50% inhibition in that test"
            )
        if "kd" in metrics:
            definitions.append("Kd is a binding-related concentration")
        if "ki" in metrics:
            definitions.append("Ki is a binding or inhibition constant")
        if "potency" in metrics:
            definitions.append("Potency is an assay label whose meaning depends on the test")
        explanation = []
        if any(
            any(node.get("target_name") for node in fact.evidence.graph_nodes) for fact in shown
        ):
            explanation.append("The target names identify proteins examined in those tests")
        if any(_field(_claim(fact), "standard_units").casefold() == "nm" for fact in shown):
            explanation.append("nM is a unit of concentration")
        if context.answer_style == "explanation":
            text = (
                "These are measurements from tests on individual plant compounds. "
                + "; ".join(definitions)
                + (". " if definitions else "")
                + "; ".join(explanation)
                + (". " if explanation else "")
                + f"For example, in {plant}, "
                + examples[0]
                + ". "
                + "A number from one test cannot be read as an effect of the whole plant."
            )
            shown = shown[:1]
        else:
            text = (
                f"Bioactivity means how a compound responds in a laboratory test. "
                f"For {plant}, "
                + "; ".join(examples)
                + ". "
                + "; ".join(definitions)
                + (". " if definitions else "")
                + "; ".join(explanation)
                + (". " if explanation else "")
                + "These numbers describe particular tests of compounds, not the whole plant."
            )
    elif kinds <= {"GET_PHYTOCHEMICALS", "GET_PHYTOCHEMICAL_DETAILS"}:
        if context.answer_style == "explanation":
            lines = []
            for fact in facts[:8]:
                data = _claim(fact)
                name = _field(data, "phytochemical_name")
                if not name:
                    continue
                shown.append(fact)
                location = f" in the {fact.part}" if fact.part else ""
                category = _field(data, "classyfire_class")
                classification = f"; classified as {category}" if category else ""
                lines.append(
                    f"- **{name}**: recorded{location}{classification} "
                    f"{_marker(len(shown))}."
                )
            if not lines:
                return None
            text = (
                f"The records name individual phytochemicals found in {plant}. "
                "Each entry connects a compound to a plant part; a chemical class, "
                "when recorded, groups related compounds.\n\n"
                + "\n".join(lines)
                + "\n\nThe records do not give concentrations for these entries, so "
                "this list cannot tell us how much of each compound the plant contains."
            )
            return FinalResponse(
                text=text,
                citation_ids=[fact.citation_id for fact in shown],
                placeholder=False,
                provider="grounded",
                fallback_used=True,
            )
        compound_groups: dict[str, list[tuple[str, AnswerFact]]] = defaultdict(list)
        for fact in facts[:5]:
            name = _field(_claim(fact), "phytochemical_name")
            if name:
                compound_groups[fact.part or "the plant"].append((name, fact))
        if not compound_groups:
            return None
        compound_clauses: list[str] = []
        for compound_part, compound_entries in compound_groups.items():
            compound_terms: list[str] = []
            for name, fact in compound_entries:
                shown.append(fact)
                compound_terms.append(f"{name} {_marker(len(shown))}")
            location = f"the {compound_part}" if compound_part != "the plant" else "the plant"
            compound_clauses.append(f"{location} is linked with {', '.join(compound_terms)}")
        text = (
            "A phytochemical is a chemical recorded in a plant. "
            + f"For {plant}, "
            + "; ".join(compound_clauses)
            + ". "
            + "These entries identify compounds and their plant parts, but do not say "
            "how much is present."
        )
        categories = {_field(_claim(fact), "classyfire_class") for fact in shown} - {""}
        if len(categories) == 1:
            category = next(iter(categories))
            if category.casefold() == "flavonoids":
                text += " Flavonoids are a broad family of plant compounds."
            else:
                text += f" The recorded chemical class is {category}."
    elif kinds == {"GET_PROTEIN_TARGETS"}:
        targets: dict[str, list[str]] = defaultdict(list)
        for fact in facts[:2]:
            data = _claim(fact)
            compound = next(
                (
                    str(node["phytochemical_name"])
                    for node in fact.evidence.graph_nodes
                    if node.get("phytochemical_name")
                ),
                "a plant compound",
            )
            target = _field(data, "target_name") or next(
                (
                    str(node["target_name"])
                    for node in fact.evidence.graph_nodes
                    if node.get("target_name")
                ),
                "",
            )
            if target:
                shown.append(fact)
                targets[compound].append(f"{target} {_marker(len(shown))}")
        if not targets:
            return None
        examples = [
            f"{compound} is linked to {', '.join(names)}" for compound, names in targets.items()
        ]
        text = (
            f"For {plant}, the listed protein targets are linked to particular plant "
            f"compounds: " + "; ".join(examples) + ". "
            "A target is what an experiment measures a compound against; the link "
            "alone does not describe an effect of the whole plant."
        )
    elif kinds == {"GET_DOCUMENTS"}:
        examples = []
        for fact in facts[:2]:
            data = _claim(fact)
            journal = _field(data, "document_journal")
            year = _field(data, "document_year")
            source = _field(data, "source")
            if journal:
                label = f"{journal} ({year})" if year else journal
            elif source:
                label = f"a {source} source entry" + (f" from {year}" if year else "")
            else:
                label = "a linked source entry"
            shown.append(fact)
            examples.append(f"{label} {_marker(len(shown))}")
        text = (
            f"The source links for {plant} include " + " and ".join(examples) + ". "
            "A source link tells us where a result was reported; it does not by "
            "itself establish the quality of that study."
        )
    elif kinds == {"GET_PLANT_DETAILS"}:
        data = _claim(facts[0])
        names = data.get("common_names")
        common_names = (
            [str(name).strip()[:80] for name in names[:4]]
            if isinstance(names, list)
            else [name.strip()[:80] for name in names.split(",")[:4] if name.strip()]
            if isinstance(names, str)
            else []
        )
        global_status = _field(data, "global_status")
        regional_status = _field(data, "regional_status")
        profile_clauses: list[str] = []
        if common_names:
            profile_clauses.append(f"is also known as {', '.join(common_names)}")
        if global_status:
            profile_clauses.append(f"has a recorded global conservation status of {global_status}")
        if regional_status:
            profile_clauses.append(
                f"has a recorded regional conservation status of {regional_status}"
            )
        if not profile_clauses:
            return None
        shown = [facts[0]]
        text = f"{plant} " + "; it ".join(profile_clauses) + " [1]."
    elif kinds <= {"GET_PLANT_PARTS", "GET_PLANT_PART_DETAILS"}:
        part_names: list[str] = []
        explained: list[str] = []
        for fact in facts[:8]:
            name = _field(_claim(fact), "plant_part") or fact.part
            if name:
                shown.append(fact)
                part_names.append(f"{name} {_marker(len(shown))}")
                meaning = PART_MEANINGS.get(name.casefold().replace("_", " "))
                if meaning:
                    explained.append(f"**{name.capitalize()}:** {meaning} {_marker(len(shown))}")
        if not part_names:
            return None
        if context.answer_style == "explanation" and explained:
            text = (
                f"For {plant}, these are names of plant parts in the available records:\n\n"
                + "\n".join(f"- {entry}" for entry in explained)
                + "\n\nThe label tells you which part a related entry concerns; "
                "it does not itself describe a use or an effect."
            )
        else:
            text = (
                f"The recorded parts of {plant} include "
                + ", ".join(part_names)
                + ". These labels identify which part a related entry concerns. "
                "You can ask about a part to explore its documented compounds or reported uses."
            )
    else:
        # The facts have already passed through the field allow-list. A short
        # narrative gives a useful example without dumping every source row.
        shown = facts[:2]
        text = f"About {plant}: " + " ".join(
            f"{fact.text.rstrip('.')} {_marker(index)}." for index, fact in enumerate(shown, 1)
        )
        if len(facts) > len(shown):
            text += (
                " There are more entries; ask about a specific name or plant part "
                "to narrow them down."
            )
    return FinalResponse(
        text=text,
        citation_ids=[fact.citation_id for fact in shown],
        placeholder=False,
        provider="grounded",
        fallback_used=True,
    )
