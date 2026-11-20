"""Stage 11 - assemble verified answer units without semantic text guessing."""

from __future__ import annotations

import re

from .answer_contract import (
    AnswerDraftResult,
    AnswerPurpose,
    PublicationStatus,
    PublishedAnswer,
)


_INTERNAL_ID_RE = re.compile(r"\b(?:Q|F|I|R|RC|E|C|K|KC|AF|S)\d{3,}(?:_\d{2})?\b")
_INTERNAL_TIME_MARKER_RE = re.compile(
    r"\s*\|\s*MỐC\s*:\s*[A-Za-z0-9_Đđ-]+\s*",
    flags=re.IGNORECASE,
)
_INTERNAL_FIELD_TERM_RE = re.compile(
    r"\b(?:proposition|request[_ ]?anchors?|time_basis|application_status|"
    r"fact_ids?|issue_id|requirement_id|claim_id|evidence_id|context_id)\b",
    flags=re.IGNORECASE,
)


def _public_issue_title(value: str) -> str:
    """Remove transport-only time-basis markers from a public heading."""

    cleaned = _INTERNAL_TIME_MARKER_RE.sub(" ", str(value or ""))
    return re.sub(r"\s+", " ", cleaned).strip(" |:-")


def _sanitize_public_field_terms(text: str) -> str:
    """Rewrite a narrow set of leaked contract labels into public Vietnamese."""

    cleaned = re.sub(
        r"\bproposition\b",
        "nhận định đang xét",
        str(text or ""),
        flags=re.IGNORECASE,
    )
    return cleaned


def _with_citation(text: str, citation: str) -> str:
    content = str(text or "").strip()
    locator = str(citation or "").strip()
    if not content or not locator:
        return ""
    return f"{content} ({locator})"


