"""Run a scripted H → A / D → G → D → G → E handoff, without a key or network.

This verifies orchestration and locations only, NOT actual model accuracy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from learngraph_review import ReviewService, approved_material, require_delivery_approval
from learngraph_review.models import Context, LessonDraft, Material, Usage

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


class OfflineFixtureGateway:
    def __init__(self, results):
        self.results = iter(results)

    def run(self, *, schema, **kwargs):
        return schema.model_validate(next(self.results)), Usage(
            model="offline-fixture-NOT-A-MODEL-RUN",
            response_id="scripted-fixture",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            estimated_cost_usd=None,
            elapsed_seconds=0,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="outputs/offline-demo")
    args = parser.parse_args()
    target = Path(args.out)
    if target.exists():
        parser.error("输出目录已存在，请换一个新目录，避免覆盖已有记录。")
    context = Context.model_validate(read("context.json"))
    material = Material.model_validate(read("material.json"))
    sources = [Material.model_validate(x) for x in read("sources.json")]
    bad = LessonDraft.model_validate(read("lesson_bad.json"))
    fixed = LessonDraft.model_validate(read("lesson_fixed.json"))
    h_output = {
        "summary": "离线预置：第一块准入，第二块广告排除。",
        "decisions": [
            {
                "block_id": b.id,
                "decision": "accept" if i == 0 else "reject",
                "relevance": "direct" if i == 0 else "irrelevant",
                "reason": "支持可变性目标。" if i == 0 else "广告与课程目标无关。",
                "anchor": {"block_id": b.id, "quote": b.text, "occurrence": 0},
                "suggestion": "交给 A 保留来源。" if i == 0 else "排除广告片段。",
            }
            for i, b in enumerate(material.blocks)
        ],
    }
    issue = {
        "category": "contradiction",
        "severity": "error",
        "target": {"block_id": "explanation", "quote": bad.sections[0].text, "occurrence": 0},
        "message": "列表和元组的可变性写反，与引用原文冲突。",
        "suggestion": "将正文改为列表可变、元组不可变，保留对应引用。",
        "source_id": "python-types",
        "source_anchor": {"block_id": "b0001", "quote": sources[0].blocks[0].text, "occurrence": 0},
    }
    service = ReviewService(
        OfflineFixtureGateway(
            [
                h_output,
                {
                    "summary": "离线预置：有引用，但陈述与来源相反。",
                    "issues": [issue],
                    "checked_objectives": context.objectives,
                },
                {
                    "summary": "离线预置：修订稿与来源对应。",
                    "issues": [],
                    "checked_objectives": context.objectives,
                },
            ]
        )
    )
    h_report = service.review_material(context, material)
    accepted = approved_material(material, h_report, context)
    first = service.review_lesson(context, bad, sources)
    second = service.review_lesson(context, fixed, sources, previous=first)
    require_delivery_approval(fixed, second, context, sources)
    target.mkdir(parents=True)
    products = {
        "h_report.json": h_report.model_dump(mode="json"),
        "h_to_a.json": [accepted.model_dump(mode="json")],
        "g_revision_1.json": first.model_dump(mode="json"),
        "g_revision_2.json": second.model_dump(mode="json"),
        "NOTICE.json": {
            "mode": "scripted-offline-fixture",
            "real_api_calls": 0,
            "proves": "格式、引用定位、过滤、路由与修订记录可运行。",
            "does_not_prove": "模型审查准确性、提示注入防御效果、真实 API 账号可用性或费用。",
        },
    }
    for name, product in products.items():
        (target / name).write_text(
            json.dumps(product, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"OFFLINE FIXTURE: H={h_report.status}; G1={first.status}; G2={second.status}")
    print(f"No API requests. Records saved to {target}")


if __name__ == "__main__":
    main()
