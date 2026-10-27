import json
from pathlib import Path

import pytest

from learngraph_review.models import Context, LessonDraft, Material, Usage

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("HG_REVIEW_MODE", "mock")
    monkeypatch.setenv("HG_SOURCES_FILE", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HG_PROJECT_ROOT", raising=False)


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture
def context():
    return Context.model_validate(load("context.json"))


@pytest.fixture
def material():
    return Material.model_validate(load("material.json"))


@pytest.fixture
def sources():
    return [Material.model_validate(x) for x in load("sources.json")]


@pytest.fixture
def bad_lesson():
    return LessonDraft.model_validate(load("lesson_bad.json"))


@pytest.fixture
def fixed_lesson():
    return LessonDraft.model_validate(load("lesson_fixed.json"))


class FixtureGateway:
    """Explicit synthetic model output; never makes a paid request."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        result = kwargs["schema"].model_validate(self.results.pop(0))
        usage = Usage(
            model="offline-fixture",
            response_id="offline-fixture",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            estimated_cost_usd=None,
            elapsed_seconds=0,
        )
        return result, usage


def h_result(material, decisions=None):
    decisions = decisions or ["accept"] * len(material.blocks)
    return {
        "summary": "离线合成的 H 输出，用于测试交接逻辑。",
        "decisions": [
            {
                "block_id": block.id,
                "decision": decision,
                "relevance": "irrelevant" if decision == "reject" else "direct",
                "reason": "与目标的对应关系测试。",
                "anchor": {"block_id": block.id, "quote": block.text, "occurrence": 0},
                "suggestion": "保留课程相关片段；无关内容排除。",
            }
            for block, decision in zip(material.blocks, decisions)
        ],
    }


def g_result(context, issues=None):
    return {
        "summary": "离线合成的 G 输出，不是实测模型结论。",
        "issues": issues or [],
        "checked_objectives": context.objectives,
    }


def contradiction(lesson, source):
    return {
        "category": "contradiction",
        "severity": "error",
        "target": {
            "block_id": lesson.sections[0].id,
            "quote": lesson.sections[0].text,
            "occurrence": 0,
        },
        "message": "列表与元组的可变性被颠倒。",
        "suggestion": "改为列表可变、元组不可变，并保持引用。",
        "source_id": source.id,
        "source_anchor": {
            "block_id": source.blocks[0].id,
            "quote": source.blocks[0].text,
            "occurrence": 0,
        },
    }
