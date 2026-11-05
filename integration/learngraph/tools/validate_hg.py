"""Explicit offline/live H/G acceptance. Live uses the local Key and paid API.

Does not enable other agents or external search. Never fabricates human signoff.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from core.contracts import (
    CoursePlan,
    CourseUnit,
    EvidenceItem,
    KnowledgeGraph,
    KnowledgeNode,
    LearningRequest,
    LessonDraft,
    LessonSection,
    QuizBundle,
    QuizQuestion,
)
from docx import Document
from dotenv import load_dotenv

from learngraph_review import ReviewService
from learngraph_review.models import Usage

ROOT = Path(__file__).resolve().parents[1]


class OfflineGateway:
    """Scripted expectations; not evidence of real model accuracy."""

    def __init__(self):
        self.calls = []
        self.case = ""

    def run(self, *, schema, payload, **kwargs):
        self.calls.append({"case": self.case, "schema": schema.__name__})
        if schema.__name__ == "HModelResult":
            blocks = payload["material"]["blocks"]
            raw = dict(
                summary="离线预置：准入知识段，排除广告",
                decisions=[
                    dict(
                        block_id=b["id"],
                        decision="accept" if i == 0 else "reject",
                        relevance="direct" if i == 0 else "irrelevant",
                        reason="知识段支持目标" if i == 0 else "广告与目标无关",
                        suggestion="保留" if i == 0 else "排除",
                        anchor=dict(block_id=b["id"], quote=b["text"], occurrence=0),
                    )
                    for i, b in enumerate(blocks)
                ],
            )
        elif schema.__name__ == "QuizModelResult":
            bad = self.case.removeprefix("quiz_bad_") if self.case != "quiz_good" else None
            raw = dict(
                summary="离线预置的分项审核",
                checked_objectives=payload["context"]["objectives"],
                checks=[
                    dict(
                        component=c,
                        status="revise" if c == bad else "pass",
                        reason="与可变性原文矛盾" if c == bad else "与教案依据一致",
                        suggestion="按原文修正" if c == bad else "保留",
                        target=dict(block_id=c, quote=payload["quiz"][c], occurrence=0),
                        lesson_anchor=dict(
                            block_id=payload["lesson_blocks"][0]["id"],
                            quote=payload["lesson_blocks"][0]["text"],
                            occurrence=0,
                        ),
                        source_id=None,
                        source_anchor=None,
                    )
                    for c in ("prompt", "reference_answer", "rubric")
                ],
            )
        elif schema.__name__ == "Diagnosis":
            raw = dict(
                issues=[
                    dict(
                        category="content",
                        reason="正文颠倒列表与元组的可变性",
                        evidence="原文列表可变、元组不可变",
                        knowledge_ids=["K1"],
                        queries=[],
                    )
                ]
            )
        else:
            issues = []
            if self.case != "lesson_good":
                text = payload["lesson"]["sections"][0]
                source = payload["sources"][0]
                uncertain = self.case == "uncertain"
                issues = [
                    dict(
                        category="missing_evidence" if uncertain else "contradiction",
                        severity="warning" if uncertain else "error",
                        target=dict(block_id=text["id"], quote=text["text"], occurrence=0),
                        message="原文不支持十倍性能保证" if uncertain else "可变性颠倒",
                        suggestion="补性能实验" if uncertain else "按原文修正",
                        source_id=None if uncertain else source["id"],
                        source_anchor=None
                        if uncertain
                        else dict(
                            block_id=source["blocks"][0]["id"],
                            quote=source["blocks"][0]["text"],
                            occurrence=0,
                        ),
                    )
                ]
            raw = dict(
                summary="离线预置的教案核查",
                issues=issues,
                checked_objectives=payload["context"]["objectives"],
            )
        return schema.model_validate(raw), Usage(
            model="scripted-offline-fixture",
            response_id="fixture",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            estimated_cost_usd=None,
            elapsed_seconds=0,
        )


def run(out: Path, mode: str):
    from unittest.mock import patch

    from agents.learning_services import audit_content, audit_practice
    from core import llm
    from tools.web_retrieval import approved_uploads

    from learngraph_review.team_adapter import run_h_live

    data = json.loads((ROOT / "examples/hg_v3/cases.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=False)
    (out / "inputs.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.environ["HG_REVIEW_MODE"] = "live"  # Offline mode explicitly injects a synthetic gateway.
    os.environ["HG_REVIEW_OUTPUT_DIR"] = str(out / "reports")
    gateway = OfflineGateway() if mode == "offline" else None
    service = ReviewService(gateway=gateway) if gateway else ReviewService()
    manifest = {
        "mode": mode,
        "cases": {},
        "human_review": "pending",
        "signoffs": {},
        "model_h": service.settings.model_h,
        "model_g": service.settings.model_g,
    }

    def save(name, value):
        (out / f"{name}.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def case(name):
        if gateway:
            gateway.case = name

    try:
        with patch.object(llm, "get_review_service", lambda: service):
            upload = out / "mixed-material.docx"
            doc = Document()
            for paragraph in data["paragraphs"]:
                doc.add_paragraph(paragraph)
            doc.save(upload)
            request = LearningRequest(
                session_id="hg-v3-acceptance",
                topic=data["topic"],
                goal=data["objective"],
                uploaded_files=[str(upload)],
            )
            case("h_partial")
            h = run_h_live(request)
            save("h-public", [r.model_dump(mode="json") for r in h])
            materials, warnings = approved_uploads(request, h)
            save("h-to-a", [m.model_dump(mode="json") for m in materials])
            manifest["cases"]["h_partial"] = {
                "actual": h[0].review_status,
                "expected": "partial",
                "accepted_block_ids": [b.id for m in materials for b in m.blocks],
                "warnings": warnings,
            }
            if not materials:
                raise ValueError("H 没有准入块，停止下游验收")
            source = materials[0]
            evidence = [
                EvidenceItem(
                    source_id=source.id,
                    title=source.title,
                    locator=source.source,
                    claim=source.blocks[0].text,
                    knowledge_id="K1",
                    mode="live",
                )
            ]
            sources = [m.model_dump(mode="json") for m in materials]
            save("evidence", [e.model_dump(mode="json") for e in evidence])
            graph = KnowledgeGraph(
                nodes=[KnowledgeNode(knowledge_id="K1", name="可变性", source_ids=[source.id])]
            )
            plan = CoursePlan(
                units=[
                    CourseUnit(
                        lesson_id="L1",
                        title=data["topic"],
                        objective=data["objective"],
                        knowledge_ids=["K1"],
                    )
                ]
            )
            drafts = {}
            for name, key in [
                ("lesson_bad", "bad_lesson"),
                ("lesson_good", "good_lesson"),
                ("uncertain", "unsupported_lesson"),
            ]:
                case(name)
                draft = LessonDraft(
                    lesson_id="L1",
                    title=data["topic"],
                    objective=data["objective"],
                    knowledge_ids=["K1"],
                    sections=[
                        LessonSection(heading="可变性", body=data[key], source_ids=[source.id])
                    ],
                    mode="live",
                )
                drafts[name] = draft
                decision = audit_content(draft, evidence, sources, graph, plan)
                save(
                    name,
                    {
                        "draft": draft.model_dump(mode="json"),
                        "decision": decision.model_dump(mode="json"),
                    },
                )
                manifest["cases"][name] = {
                    "passed": decision.passed,
                    "categories": [i.category for i in decision.issues],
                    "report_path": decision.report_path,
                }
            draft = drafts["lesson_good"]
            for component in [None, "prompt", "reference_answer", "rubric"]:
                name = "quiz_bad_" + component if component else "quiz_good"
                case(name)
                fields = dict(data["quiz"])
                if component:
                    fields[component] = data["bad_components"][component]
                quiz = QuizBundle(
                    lesson_id="L1",
                    questions=[
                        QuizQuestion(
                            lesson_id="L1", question_id="Q1", knowledge_ids=["K1"], **fields
                        )
                    ],
                    mode="live",
                )
                decision = audit_practice(draft, quiz, evidence, sources)
                save(
                    name,
                    {
                        "quiz": quiz.model_dump(mode="json"),
                        "decision": decision.model_dump(mode="json"),
                    },
                )
                manifest["cases"][name] = {
                    "passed": decision.passed,
                    "issues": [i.model_dump() for i in decision.issues],
                    "report_path": decision.report_path,
                }
            missing_decision = audit_content(draft, evidence, [], graph, plan)
            save("missing_lesson_sources", {"decision": missing_decision.model_dump(mode="json")})
            manifest["cases"]["missing_lesson_sources"] = {
                "passed": missing_decision.passed,
                "categories": [i.category for i in missing_decision.issues],
                "queries": [q for i in missing_decision.issues for q in i.queries],
            }
            case("missing_sources")
            try:
                audit_practice(draft, quiz, evidence, [])
            except ValueError as exc:
                manifest["cases"]["missing_sources"] = {"blocked": True, "reason": str(exc)}
            else:
                raise ValueError("缺少来源时错误放行")
            expected = {
                "h_partial": manifest["cases"]["h_partial"]["actual"] == "partial",
                "lesson_good": manifest["cases"]["lesson_good"]["passed"],
                "lesson_bad": not manifest["cases"]["lesson_bad"]["passed"],
                "uncertain": "uncertain" in manifest["cases"]["uncertain"]["categories"],
                "quiz_good": manifest["cases"]["quiz_good"]["passed"],
            }
            expected["missing_lesson_sources"] = (
                not missing_decision.passed
                and missing_decision.issues[0].category == "evidence"
                and bool(missing_decision.issues[0].queries)
            )
            expected.update(
                {
                    "quiz_bad_" + c: not manifest["cases"]["quiz_bad_" + c]["passed"]
                    for c in ("prompt", "reference_answer", "rubric")
                }
            )
            manifest["expectation_checks"] = expected
            manifest["all_expected"] = all(expected.values())
    except Exception as exc:
        # Do not expose response bodies, credentials, or transport exception messages.
        manifest["error_type"] = type(exc).__name__
        manifest["all_expected"] = False
        print("验收未完成：" + type(exc).__name__ + "；配置/网络异常详情未写入公开记录。")
    finally:
        manifest["scripted_model_responses"] = mode == "offline"
        save("manifest", manifest)
    print(f"{mode}: all_expected={manifest['all_expected']}; records={out}")
    return 0 if manifest["all_expected"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("输出已存在，请使用新目录")
    if args.mode == "live":
        load_dotenv(ROOT / ".env")
    else:
        os.environ["PYTHON_DOTENV_DISABLED"] = "1"
        os.environ.pop("OPENAI_API_KEY", None)
    return run(args.out.resolve(), args.mode)


if __name__ == "__main__":
    sys.exit(main())
