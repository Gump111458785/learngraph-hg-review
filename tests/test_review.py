import copy

import pytest
from conftest import FixtureGateway, contradiction, g_result, h_result

from learngraph_review import ReviewService, approved_material, require_delivery_approval
from learngraph_review.agents import check_citations
from learngraph_review.errors import ReviewError
from learngraph_review.locations import locate
from learngraph_review.models import Anchor, Context, TextBlock
from learngraph_review.nodes import make_g_node, make_h_node


def test_h_filters_rejected_content(context, material):
    gateway = FixtureGateway(h_result(material, ["accept", "reject"]))
    report = ReviewService(gateway).review_material(context, material)
    assert report.status == "partial"
    accepted = approved_material(material, report, context)
    assert [b.id for b in accepted.blocks] == ["b0001"]
    assert "会员" not in accepted.model_dump_json()
    for decision in report.decisions:
        block = next(b for b in material.blocks if b.id == decision.block_id)
        assert block.text[decision.location.start : decision.location.end] == decision.anchor.quote


@pytest.mark.parametrize(
    "decision,status", [("reject", "reject"), ("needs_review", "needs_review")]
)
def test_h_no_accepted_material(context, material, decision, status):
    gateway = FixtureGateway(h_result(material, [decision, decision]))
    report = ReviewService(gateway).review_material(context, material)
    assert report.status == status
    assert approved_material(material, report, context) is None


@pytest.mark.parametrize(
    "damage", ["missing", "duplicate", "wrong_anchor", "invented_quote", "irrelevant"]
)
def test_h_invalid_model_output_never_admits(context, material, damage):
    result = h_result(material)
    if damage == "missing":
        result["decisions"].pop()
    elif damage == "duplicate":
        result["decisions"][1] = copy.deepcopy(result["decisions"][0])
    elif damage == "wrong_anchor":
        result["decisions"][0]["anchor"]["block_id"] = "b0002"
    elif damage == "invented_quote":
        result["decisions"][0]["anchor"]["quote"] = "资料中并不存在的原文"
    else:
        result["decisions"][0]["relevance"] = "irrelevant"
    with pytest.raises(ReviewError):
        ReviewService(FixtureGateway(result)).review_material(context, material)


def test_h_report_cannot_be_reused_after_material_or_goal_change(context, material):
    report = ReviewService(FixtureGateway(h_result(material))).review_material(context, material)
    changed = material.model_copy(deep=True)
    changed.blocks[0].text += "新增未审查内容"
    with pytest.raises(ReviewError, match="不匹配"):
        approved_material(changed, report, context)
    with pytest.raises(ReviewError, match="不匹配"):
        approved_material(material, report, Context(topic="其他主题", objectives=["其他目标"]))


def test_existing_quote_can_still_contradict_claim(context, bad_lesson, sources):
    checks, _ = check_citations(bad_lesson, sources)
    assert all(c.valid for c in checks)  # Existence alone is not proof of support.
    report = ReviewService(
        FixtureGateway(
            g_result(
                context,
                [contradiction(bad_lesson, sources[0])],
            )
        )
    ).review_lesson(context, bad_lesson, sources)
    assert report.status == "revise" and report.next_agent == "D"
    assert report.findings[0].evidence.document_id == sources[0].id
    with pytest.raises(ReviewError):
        require_delivery_approval(bad_lesson, report, context, sources)


@pytest.mark.parametrize("damage", ["source", "block", "quote", "claim"])
def test_broken_citations_override_model_pass(context, fixed_lesson, sources, damage):
    citation = fixed_lesson.sections[0].citations[0]
    if damage == "source":
        citation.source_id = "invented-source"
    elif damage == "block":
        citation.source_anchor.block_id = "invented-block"
    elif damage == "quote":
        citation.source_anchor.quote = "不存在的证据"
    else:
        citation.claim_quote = "不在本段的主张"
    report = ReviewService(FixtureGateway(g_result(context))).review_lesson(
        context,
        fixed_lesson,
        sources,
    )
    assert report.status == "revise"
    assert not report.citation_checks[0].valid
    assert any(f.origin == "rule" for f in report.findings)


def test_missing_citation_requires_manual_review(context, fixed_lesson, sources):
    fixed_lesson.sections[0].citations = []
    report = ReviewService(FixtureGateway(g_result(context))).review_lesson(
        context,
        fixed_lesson,
        sources,
    )
    assert report.status == "needs_review" and report.next_agent == "human"


@pytest.mark.parametrize("damage", ["target", "source", "half_source", "objectives"])
def test_g_fabricated_locations_or_skipped_objectives_fail(context, bad_lesson, sources, damage):
    issue = contradiction(bad_lesson, sources[0])
    result = g_result(context, [issue])
    if damage == "target":
        issue["target"]["quote"] = "模型虚构正文"
    elif damage == "source":
        issue["source_anchor"]["quote"] = "模型虚构原文"
    elif damage == "half_source":
        issue["source_id"] = None
    else:
        result["checked_objectives"] = ["忽略真实目标"]
    with pytest.raises(ReviewError):
        ReviewService(FixtureGateway(result)).review_lesson(context, bad_lesson, sources)


