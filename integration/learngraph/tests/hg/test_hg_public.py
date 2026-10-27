import json
from pathlib import Path

import pytest
from agents.g_lesson_audit import run_g
from agents.h_file_review import run_h
from core import llm
from core.contracts import EvidenceItem, LearningRequest
from core.contracts import LessonDraft as TeamDraft
from core.contracts import LessonSection as TeamSection
from tests.hg.fixtures import FixtureGateway, g_result, h_result

from learngraph_review import ReviewService, extract_file
from learngraph_review.errors import ReviewError
from learngraph_review.models import Context


def test_public_h_live_returns_contract_and_persists_locations(tmp_path, monkeypatch):
    monkeypatch.setenv("HG_REVIEW_MODE", "live")
    monkeypatch.setenv("HG_REVIEW_OUTPUT_DIR", str(tmp_path / "records"))
    path = tmp_path / "note.txt"
    path.write_text("Python 列表可变。", encoding="utf-8")
    material = extract_file(path)
    monkeypatch.setattr(
        llm, "get_review_service", lambda: ReviewService(FixtureGateway(h_result(material)))
    )
    result = run_h(
        LearningRequest(
            session_id="test", topic="Python", goal="区分可变性", uploaded_files=[str(path)]
        )
    )
    assert result[0].mode == "live" and result[0].status == "accepted"
    assert result[0].review_status == "accept"
    assert Path(result[0].report_path).is_file()
    assert Path(result[0].approved_sources_path).is_file()
    assert json.loads(result[0].cited_locations[0])["quote"] == "Python 列表可变。"
    assert len(list((tmp_path / "records").glob("*.json"))) == 2


def test_public_h_missing_uploaded_bytes_never_calls_model(tmp_path, monkeypatch):
    monkeypatch.setenv("HG_REVIEW_MODE", "live")
    monkeypatch.setattr(llm, "get_review_service", lambda: pytest.fail("must parse first"))
    with pytest.raises((FileNotFoundError, ValueError)):
        run_h(
            LearningRequest(
                session_id="test",
                topic="Python",
                goal="目标",
                uploaded_files=[str(tmp_path / "filename-only.pdf")],
            )
        )


def test_public_g_requires_original_not_summary(monkeypatch):
    monkeypatch.setenv("HG_REVIEW_MODE", "live")
    monkeypatch.setenv("HG_SOURCES_FILE", "")
    draft = TeamDraft(
        lesson_id="L1",
        title="Python",
        objective="可变性",
        knowledge_ids=["k"],
        sections=[TeamSection(heading="概念", body="列表可变。", source_ids=["s"])],
    )
    evidence = [
        EvidenceItem(
            source_id="s",
            title="资料",
            locator="note.txt",
            claim="A 的摘要",
            knowledge_id="k",
            source_type="upload",
            mode="live",
        )
    ]
    with pytest.raises(ReviewError, match="不能将 EvidenceItem.claim 当原文"):
        run_g(draft, evidence)


def test_public_g_uses_original_and_preserves_lesson_contract(tmp_path, monkeypatch, sources):
    monkeypatch.setenv("HG_REVIEW_MODE", "live")
    monkeypatch.setenv("HG_REVIEW_OUTPUT_DIR", str(tmp_path / "records"))
    originals = tmp_path / "sources.json"
    originals.write_text(json.dumps([s.model_dump() for s in sources]), encoding="utf-8")
    monkeypatch.setenv("HG_SOURCES_FILE", str(originals))
    draft = TeamDraft(
        lesson_id="L1",
        title="Python",
        objective="可变性",
        knowledge_ids=["k"],
        sections=[TeamSection(heading="概念", body="列表可变。", source_ids=[sources[0].id])],
    )
    evidence = [
        EvidenceItem(
            source_id=sources[0].id,
            title="资料",
            locator=sources[0].source,
            claim="A 提炼的摘要不能替代原文",
            knowledge_id="k",
        )
    ]
    gateway = FixtureGateway(g_result(Context(topic="Python", objectives=["可变性"])))
    monkeypatch.setattr(llm, "get_review_service", lambda: ReviewService(gateway))
    result = run_g(draft, evidence)
    assert result.passed and result.mode == "live" and result.lesson_id == "L1"
    assert result.review_status == "pass" and Path(result.report_path).is_file()
    assert (
        gateway.calls[0]["payload"]["sources"][0]["blocks"][0]["text"] == sources[0].blocks[0].text
    )


def test_public_mode_never_silently_falls_back(monkeypatch):
    monkeypatch.setenv("HG_REVIEW_MODE", "typo")
    with pytest.raises(ReviewError, match="mock 或 live"):
        run_h(LearningRequest(session_id="test", topic="Python", goal="目标"))


def test_public_h_partial_never_admits_entire_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HG_REVIEW_MODE", "live")
    monkeypatch.setenv("HG_REVIEW_OUTPUT_DIR", str(tmp_path / "records"))
    path = tmp_path / "mixed.txt"
    path.write_text("列表可变。" * 360 + "无关广告", encoding="utf-8")
    material = extract_file(path)
    assert len(material.blocks) == 2
    monkeypatch.setattr(
        llm,
        "get_review_service",
        lambda: ReviewService(
            FixtureGateway(
                h_result(material, ["accept", "reject"]),
            )
        ),
    )
    report = run_h(
        LearningRequest(session_id="test", topic="Python", goal="目标", uploaded_files=[str(path)])
    )[0]
    assert report.status == "unreviewed" and report.mode == "live"
    assert report.review_status == "partial" and Path(report.approved_sources_path).is_file()
    assert "A 不得读取整个原文件" in report.reason
    handoff = next((tmp_path / "records").glob("*-sources.json"))
    assert len(json.loads(handoff.read_text(encoding="utf-8"))[0]["blocks"]) == 1
