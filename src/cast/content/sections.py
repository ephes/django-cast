"""Transport-neutral selection and merging of stored body sections."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


def section_value(body: Iterable[dict[str, Any]], section_type: str) -> list[dict]:
    """Return the first list-valued matching section, or an empty list."""
    for block in body:
        if block.get("type") == section_type:
            value = block.get("value")
            if isinstance(value, list):
                return value
    return []


def body_sections_with_replacements(body: Iterable[dict[str, Any]], replacements: dict[str, list[dict]]) -> str:
    """Serialize a merged body without mutating the supplied sections.

    Keep existing section order, IDs, and omitted values. Insert missing
    overview/detail sections in their canonical order. Replacements must
    use overview/detail keys and already contain converted StreamField values,
    not unvalidated author input. Every stored section must have a type key;
    unlike section_value, merging does not tolerate a missing type. Missing
    type keys or insertion of an unknown section type raise KeyError.
    """
    sections = []
    remaining = dict(replacements)
    for section in body:
        section_data = dict(section)
        section_type = section_data["type"]
        if section_type in replacements:
            section_data["value"] = replacements[section_type]
            remaining.pop(section_type, None)
        sections.append(section_data)
    section_order = {section_type: index for index, section_type in enumerate(("overview", "detail"))}
    for section_type, value in sorted(remaining.items(), key=lambda item: section_order[item[0]]):
        new_section = {"type": section_type, "value": value}
        current_order = section_order[section_type]
        insert_index = 0
        for index, section in enumerate(sections):
            existing_order = section_order.get(section["type"])
            if existing_order is not None and existing_order > current_order:
                insert_index = index
                break
            insert_index = index + 1
        sections.insert(insert_index, new_section)
    return json.dumps(sections)