def test_revision_loop_and_delivery_binding(context, bad_lesson, fixed_lesson, sources):
    gateway = FixtureGateway(
        g_result(context, [contradiction(bad_lesson, sources[0])]),
        g_result(context),
    )
    service = ReviewService(gateway)
    original = bad_lesson.model_dump_json()
    first = service.review_lesson(context, bad_lesson, sources)
    second = service.review_lesson(context, fixed_lesson, sources, previous=first)
    assert first.status == "revise" and second.status == "pass"
    assert second.revision_record.no_longer_reported_ids == [first.findings[0].id]
    assert original == bad_lesson.model_dump_json()
    require_delivery_approval(fixed_lesson, second, context, sources)
    modified = fixed_lesson.model_copy(deep=True)
    modified.sections[0].text += "未经核查的附加说明"
    with pytest.raises(ReviewError):
        require_delivery_approval(modified, second, context, sources)
    altered_sources = [s.model_copy(deep=True) for s in sources]
    altered_sources[0].blocks[0].text += "新资料"
    with pytest.raises(ReviewError):
        require_delivery_approval(fixed_lesson, second, context, altered_sources)


def test_previous_revision_and_delivered_content_are_guarded(context, fixed_lesson, sources):
    service = ReviewService(FixtureGateway(g_result(context)))
    report = service.review_lesson(context, fixed_lesson, sources)
    with pytest.raises(ReviewError, match="revision"):
        service.review_lesson(context, fixed_lesson, sources, previous=report)
    fixed_lesson.delivered = True
    with pytest.raises(ReviewError, match="已交付"):
        service.review_lesson(context, fixed_lesson, sources)
    with pytest.raises(ReviewError, match="交付"):
        require_delivery_approval(fixed_lesson, report, context, sources)


def test_duplicate_source_ids_are_rejected(context, fixed_lesson, sources):
    with pytest.raises(ReviewError, match="唯一"):
        ReviewService(FixtureGateway()).review_lesson(context, fixed_lesson, sources * 2)


def test_repeated_quotes_unicode_and_page_locations():
    block = TextBlock(id="b1", text="中文第一行\n同一句。其他。同一句。", page=3, source_start=1800)
    anchor = Anchor(block_id="b1", quote="同一句。", occurrence=1)
    found = locate("doc", [block], anchor)
    assert block.text[found.start : found.end] == "同一句。"
    assert found.start == block.text.rindex("同一句。")
    assert found.page == 3 and found.line_start == 2 and found.line_end == 2
    assert found.source_start == 1800 + found.start


def test_langgraph_node_handoffs(context, material, fixed_lesson, sources):
    service = ReviewService(
        FixtureGateway(h_result(material, ["accept", "reject"]), g_result(context))
    )
    state = {
        "context": context.model_dump(),
        "uploads": [material.model_dump()],
        "lesson": fixed_lesson.model_dump(),
        "sources": [s.model_dump() for s in sources],
    }
    h_update = make_h_node(service)(state)
    assert len(h_update["approved_uploads"][0]["blocks"]) == 1
    g_update = make_g_node(service)(state)
    assert g_update["next_agent"] == "E"
    assert "h_reports" not in state and "g_report" not in state


def test_media_text_mismatch_routes_back_to_d(context, fixed_lesson, sources):
    from learngraph_review.models import MediaText

    fixed_lesson.media = [
        MediaText(
            id="slide-1",
            kind="slides_text",
            text="元组是可变序列。",
            section_ids=["explanation"],
        )
    ]
    issue = {
        "category": "media_mismatch",
        "severity": "error",
        "target": {"block_id": "slide-1", "quote": "元组是可变序列。", "occurrence": 0},
        "message": "PPT 文本与正文中的元组不可变结论冲突。",
        "suggestion": "修改当前尚未交付 PPT 文本并重新导出。",
        "source_id": sources[0].id,
        "source_anchor": {"block_id": "b0001", "quote": "元组是不可变序列", "occurrence": 0},
    }
    report = ReviewService(FixtureGateway(g_result(context, [issue]))).review_lesson(
        context,
        fixed_lesson,
        sources,
    )
    assert report.next_agent == "D"
    assert report.findings[0].target.block_id == "slide-1"
    assert "未直接核验二进制媒体" in report.media_scope


def test_g_model_cannot_cite_unprovided_source(context, bad_lesson, sources):
    issue = contradiction(bad_lesson, sources[0])
    issue["source_id"] = "not-provided"
    with pytest.raises(ReviewError, match="未提供"):
        ReviewService(FixtureGateway(g_result(context, [issue]))).review_lesson(
            context,
            bad_lesson,
            sources,
        )


def test_g_node_can_move_to_next_unit_with_previous_report_in_state(context, fixed_lesson, sources):
    service = ReviewService(FixtureGateway(g_result(context), g_result(context)))
    state = {
        "context": context.model_dump(),
        "lesson": fixed_lesson.model_dump(),
        "sources": [s.model_dump() for s in sources],
    }
    node = make_g_node(service)
    state.update(node(state))
    state["lesson"]["unit_id"] = "next-unit"
    state["lesson"]["revision"] = 1
    update = node(state)
    assert update["next_agent"] == "E"
    assert update["g_report"]["revision_record"] is None


def test_h_node_rejects_duplicate_upload_ids_before_api(context, material):
    gateway = FixtureGateway()
    with pytest.raises(ReviewError, match="唯一"):
        make_h_node(ReviewService(gateway))(
            {
                "context": context.model_dump(),
                "uploads": [material.model_dump()] * 2,
            }
        )
    assert not gateway.calls
