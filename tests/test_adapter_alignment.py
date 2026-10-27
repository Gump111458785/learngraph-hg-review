"""R1 contract/path regressions, without copying private team core implementations."""

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from conftest import FixtureGateway, g_result, h_result
from pydantic import ConfigDict, create_model

from learngraph_review import ReviewService, extract_file
from learngraph_review import team_adapter as adapter
from learngraph_review.errors import ReviewError
from learngraph_review.models import Context


@pytest.fixture
def public_contracts(monkeypatch, tmp_path):
    def install(gateway, *, r1=True):
        team = tmp_path / "team"
        team.mkdir(exist_ok=True)
        core = ModuleType("core")
        contracts = ModuleType("core.contracts")
        llm = ModuleType("core.llm")
        llm.__file__ = str(team / "core/llm.py")
        llm.get_review_service = lambda: ReviewService(gateway)
        h_fields = dict(
            file_path=(str, ...),
            status=(str, ...),
            reason=(str, ...),
            mode=(str, "mock"),
            cited_locations=(list[str], []),
        )
        g_fields = dict(
            lesson_id=(str, ...),
            passed=(bool, ...),
            issues=(list[str], []),
            checked_source_ids=(list[str], []),
            mode=(str, "mock"),
        )
        if r1:
            optional = {"review_status": (str | None, None), "report_path": (str | None, None)}
            h_fields.update(optional, approved_sources_path=(str | None, None))
            g_fields.update(optional)
        contracts.FileReviewReport = create_model(
            "FileReviewReport",
            __config__=ConfigDict(extra="forbid"),
            **h_fields,
        )
        contracts.LessonAudit = create_model(
            "LessonAudit",
            __config__=ConfigDict(extra="forbid"),
            **g_fields,
        )
        core.contracts, core.llm = contracts, llm
        tools = ModuleType("tools")
        extractors = ModuleType("tools.file_extractors")
        extractors.extract_text_with_locators = extract_file
        tools.file_extractors = extractors
        for name, module in {
            "core": core,
            "core.contracts": contracts,
            "core.llm": llm,
            "tools": tools,
            "tools.file_extractors": extractors,
        }.items():
            monkeypatch.setitem(sys.modules, name, module)
        return team

    return install


@pytest.mark.parametrize("layout", ["src", "root", "wheel"])
def test_project_root_handles_both_repository_layouts_and_wheels(monkeypatch, tmp_path, layout):
    monkeypatch.delitem(sys.modules, "core.llm", raising=False)
    root = tmp_path / "project"
    root.mkdir()
    caller = tmp_path / "caller"
    caller.mkdir()
    monkeypatch.chdir(caller)
    if layout == "src":
        module = root / "src/learngraph_review/team_adapter.py"
        expected = root
    elif layout == "root":
        module = root / "learngraph_review/team_adapter.py"
        (root / "pyproject.toml").write_text("", encoding="utf-8")
        expected = root
    else:
        module = root / "site-packages/learngraph_review/team_adapter.py"
        expected = caller
    monkeypatch.setattr(adapter, "__file__", str(module))
    assert adapter.project_root() == expected
    assert adapter.project_path("outputs/hg") == expected / "outputs/hg"


def test_explicit_project_root_wins_over_loaded_team(monkeypatch, tmp_path, public_contracts):
    public_contracts(FixtureGateway())
    override = tmp_path / "explicit"
    monkeypatch.setenv("HG_PROJECT_ROOT", str(override))
    assert adapter.project_root() == override
    absolute = tmp_path / "absolute.json"
    assert adapter.project_path(str(absolute)) == absolute


def test_report_save_failure_is_catchable_by_workflow_guard(monkeypatch, tmp_path):
    target = tmp_path / "not-a-directory"
    target.write_text("existing file", encoding="utf-8")
    monkeypatch.setenv("HG_REVIEW_OUTPUT_DIR", str(target))
    with pytest.raises(ReviewError, match="保存失败") as result:
        adapter._save("review.json", {"status": "pass"})
    assert isinstance(result.value, ValueError)


@pytest.mark.parametrize("r1", [True, False], ids=["r1", "legacy-strict"])
def test_h_metadata_and_partial_handoff(monkeypatch, tmp_path, public_contracts, r1):
    path = tmp_path / "material.txt"
    path.write_text("列表可变。" * 360 + "广告", encoding="utf-8")
    material = extract_file(path)
    gateway = FixtureGateway(h_result(material, ["accept", "reject"]))
    team = public_contracts(gateway, r1=r1)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("HG_REVIEW_OUTPUT_DIR", "outputs/hg")
    result = adapter.run_h_live(
        SimpleNamespace(topic="Python", goal="目标", uploaded_files=[str(path)])
    )[0]
    assert result.status == "unreviewed"
    records = list((team / "outputs/hg").glob("h-*.json"))
    assert len(records) == 2
    if r1:
        assert result.review_status == "partial"
        assert Path(result.report_path).is_file()
        accepted = json.loads(Path(result.approved_sources_path).read_text(encoding="utf-8"))
        assert len(accepted[0]["blocks"]) == 1
    else:
        assert "review_status" not in type(result).model_fields
    assert not (elsewhere / "outputs").exists()


@pytest.mark.parametrize("verdict", ["pass", "revise", "needs_review"])
@pytest.mark.parametrize("r1", [True, False], ids=["r1", "legacy-strict"])
def test_g_metadata_relative_registry_and_public_issue_privacy(
    monkeypatch,
    tmp_path,
    public_contracts,
    sources,
    verdict,
    r1,
):
    body = "PRIVATE_UPLOAD_LITERAL 列表可变。"
    issue = {
        "category": "obvious_error",
        "severity": "error" if verdict == "revise" else "warning",
        "target": {"block_id": "section-1", "quote": body, "occurrence": 0},
        "message": "需要核对资料",
        "suggestion": "请补充依据",
        "source_id": None,
        "source_anchor": None,
    }
    output = g_result(
        Context(topic="Python", objectives=["目标"]), [] if verdict == "pass" else [issue]
    )
    gateway = FixtureGateway(output)
    team = public_contracts(gateway, r1=r1)
    (team / "registry.json").write_text(
        json.dumps([s.model_dump() for s in sources]),
        encoding="utf-8",
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("HG_SOURCES_FILE", "registry.json")
    monkeypatch.setenv("HG_REVIEW_OUTPUT_DIR", "outputs/hg")
    draft = SimpleNamespace(
        lesson_id="L1",
        title="Python",
        objective="目标",
        sections=[
            SimpleNamespace(body=body, source_ids=[sources[0].id]),
        ],
    )
    evidence = [SimpleNamespace(source_id=sources[0].id, locator=sources[0].source)]
    result = adapter.run_g_live(draft, evidence)
    assert result.passed == (verdict == "pass")
    assert "PRIVATE_UPLOAD_LITERAL" not in " ".join(result.issues)
    if r1:
        assert result.review_status == verdict
        path = Path(result.report_path)
        assert path.is_relative_to(team)
    else:
        path = next((team / "outputs/hg").glob("g-*.json"))
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["status"] == verdict
    if verdict != "pass":
        assert report["findings"][0]["target"]["quote"] == body
