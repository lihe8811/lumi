"""
Helpers to convert LumiDoc JSON payloads into dataclass instances.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.lumi_doc import (
    Position,
    InnerTag,
    InnerTagName,
    LumiSpan,
    TextContent,
    ListItem,
    ListContent,
    ImageContent,
    FigureContent,
    HtmlFigureContent,
    LumiContent,
    Heading,
    LumiSection,
    LumiReference,
    LumiFootnote,
    LumiAbstract,
    ConceptContent,
    Label,
    LumiConcept,
    LumiDoc,
    LumiSummaries,
    LumiSummary,
)
from shared.types import ArxivMetadata, LoadingStatus


def _get_value(data: dict, *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _to_position(data: dict) -> Position:
    return Position(
        start_index=_get_value(data, "start_index", "startIndex") or 0,
        end_index=_get_value(data, "end_index", "endIndex") or 0,
    )


def _to_inner_tag(data: dict) -> InnerTag:
    tag_name = _get_value(data, "tag_name", "tagName") or ""
    children = [_to_inner_tag(child) for child in _get_value(data, "children") or []]
    return InnerTag(
        id=_get_value(data, "id") or "",
        tag_name=InnerTagName(tag_name),
        metadata=_get_value(data, "metadata") or {},
        position=_to_position(_get_value(data, "position") or {}),
        children=children,
    )


def _to_span(data: dict) -> LumiSpan:
    return LumiSpan(
        id=_get_value(data, "id") or "",
        text=_get_value(data, "text") or "",
        inner_tags=[_to_inner_tag(tag) for tag in _get_value(data, "inner_tags", "innerTags") or []],
    )


def _to_text_content(data: dict | None) -> Optional[TextContent]:
    if not data:
        return None
    return TextContent(
        tag_name=_get_value(data, "tag_name", "tagName") or "",
        spans=[_to_span(span) for span in _get_value(data, "spans") or []],
    )


def _to_list_item(data: dict) -> ListItem:
    return ListItem(
        spans=[_to_span(span) for span in _get_value(data, "spans") or []],
        subListContent=_to_list_content(_get_value(data, "subListContent", "sub_list_content")),
    )


def _to_list_content(data: dict | None) -> Optional[ListContent]:
    if not data:
        return None
    return ListContent(
        list_items=[_to_list_item(item) for item in _get_value(data, "list_items", "listItems") or []],
        is_ordered=bool(_get_value(data, "is_ordered", "isOrdered")),
    )


def _to_image_content(data: dict | None) -> Optional[ImageContent]:
    if not data:
        return None
    return ImageContent(
        storage_path=_get_value(data, "storage_path", "storagePath") or "",
        latex_path=_get_value(data, "latex_path", "latexPath") or "",
        alt_text=_get_value(data, "alt_text", "altText") or "",
        width=float(_get_value(data, "width") or 0.0),
        height=float(_get_value(data, "height") or 0.0),
        caption=_to_span(_get_value(data, "caption") or {}) if _get_value(data, "caption") else None,
    )


def _to_figure_content(data: dict | None) -> Optional[FigureContent]:
    if not data:
        return None
    return FigureContent(
        images=[_to_image_content(img) for img in _get_value(data, "images") or [] if img],
        caption=_to_span(_get_value(data, "caption") or {}) if _get_value(data, "caption") else None,
    )


def _to_html_figure_content(data: dict | None) -> Optional[HtmlFigureContent]:
    if not data:
        return None
    return HtmlFigureContent(
        html=_get_value(data, "html") or "",
        caption=_to_span(_get_value(data, "caption") or {}) if _get_value(data, "caption") else None,
    )


def _to_lumi_content(data: dict) -> LumiContent:
    return LumiContent(
        id=_get_value(data, "id") or "",
        text_content=_to_text_content(_get_value(data, "text_content", "textContent")),
        image_content=_to_image_content(_get_value(data, "image_content", "imageContent")),
        figure_content=_to_figure_content(_get_value(data, "figure_content", "figureContent")),
        html_figure_content=_to_html_figure_content(
            _get_value(data, "html_figure_content", "htmlFigureContent")
        ),
        list_content=_to_list_content(_get_value(data, "list_content", "listContent")),
    )


def _to_heading(data: dict | None) -> Heading:
    data = data or {}
    return Heading(
        heading_level=int(_get_value(data, "heading_level", "headingLevel") or 0),
        text=_get_value(data, "text") or "",
    )


def _to_section(data: dict) -> LumiSection:
    return LumiSection(
        id=_get_value(data, "id") or "",
        heading=_to_heading(_get_value(data, "heading")),
        contents=[_to_lumi_content(content) for content in _get_value(data, "contents") or []],
        sub_sections=[_to_section(section) for section in _get_value(data, "sub_sections", "subSections") or []]
        or None,
    )


def _to_reference(data: dict) -> LumiReference:
    return LumiReference(
        id=_get_value(data, "id") or "",
        span=_to_span(_get_value(data, "span") or {}),
    )


def _to_footnote(data: dict) -> LumiFootnote:
    return LumiFootnote(
        id=_get_value(data, "id") or "",
        span=_to_span(_get_value(data, "span") or {}),
    )


def _to_abstract(data: dict | None) -> Optional[LumiAbstract]:
    if not data:
        return None
    return LumiAbstract(
        contents=[_to_lumi_content(content) for content in _get_value(data, "contents") or []]
    )


def _to_concept_content(data: dict) -> ConceptContent:
    return ConceptContent(
        label=_get_value(data, "label") or "",
        value=_get_value(data, "value") or "",
    )


def _to_label(data: dict) -> Label:
    return Label(
        id=_get_value(data, "id") or "",
        label=_get_value(data, "label") or "",
    )


def _to_concept(data: dict) -> LumiConcept:
    return LumiConcept(
        id=_get_value(data, "id") or "",
        name=_get_value(data, "name") or "",
        contents=[_to_concept_content(c) for c in _get_value(data, "contents") or []],
        in_text_citations=[_to_label(c) for c in _get_value(data, "in_text_citations", "inTextCitations") or []],
    )


def _to_summaries(data: dict | None) -> Optional[LumiSummaries]:
    if not data:
        return None
    return LumiSummaries(
        section_summaries=[_to_summary(s) for s in _get_value(data, "section_summaries", "sectionSummaries") or []],
        content_summaries=[_to_summary(s) for s in _get_value(data, "content_summaries", "contentSummaries") or []],
        span_summaries=[_to_summary(s) for s in _get_value(data, "span_summaries", "spanSummaries") or []],
        abstract_excerpt_span_id=_get_value(data, "abstract_excerpt_span_id", "abstractExcerptSpanId"),
    )


def _to_summary(data: dict) -> LumiSummary:
    return LumiSummary(
        id=_get_value(data, "id") or "",
        summary=_to_span(_get_value(data, "summary") or {}),
    )


def _to_metadata(data: dict | None) -> Optional[ArxivMetadata]:
    if not data:
        return None
    return ArxivMetadata(
        paper_id=_get_value(data, "paper_id", "paperId") or "",
        version=_get_value(data, "version") or "",
        authors=_get_value(data, "authors") or [],
        title=_get_value(data, "title") or "",
        summary=_get_value(data, "summary") or "",
        updated_timestamp=_get_value(data, "updated_timestamp", "updatedTimestamp") or "",
        published_timestamp=_get_value(data, "published_timestamp", "publishedTimestamp") or "",
    )


def doc_from_dict(data: dict) -> LumiDoc:
    return LumiDoc(
        markdown=_get_value(data, "markdown") or "",
        sections=[_to_section(section) for section in _get_value(data, "sections") or []],
        concepts=[_to_concept(concept) for concept in _get_value(data, "concepts") or []],
        section_outline=[
            _to_section(section)
            for section in _get_value(data, "section_outline", "sectionOutline") or []
        ]
        or None,
        abstract=_to_abstract(_get_value(data, "abstract")),
        references=[_to_reference(ref) for ref in _get_value(data, "references") or []] or None,
        footnotes=[_to_footnote(note) for note in _get_value(data, "footnotes") or []] or None,
        summaries=_to_summaries(_get_value(data, "summaries")),
        metadata=_to_metadata(_get_value(data, "metadata")),
        loading_status=LoadingStatus(
            _get_value(data, "loading_status", "loadingStatus") or LoadingStatus.UNSET
        ),
        loading_error=_get_value(data, "loading_error", "loadingError"),
    )
