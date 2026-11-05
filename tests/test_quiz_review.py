"""Quiz review calls the real service/adapter with synthetic model responses."""

from copy import deepcopy

import pytest
from conftest import FixtureGateway

from learngraph_review import ReviewService
from learngraph_review.errors import ReviewError
from learngraph_review.models import Context, Material, TextBlock
from learngraph_review.quiz import QuizDraft, review_quiz


def inputs():
    context = Context(topic="Python", objectives=["判断列表的可变性"])
    lesson = [TextBlock(id="section-1", text="Python 列表是可变对象，可以修改元素。")]
    sources = [Material(id="s", title="资料", source="types.txt", blocks=lesson)]
    quiz = QuizDraft(
        lesson_id="L1",
        question_id="Q1",
        prompt="列表能修改元素吗？",
        reference_answer="能。",
        rubric="回答能并说明列表可变得满分。",
    )
    return context, quiz, lesson, sources


def response(quiz, lesson, broken=None, status="revise"):
    return dict(
        summary="明确标识的离线输出",
        checked_objectives=["判断列表的可变性"],
        checks=[
            dict(
                component=c,
                status=status if c == broken else "pass",
                reason="与教案不符" if c == broken else "教案明确给出可变性依据",
                suggestion="按教案修正" if c == broken else "保留",
                target=dict(block_id=c, quote=getattr(quiz, c), occurrence=0),
                lesson_anchor=dict(block_id=lesson[0].id, quote=lesson[0].text, occurrence=0),
                source_id=None,
                source_anchor=None,
            )
            for c in ("prompt", "reference_answer", "rubric")
        ],
    )


@pytest.mark.parametrize("broken", [None, "prompt", "reference_answer", "rubric"])
def test_each_component_gets_checked_and_a_bad_component_blocks(broken):
    context, quiz, lesson, sources = inputs()
    gateway = FixtureGateway(response(quiz, lesson, broken))
    report = review_quiz(ReviewService(gateway), context, quiz, lesson, sources)
    assert report.status == ("revise" if broken else "pass")
    assert len(report.checks) == 3
    assert all(c.location.quote == getattr(quiz, c.component) for c in report.checks)
    assert "评分规则" in gateway.calls[0]["instructions"]
    assert "不检查或生成练习" not in gateway.calls[0]["instructions"]
    assert gateway.calls[0]["payload"]["sources"][0]["blocks"][0]["text"] == lesson[0].text


@pytest.mark.parametrize(
    "damage",
    ["duplicate", "bad_quote", "invented_source", "no_basis", "wrong_target", "missing_goal"],
)
def test_invalid_model_review_never_approves(damage):
    context, quiz, lesson, sources = inputs()
    raw = response(quiz, lesson)
    check = raw["checks"][0]
    if damage == "duplicate":
        raw["checks"][1] = deepcopy(check)
    elif damage == "bad_quote":
        check["target"]["quote"] = "不在实际题干中"
    elif damage == "invented_source":
        check["source_id"] = "fake"
        check["source_anchor"] = check["lesson_anchor"]
    elif damage == "no_basis":
        check["lesson_anchor"] = None
    elif damage == "wrong_target":
        check["target"]["block_id"] = "rubric"
    else:
        raw["checked_objectives"] = ["偷换的目标"]
    with pytest.raises(ReviewError):
        review_quiz(ReviewService(FixtureGateway(raw)), context, quiz, lesson, sources)


def test_missing_sources_fails_before_model_call():
    context, quiz, lesson, _ = inputs()
    gateway = FixtureGateway()
    with pytest.raises(ReviewError, match="缺少原文"):
        review_quiz(ReviewService(gateway), context, quiz, lesson, [])
    assert not gateway.calls


def test_uncertain_component_requires_manual_review():
    context, quiz, lesson, sources = inputs()
    report = review_quiz(
        ReviewService(FixtureGateway(response(quiz, lesson, "reference_answer", "needs_review"))),
        context,
        quiz,
        lesson,
        sources,
    )
    assert report.status == "needs_review"
