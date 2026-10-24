from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def digest(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.model_dump(mode="json"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class Context(StrictModel):
    topic: str = Field(min_length=1, max_length=500)
    objectives: list[str] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def nonblank(self) -> Context:
        if not self.topic.strip() or any(not x.strip() for x in self.objectives):
            raise ValueError("主题和每个学习目标都不能为空")
        return self


class TextBlock(StrictModel):
    id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)
    # File positions are 1-based; offsets in Location are 0-based Python characters.
    page: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=1)
    source_start: int = Field(default=0, ge=0)


class Material(StrictModel):
    id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)
    blocks: list[TextBlock] = Field(min_length=1)
    extraction_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_blocks(self) -> Material:
        ids = [b.id for b in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("资料块 id 必须唯一")
        if any(not b.text.strip() for b in self.blocks):
            raise ValueError("资料块不能只有空白")
        return self


class Anchor(StrictModel):
    block_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    occurrence: int = Field(default=0, ge=0)


class Location(StrictModel):
    document_id: str
    block_id: str
    quote: str
    occurrence: int
    start: int
    end: int
    line_start: int
    line_end: int
    page: int | None
    paragraph: int | None
    source_start: int


class Citation(StrictModel):
    source_id: str = Field(min_length=1)
    source_anchor: Anchor
    claim_quote: str = Field(min_length=1)
    claim_occurrence: int = Field(default=0, ge=0)


class LessonSection(StrictModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list)


class MediaText(StrictModel):
    id: str = Field(min_length=1)
    kind: Literal["slides_text", "image_description", "audio_transcript", "video_transcript"]
    # Supply the actual exported/recognized text, not a request to inspect a binary file.
    text: str = Field(min_length=1)
    section_ids: list[str] = Field(min_length=1)


class LessonDraft(StrictModel):
    unit_id: str = Field(min_length=1)
    revision: int = Field(default=1, ge=1)
    delivered: bool = False
    sections: list[LessonSection] = Field(min_length=1)
    media: list[MediaText] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_ids(self) -> LessonDraft:
        ids = [s.id for s in self.sections] + [m.id for m in self.media]
        if len(ids) != len(set(ids)):
            raise ValueError("正文与媒体 id 必须在单节课内唯一")
        section_ids = {s.id for s in self.sections}
        if any(not set(m.section_ids) <= section_ids for m in self.media):
            raise ValueError("媒体引用了不存在的正文段落")
        if any(not s.text.strip() for s in self.sections + self.media):
            raise ValueError("正文与媒体文本不能为空白")
        return self


class BlockDecision(StrictModel):
    block_id: str
    decision: Literal["accept", "needs_review", "reject"]
    relevance: Literal["direct", "background", "irrelevant"]
    reason: str = Field(min_length=1)
    # Quote an actual passage supporting the decision; never invent offsets.
    anchor: Anchor
    suggestion: str = Field(min_length=1)


class HModelResult(StrictModel):
    summary: str = Field(min_length=1)
    decisions: list[BlockDecision] = Field(min_length=1)


class ModelIssue(StrictModel):
    category: Literal[
        "unsupported_claim",
        "contradiction",
        "goal_mismatch",
        "obvious_error",
        "missing_evidence",
        "media_mismatch",
    ]
    severity: Literal["error", "warning"]
    target: Anchor
    message: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)
    source_id: str | None
    source_anchor: Anchor | None


class GModelResult(StrictModel):
    summary: str = Field(min_length=1)
    issues: list[ModelIssue]
    checked_objectives: list[str] = Field(min_length=1)


class Usage(StrictModel):
    model: str
    response_id: str
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    estimated_cost_usd: float | None
    elapsed_seconds: float


class HDecision(BlockDecision):
    location: Location


class HReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    review_id: str
    created_at: str
    material_id: str
    material_hash: str
    context_hash: str
    status: Literal["accept", "partial", "needs_review", "reject"]
    summary: str
    decisions: list[HDecision]
    usage: Usage


class Finding(StrictModel):
    id: str
    origin: Literal["rule", "model"]
    category: str
    severity: Literal["error", "warning"]
    target: Location
    evidence: Location | None
    message: str
    suggestion: str


class CitationCheck(StrictModel):
    section_id: str
    citation_index: int
    valid: bool
    claim: Location | None
    evidence: Location | None
    error: str | None


class RevisionRecord(StrictModel):
    previous_review_id: str
    previous_revision: int
    current_revision: int
    new_finding_ids: list[str]
    still_reported_ids: list[str]
    no_longer_reported_ids: list[str]
    # A disappeared finding is not, by itself, proof that a correction is valid.
    note: str = "本轮未再报告的问题不等于已证实修复；以本轮完整审查结论为准。"


class GReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    review_id: str
    created_at: str
    unit_id: str
    revision: int
    draft_hash: str
    context_hash: str
    sources_hash: str
    status: Literal["pass", "revise", "needs_review"]
    next_agent: Literal["E", "D", "human"]
    summary: str
    findings: list[Finding]
    citation_checks: list[CitationCheck]
    checked_objectives: list[str]
    media_scope: str
    usage: Usage
    revision_record: RevisionRecord | None
