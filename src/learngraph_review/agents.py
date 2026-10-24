from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .errors import ReviewError
from .gateway import Gateway, OpenAIGateway, Settings
from .locations import locate
from .models import (
    Anchor,
    CitationCheck,
    Context,
    Finding,
    GModelResult,
    GReport,
    HDecision,
    HModelResult,
    HReport,
    LessonDraft,
    Location,
    Material,
    RevisionRecord,
    TextBlock,
    digest,
)
from .prompts import G_PROMPT, H_PROMPT


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _draft_blocks(lesson: LessonDraft) -> list[TextBlock]:
    return [TextBlock(id=s.id, text=s.text) for s in lesson.sections + lesson.media]


def _finding(
    lesson: LessonDraft,
    *,
    origin: str,
    category: str,
    severity: str,
    target: Location,
    message: str,
    suggestion: str,
    evidence: Location | None = None,
    discriminator: str = "",
) -> Finding:
    identifier = digest(
        [
            lesson.unit_id,
            origin,
            category,
            target.block_id,
            target.quote,
            target.occurrence,
            discriminator,
        ]
    )[:20]
    return Finding(
        id=f"issue-{identifier}",
        origin=origin,
        category=category,
        severity=severity,
        target=target,
        evidence=evidence,
        message=message,
        suggestion=suggestion,
    )


def check_citations(
    lesson: LessonDraft,
    sources: list[Material],
) -> tuple[list[CitationCheck], list[Finding]]:
    """Check exact text and identifiers. Semantic support is checked by G separately."""
    source_map = {s.id: s for s in sources}
    if len(source_map) != len(sources):
        raise ReviewError("资料 id 必须唯一，不能让引用指向多个来源")
    blocks = _draft_blocks(lesson)
    checks: list[CitationCheck] = []
    findings: list[Finding] = []
    for section in lesson.sections:
        fallback = locate(
            lesson.unit_id,
            blocks,
            Anchor(block_id=section.id, quote=section.text[:120]),
        )
        if not section.citations:
            findings.append(
                _finding(
                    lesson,
                    origin="rule",
                    category="missing_citation",
                    severity="warning",
                    target=fallback,
                    message="本段未提供来源引用，需确认重要知识陈述是否有依据。",
                    suggestion="由 D 为关键陈述补充 Citation；如为纯过渡段，由人工确认后再审查。",
                )
            )
        for index, citation in enumerate(section.citations):
            claim = None
            evidence = None
            error = None
            try:
                claim = locate(
                    lesson.unit_id,
                    blocks,
                    Anchor(
                        block_id=section.id,
                        quote=citation.claim_quote,
                        occurrence=citation.claim_occurrence,
                    ),
                )
                source = source_map.get(citation.source_id)
                if source is None:
                    raise ReviewError(f"不存在引用来源 {citation.source_id}")
                evidence = locate(source.id, source.blocks, citation.source_anchor)
            except ReviewError as exc:
                error = str(exc)
                findings.append(
                    _finding(
                        lesson,
                        origin="rule",
                        category="invalid_citation",
                        severity="error",
                        target=claim or fallback,
                        message=f"引用 {index + 1} 无法定位：{error}",
                        suggestion="修正来源编号、文本块编号和逐字引句，保留出处后重新提交 G。",
                        discriminator=str(index),
                    )
                )
            checks.append(
                CitationCheck(
                    section_id=section.id,
                    citation_index=index,
                    valid=error is None,
                    claim=claim,
                    evidence=evidence,
                    error=error,
                )
            )
    return checks, findings


def approved_material(material: Material, report: HReport, context: Context) -> Material | None:
    """H → A: forward only accepted blocks of exactly the reviewed input and context."""
    if (
        report.material_id != material.id
        or report.material_hash != digest(material)
        or report.context_hash != digest(context)
    ):
        raise ReviewError("H 记录与当前资料或学习目标不匹配，请重新审查")
    actual = {b.id for b in material.blocks}
    ids = [d.block_id for d in report.decisions]
    if len(ids) != len(set(ids)) or set(ids) != actual:
        raise ReviewError("H 记录未完整覆盖当前资料")
    accepted = {d.block_id for d in report.decisions if d.decision == "accept"}
    if not accepted:
        return None
    blocks = [b for b in material.blocks if b.id in accepted]
    return material.model_copy(
        update={
            "blocks": blocks,
            "extraction_notes": material.extraction_notes
            + [f"候选资料由 H 准入：{report.review_id}"],
        },
        deep=True,
    )


def require_delivery_approval(
    lesson: LessonDraft,
    report: GReport,
    context: Context,
    sources: list[Material],
) -> None:
    """Call immediately before E / delivery. Approval binds content, goals, and evidence."""
    if lesson.delivered:
        raise ReviewError("当前单元已经交付，不能重复交付或回写；请建立后续补充单元")
    if (
        report.unit_id != lesson.unit_id
        or report.revision != lesson.revision
        or report.draft_hash != digest(lesson)
        or report.context_hash != digest(context)
        or report.sources_hash != digest(sources)
    ):
        raise ReviewError("G 记录与当前内容、目标或资料不匹配，请重新审查")
    if report.status != "pass" or report.next_agent != "E" or report.findings:
        raise ReviewError("G 尚未通过，不能进入 E 或交付")


