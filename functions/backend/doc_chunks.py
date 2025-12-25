"""
Helpers for chunking LumiDoc payloads by section.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def _strip_section_contents(section: Dict[str, Any]) -> Dict[str, Any]:
    outline = dict(section)
    outline["contents"] = []
    sub_sections = outline.get("subSections") or []
    if sub_sections:
        outline["subSections"] = [
            _strip_section_contents(sub_section) for sub_section in sub_sections
        ]
    return outline


def build_section_outline(sections: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_strip_section_contents(section) for section in sections]


def build_doc_index(doc_json: Dict[str, Any]) -> Dict[str, Any]:
    sections = doc_json.get("sections") or []
    doc_index = dict(doc_json)
    doc_index["sections"] = []
    doc_index["sectionOutline"] = build_section_outline(sections)
    return doc_index


def iter_section_chunks(doc_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(doc_json.get("sections") or [])


def find_section_by_id(
    sections: Iterable[Dict[str, Any]], section_id: str
) -> Optional[Dict[str, Any]]:
    for section in sections:
        if section.get("id") == section_id:
            return section
        sub_sections = section.get("subSections") or []
        match = find_section_by_id(sub_sections, section_id)
        if match:
            return match
    return None
