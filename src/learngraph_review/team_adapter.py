"""Adapters for the team's existing contracts; no public schema/signature changes."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .agents import approved_material
from .errors import ReviewError
from .models import Anchor, Citation, Context, LessonDraft, LessonSection, Material, TextBlock


def review_mode() -> str:
    load_dotenv()
    mode = os.getenv("HG_REVIEW_MODE", "mock").strip().lower()
    if mode not in {"mock", "live"}:
        raise ReviewError("HG_REVIEW_MODE 只能为 mock 或 live")
    return mode


def _save(name: str, value) -> Path:
    directory = Path(os.getenv("HG_REVIEW_OUTPUT_DIR", "outputs/hg"))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
    return path


def run_h_live(request):
    from core.contracts import FileReviewReport
    from core.llm import get_review_service
    from tools.file_extractors import extract_text_with_locators

    if not request.uploaded_files:
        return []
    context = Context(topic=request.topic, objectives=[request.goal])
    # Parse all paths first. Missing UI upload bytes never trigger paid model calls.
    try:
        materials = [extract_text_with_locators(path) for path in request.uploaded_files]
    except OSError as exc:
        raise ReviewError("H 未收到可读取的实际文件；只有 UI 文件名不能执行审查") from exc
    service = get_review_service()
    reviews = []
    for path, material in zip(request.uploaded_files, materials):
        report = service.review_material(context, material)
        saved = _save(f"{report.review_id}.json", report.model_dump(mode="json"))
        accepted = approved_material(material, report, context)
        handoff = _save(
            f"{report.review_id}-sources.json",
            [accepted.model_dump(mode="json")] if accepted else [],
        )
        # The v0.1 public contract cannot bind per-block admission. Do not label
        # a partially rejected original file as accepted/supplemental in that contract.
        status = {"accept": "accepted", "reject": "excluded"}.get(report.status, "unreviewed")
        reason = f"{report.summary}；详细记录：{saved}；仅已采纳块：{handoff}"
        if report.status == "partial":
            reason += "；公共协议不支持块级准入，A 不得读取整个原文件，请接入 sources JSON。"
        reviews.append(
            FileReviewReport(
                file_path=path,
                status=status,
                reason=reason,
                mode="live",
                cited_locations=[
                    d.location.model_dump_json() for d in report.decisions if d.decision == "accept"
                ],
            )
        )
    return reviews


def run_g_live(draft, evidence):
    from core.contracts import LessonAudit
    from core.llm import get_review_service

    if not draft.sections or not draft.objective.strip():
        raise ReviewError("G 需要非空正文与单元目标")
    evidence_map = {item.source_id: item for item in evidence}
    if len(evidence_map) != len(evidence):
        raise ReviewError("A 提供的证据 source_id 不能重复")
    cited = sorted({sid for section in draft.sections for sid in section.source_ids})
    if not cited or not set(cited) <= evidence_map.keys():
        raise ReviewError("G 缺少有效来源编号，或 D 引用了 A 未提供的来源")
    registry_path = os.getenv("HG_SOURCES_FILE", "").strip()
    if not registry_path:
        raise ReviewError(
            "G 真实审查需要 HG_SOURCES_FILE 原文数组；不能将 EvidenceItem.claim 当原文"
        )
    try:
        raw = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        originals = [Material.model_validate(item) for item in raw]
    except (OSError, ValueError, TypeError) as exc:
        raise ReviewError("G 来源原文文件无法读取或格式无效") from exc
    registry = {m.id: m for m in originals}
    if len(registry) != len(originals) or not set(cited) <= registry.keys():
        raise ReviewError("G 原文数组的来源编号重复或缺少当前引用来源")
    sources = []
    for sid in cited:
        material = registry[sid]
        if evidence_map[sid].locator.split("#", 1)[0] != material.source.split("#", 1)[0]:
            raise ReviewError("A 的 locator 与 G 原文 source 不匹配，请确认同一来源")
        # v0.1 D cites whole source IDs, not quote spans. Explicitly use the
        # complete extracted reference text; never pretend an A summary is raw text.
        text = "\n".join(block.text for block in material.blocks)
        sources.append(
            Material(
                id=sid,
                title=material.title,
                source=material.source,
                blocks=[TextBlock(id="reference", text=text)],
                extraction_notes=material.extraction_notes
                + [
                    "公共 v0.1 只有来源级引用；位置对应合并提取文本，非原文件页码。",
                ],
            )
        )
    source_map = {s.id: s for s in sources}
    sections = []
    for index, section in enumerate(draft.sections):
        citations = [
            Citation(
                source_id=sid,
                source_anchor=Anchor(block_id="reference", quote=source_map[sid].blocks[0].text),
                claim_quote=section.body,
            )
            for sid in section.source_ids
        ]
        sections.append(
            LessonSection(id=f"section-{index + 1}", text=section.body, citations=citations)
        )
    lesson = LessonDraft(unit_id=draft.lesson_id, sections=sections)
    report = get_review_service().review_lesson(
        Context(topic=draft.title, objectives=[draft.objective]),
        lesson,
        sources,
    )
    record_path = _save(f"{report.review_id}.json", report.model_dump(mode="json"))
    # Keep the contract's issues as strings so D and the group's routing keep working.
    issues = [
        f"[{f.severity}/{f.category}] {f.target.block_id} 字符 {f.target.start}:{f.target.end} "
        f"原文={f.target.quote!r}：{f.message} 建议：{f.suggestion}；完整证据记录：{record_path}"
        for f in report.findings
    ]
    return LessonAudit(
        lesson_id=draft.lesson_id,
        passed=report.status == "pass",
        issues=issues,
        checked_source_ids=cited,
        mode="live",
    )