class ReviewService:
    def __init__(self, gateway: Gateway | None = None, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.gateway = gateway or OpenAIGateway(self.settings)

    def review_material(self, context: Context, material: Material) -> HReport:
        result, usage = self.gateway.run(
            model=self.settings.model_h,
            instructions=H_PROMPT,
            payload={"context": context.model_dump(), "material": material.model_dump()},
            schema=HModelResult,
        )
        ids = [d.block_id for d in result.decisions]
        expected = {b.id for b in material.blocks}
        if len(ids) != len(set(ids)) or set(ids) != expected:
            raise ReviewError("H 未对每个资料块恰好审查一次，本次不予采纳")
        mapped = {d.block_id: d for d in result.decisions}
        decisions = []
        for block in material.blocks:
            decision = mapped[block.id]
            if decision.anchor.block_id != block.id:
                raise ReviewError("H 的理由未定位到对应资料块，本次不予采纳")
            if decision.decision == "accept" and decision.relevance == "irrelevant":
                raise ReviewError("H 对无关资料给出了相互矛盾的采纳结论")
            location = locate(material.id, material.blocks, decision.anchor)
            decisions.append(HDecision(**decision.model_dump(), location=location))
        outcomes = [d.decision for d in decisions]
        if all(x == "accept" for x in outcomes):
            status = "accept"
        elif "accept" in outcomes:
            status = "partial"
        elif "needs_review" in outcomes:
            status = "needs_review"
        else:
            status = "reject"
        return HReport(
            review_id=f"h-{uuid4().hex}",
            created_at=_now(),
            material_id=material.id,
            material_hash=digest(material),
            context_hash=digest(context),
            status=status,
            summary=result.summary,
            decisions=decisions,
            usage=usage,
        )

    def review_lesson(
        self,
        context: Context,
        lesson: LessonDraft,
        sources: list[Material],
        *,
        previous: GReport | None = None,
    ) -> GReport:
        if lesson.delivered:
            raise ReviewError("已交付内容不可进入 D/G 修订循环；请通过后续单元追加更正")
        if previous is not None:
            if previous.unit_id != lesson.unit_id or previous.context_hash != digest(context):
                raise ReviewError("修订记录必须属于同一单元和学习目标")
            if lesson.revision <= previous.revision:
                raise ReviewError("修订稿 revision 必须大于上轮审查的 revision")
        checks, findings = check_citations(lesson, sources)
        result, usage = self.gateway.run(
            model=self.settings.model_g,
            instructions=G_PROMPT,
            payload={
                "context": context.model_dump(),
                "lesson": lesson.model_dump(),
                "sources": [s.model_dump() for s in sources],
                "deterministic_checks": [c.model_dump() for c in checks],
            },
            schema=GModelResult,
        )
        if len(result.checked_objectives) != len(context.objectives) or sorted(
            result.checked_objectives
        ) != sorted(context.objectives):
            raise ReviewError("G 未完整覆盖本节学习目标，本次不予放行")
        blocks = _draft_blocks(lesson)
        source_map = {s.id: s for s in sources}
        for issue in result.issues:
            target = locate(lesson.unit_id, blocks, issue.target)
            evidence = None
            if (issue.source_id is None) != (issue.source_anchor is None):
                raise ReviewError("G 的证据来源和证据定位必须同时提供或同时留空")
            if issue.source_id is not None:
                source = source_map.get(issue.source_id)
                if source is None:
                    raise ReviewError("G 引用了本次未提供的资料，不能使用虚构依据")
                evidence = locate(source.id, source.blocks, issue.source_anchor)
            findings.append(
                _finding(
                    lesson,
                    origin="model",
                    category=issue.category,
                    severity=issue.severity,
                    target=target,
                    evidence=evidence,
                    message=issue.message,
                    suggestion=issue.suggestion,
                )
            )
        # Combine repeated findings at the same text; retain the strongest severity.
        unique: dict[str, Finding] = {}
        for finding in findings:
            if finding.id not in unique or finding.severity == "error":
                unique[finding.id] = finding
        findings = list(unique.values())
        if any(f.severity == "error" for f in findings):
            status, next_agent = "revise", "D"
        elif findings:
            status, next_agent = "needs_review", "human"
        else:
            status, next_agent = "pass", "E"
        record = None
        if previous is not None:
            before = {f.id for f in previous.findings}
            after = {f.id for f in findings}
            record = RevisionRecord(
                previous_review_id=previous.review_id,
                previous_revision=previous.revision,
                current_revision=lesson.revision,
                new_finding_ids=sorted(after - before),
                still_reported_ids=sorted(after & before),
                no_longer_reported_ids=sorted(before - after),
            )
        return GReport(
            review_id=f"g-{uuid4().hex}",
            created_at=_now(),
            unit_id=lesson.unit_id,
            revision=lesson.revision,
            draft_hash=digest(lesson),
            context_hash=digest(context),
            sources_hash=digest(sources),
            status=status,
            next_agent=next_agent,
            summary=result.summary,
            findings=findings,
            citation_checks=checks,
            checked_objectives=result.checked_objectives,
            media_scope=(
                "仅检查提供的媒体文本/描述与正文的一致性；未直接核验二进制媒体。"
                if lesson.media
                else "本次未提供媒体文本，未执行媒体一致性核查。"
            ),
            usage=usage,
            revision_record=record,
        )