def _unique_lines(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            output.append(text)
    return output


def _issue_paragraphs(units, field: str) -> list[str]:
    """Join grounded units into one prose paragraph per Issue."""

    issue_order: list[str] = []
    grouped: dict[str, list[str]] = {}
    for unit in units:
        value = _with_citation(getattr(unit, field), unit.citation)
        if not value:
            continue
        if unit.issue_id not in grouped:
            grouped[unit.issue_id] = []
            issue_order.append(unit.issue_id)
        if value.casefold() not in {item.casefold() for item in grouped[unit.issue_id]}:
            grouped[unit.issue_id].append(value)
    return [
        " ".join(grouped[issue_id])
        for issue_id in issue_order
        if grouped[issue_id]
    ]


def _grouped_issue_paragraphs(
    units,
    field: str,
    issue_titles: dict[str, str],
) -> list[str]:
    """Render one titled paragraph per Issue without exposing internal IDs."""

    issue_order: list[str] = []
    grouped: dict[str, list[str]] = {}
    for unit in units:
        value = _with_citation(getattr(unit, field), unit.citation)
        if not value:
            continue
        if unit.issue_id not in grouped:
            grouped[unit.issue_id] = []
            issue_order.append(unit.issue_id)
        if value.casefold() not in {item.casefold() for item in grouped[unit.issue_id]}:
            grouped[unit.issue_id].append(value)

    output: list[str] = []
    for index, issue_id in enumerate(issue_order, 1):
        values = grouped.get(issue_id, [])
        if not values:
            continue
        title = _public_issue_title(issue_titles.get(issue_id, ""))
        if not title:
            title = f"Vấn đề pháp lý {index}"
        output.append(f"***{title}***\n\n" + " ".join(values))
    return output


def _numbered_steps(values: list[str]) -> str:
    return "\n\n".join(
        f"{index}. {value}"
        for index, value in enumerate(_unique_lines(values), 1)
    )


class PublicationStage:
    """Publish only units that already carry immutable provenance."""

    def run(
        self,
        draft: AnswerDraftResult,
        *,
        response_mode: str = "consultation",
        issue_titles: dict[str, str] | None = None,
        unresolved_issue_titles: dict[str, str] | None = None,
    ) -> PublishedAnswer:
        issue_titles = dict(issue_titles or {})
        unresolved_issue_titles = dict(unresolved_issue_titles or {})
        valid_units = tuple(
            unit
            for unit in draft.units
            if unit.citation
            and unit.analysis
            and not _INTERNAL_ID_RE.search(
                " ".join((unit.analysis, unit.conclusion, unit.next_step))
            )
            and not _INTERNAL_TIME_MARKER_RE.search(
                " ".join((unit.analysis, unit.conclusion, unit.next_step))
            )
        )
        omitted_claim_ids = tuple(
            dict.fromkeys(
                [
                    *(failure.claim_id for failure in draft.failures),
                    *(
                        unit.claim_id
                        for unit in draft.units
                        if unit not in valid_units
                    ),
                ]
            )
        )
        if not valid_units:
            unresolved = _unique_lines(
                [
                    _public_issue_title(value)
                    for value in (
                        list(unresolved_issue_titles.values())
                        or list(issue_titles.values())
                    )
                ]
            )
            issue_lines = "\n".join(
                f"- {title}" for title in unresolved
            )
            text = (
                "**Kết quả kiểm chứng**\n\n"
                "Các nguồn và nhận định hiện có chưa đủ điều kiện để công bố "
                "kết luận chắc chắn cho yêu cầu này."
                + (
                    "\n\n**Những vấn đề chưa đủ căn cứ**\n\n" + issue_lines
                    if issue_lines
                    else ""
                )
                + "\n\n**Hướng xử lý tiếp theo**\n\n"
                "Cần bổ sung nguồn trực tiếp hoặc thông tin hồ sơ liên quan đến "
                "các vấn đề nêu trên trước khi đưa ra kết luận pháp lý."
            )
            return PublishedAnswer(
                text=text,
                status=PublicationStatus.NO_PUBLISHABLE_CONTENT,
                published_unit_ids=(),
                published_evidence_ids=(),
                omitted_claim_ids=omitted_claim_ids,
            )

        analysis_units = tuple(
            unit
            for unit in valid_units
            if unit.purpose is not AnswerPurpose.LIMIT
        )
        analysis_lines = _grouped_issue_paragraphs(
            analysis_units,
            "analysis",
            issue_titles,
        )
        conclusion_lines = _issue_paragraphs(valid_units, "conclusion")
        next_steps = [
            _with_citation(unit.next_step, unit.citation)
            for unit in valid_units
            if unit.next_step
        ]
        limitations = _grouped_issue_paragraphs(
            tuple(
                unit
                for unit in valid_units
                if unit.purpose is AnswerPurpose.LIMIT
            ),
            "analysis",
            issue_titles,
        )
        if omitted_claim_ids:
            limitations.append(
                "Một phần vấn đề chưa tạo được nhận định có đủ căn cứ để công bố. "
                "Phần này cần được kiểm tra thêm bằng hồ sơ hoặc nguồn pháp luật "
                "liên quan trực tiếp."
            )
        for title in _unique_lines(
            [_public_issue_title(value) for value in unresolved_issue_titles.values()]
        ):
            limitations.append(
                f"Chưa có căn cứ đủ điều kiện công bố cho vấn đề: {title}."
            )
        legal_basis = _unique_lines(
            [
                f"- {unit.proposition} — {unit.citation}"
                for unit in valid_units
            ]
        )

        sections: list[str] = []
        if response_mode == "procedure":
            sections.append(
                "**Hướng dẫn thực hiện**\n\n"
                + (
                    _numbered_steps(next_steps)
                    if next_steps
                    else "\n\n".join(analysis_lines or limitations)
                )
            )
            if analysis_lines:
                sections.append(
                    "**Căn cứ và lưu ý áp dụng**\n\n"
                    + "\n\n".join(analysis_lines)
                )
        else:
            if conclusion_lines:
                sections.append(
                    "**Nhận định chính**\n\n"
                    + "\n\n".join(conclusion_lines)
                )
            if analysis_lines:
                sections.append(
                    "**Phân tích từng vấn đề**\n\n"
                    + "\n\n".join(analysis_lines)
                )
            if next_steps:
                sections.append(
                    "**Hướng xử lý đề xuất**\n\n"
                    + _numbered_steps(next_steps)
                )

        sections.append(
            "**Căn cứ pháp luật đã đối chiếu**\n\n" + "\n".join(legal_basis)
        )
        if limitations:
            sections.append(
                "**Thông tin cần bổ sung và giới hạn**\n\n"
                + "\n\n".join(limitations)
            )
        text = "\n\n".join(section for section in sections if section.strip())
        text = _sanitize_public_field_terms(text)
        if (
            _INTERNAL_ID_RE.search(text)
            or _INTERNAL_TIME_MARKER_RE.search(text)
            or _INTERNAL_FIELD_TERM_RE.search(text)
        ):
            return PublishedAnswer(
                text="",
                status=PublicationStatus.NO_PUBLISHABLE_CONTENT,
                published_unit_ids=(),
                published_evidence_ids=(),
                omitted_claim_ids=tuple(
                    dict.fromkeys(
                        [*omitted_claim_ids, *(unit.claim_id for unit in valid_units)]
                    )
                ),
            )
        return PublishedAnswer(
            text=text,
            status=(
                PublicationStatus.PARTIAL
                if (
                    omitted_claim_ids
                    or unresolved_issue_titles
                    or any(unit.purpose is AnswerPurpose.LIMIT for unit in valid_units)
                )
                else PublicationStatus.READY
            ),
            published_unit_ids=tuple(unit.unit_id for unit in valid_units),
            published_evidence_ids=tuple(
                dict.fromkeys(unit.evidence_id for unit in valid_units)
            ),
            omitted_claim_ids=omitted_claim_ids,
        )


__all__ = ["PublicationStage"]
