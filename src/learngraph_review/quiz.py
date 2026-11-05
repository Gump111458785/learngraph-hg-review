"""Grounded, component-by-component quiz review; never grades student answers."""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import Field, ValidationError, create_model

from .errors import ReviewError
from .locations import locate
from .models import Anchor, Context, Location, Material, StrictModel, TextBlock, Usage, digest
from .prompts import BASE

Component = Literal["prompt", "reference_answer", "rubric"]
Verdict = Literal["pass", "revise", "needs_review"]


class QuizDraft(StrictModel):
    lesson_id: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    reference_answer: str = Field(min_length=1)
    rubric: str = Field(min_length=1)

    def blocks(self) -> list[TextBlock]:
        return [
            TextBlock(id=k, text=getattr(self, k)) for k in ("prompt", "reference_answer", "rubric")
        ]


class ComponentResult(StrictModel):
    component: Component
    status: Verdict
    reason: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)
    target: Anchor
    lesson_anchor: Anchor | None
    source_id: str | None
    source_anchor: Anchor | None


class QuizModelResult(StrictModel):
    summary: str = Field(min_length=1)
    checked_objectives: list[str] = Field(min_length=1)
    checks: list[ComponentResult] = Field(min_length=3, max_length=3)


class ComponentReview(ComponentResult):
    location: Location
    lesson_location: Location | None
    evidence_location: Location | None


class QuizReport(StrictModel):
    review_id: str
    created_at: str
    lesson_id: str
    question_id: str
    quiz_hash: str
    lesson_hash: str
    sources_hash: str
    context_hash: str
    status: Verdict
    summary: str
    checks: list[ComponentReview] = Field(min_length=3, max_length=3)
    usage: Usage


QUIZ_PROMPT = (
    BASE
    + """
你审核尚未交付的练习，不生成题目、不评分学生作答。必须分别检查三个组件：
prompt：题干清楚、可回答、与本课目标及已审教案一致，不能偷换条件。
reference_answer：参考答案是否正确、完整；必须独立对照原文和教案，不能因题干暗示而认可错误答案。
rubric：评分规则是否与正确答案、题目条件一致，不能奖励错误结论或遗漏关键评分点。
checks 恰好覆盖 prompt/reference_answer/rubric，每项一次，即使通过也要说明具体依据。
target.block_id 必须等于 component，quote 是该组件实际文本。
每项都给 status、reason、suggestion。确定错误为 revise；缺少原文、教案依据或不能确定则
needs_review，禁止无依据 pass。通过项必须有 lesson_anchor 或 source_id/source_anchor。
lesson_anchor 定位 lesson_blocks；source_anchor 定位 sources 中的真实块，两种定位均须逐字引用。
来源编号和来源 anchor 必须同时提供或同时为空。不得捏造引用或偏移。
checked_objectives 逐字覆盖 context.objectives。不要把原教案审核通过当作练习必然通过。
不要要求单道练习穷尽整份教案的所有细节；
围绕当前学习目标和题目条件检查。准确的简洁回答可以通过，不能仅因措辞或省略可选拓展
而返修。评分规则不能要求题干未提出、与学习目标无关的额外知识。
"""
)


def review_quiz(
    service,
    context: Context,
    quiz: QuizDraft,
    lesson_blocks: list[TextBlock],
    sources: list[Material],
) -> QuizReport:
    """Validate coverage, quotations and provenance before permitting delivery."""
    if not lesson_blocks or any(not b.text.strip() for b in lesson_blocks + quiz.blocks()):
        raise ReviewError("练习审核需要非空教案、题干、答案和评分规则")
    if len({b.id for b in lesson_blocks}) != len(lesson_blocks):
        raise ReviewError("练习教案块 ID 不能重复")
    source_map = {s.id: s for s in sources}
    if not sources or len(source_map) != len(sources):
        raise ReviewError("练习审核缺少原文或原文编号重复")
    # Constrain the SDK schema too: real responses paraphrased this field, which
    # made their objective coverage impossible to bind to this exact request.
    source_anchor = create_model(
        "ProvidedSourceAnchor",
        __base__=Anchor,
        block_id=(Literal[tuple(sorted({b.id for s in sources for b in s.blocks}))], ...),
    )
    lesson_anchor = create_model(
        "ProvidedLessonAnchor",
        __base__=Anchor,
        block_id=(Literal[tuple(b.id for b in lesson_blocks)], ...),
    )
    variants = []
    for component in ("prompt", "reference_answer", "rubric"):
        target = create_model(
            component.title().replace("_", "") + "Target",
            __base__=Anchor,
            block_id=(Literal[component], ...),
        )
        variants.append(
            create_model(
                component.title().replace("_", "") + "Check",
                __base__=ComponentResult,
                component=(Literal[component], ...),
                target=(target, ...),
                source_id=(Literal[tuple(source_map)] | None, ...),
                source_anchor=(source_anchor | None, ...),
                lesson_anchor=(lesson_anchor | None, ...),
            )
        )
    component_type = variants[0] | variants[1] | variants[2]
    response_schema = create_model(
        "QuizModelResult",
        __base__=QuizModelResult,
        checks=(list[component_type], Field(min_length=3, max_length=3)),
        checked_objectives=(
            list[Literal[tuple(context.objectives)]],
            Field(min_length=len(context.objectives), max_length=len(context.objectives)),
        ),
    )
    try:
        result, usage = service.gateway.run(
            model=service.settings.model_g,
            instructions=QUIZ_PROMPT,
            payload={
                "context": context.model_dump(),
                "quiz": quiz.model_dump(),
                "lesson_blocks": [b.model_dump() for b in lesson_blocks],
                "sources": [s.model_dump() for s in sources],
            },
            schema=response_schema,
        )
    except ValidationError as exc:
        raise ReviewError("练习模型结果不符合当前目标与审核协议") from exc
    if sorted(result.checked_objectives) != sorted(context.objectives):
        raise ReviewError("练习审核未完整覆盖目标")
    if sorted(c.component for c in result.checks) != ["prompt", "reference_answer", "rubric"]:
        raise ReviewError("练习审核必须分别覆盖题干、参考答案和评分规则")
    reviews = []
    for check in result.checks:
        if check.target.block_id != check.component:
            raise ReviewError("练习审核组件与问题定位不一致")
        target = locate(quiz.question_id, quiz.blocks(), check.target)
        lesson = (
            locate(quiz.lesson_id, lesson_blocks, check.lesson_anchor)
            if check.lesson_anchor
            else None
        )
        evidence = None
        if (check.source_id is None) != (check.source_anchor is None):
            raise ReviewError("练习来源编号与原文定位必须同时提供")
        if check.source_id is not None:
            source = source_map.get(check.source_id)
            if source is None:
                raise ReviewError("练习审核引用了未提供的原文")
            evidence = locate(source.id, source.blocks, check.source_anchor)
        if check.status == "pass" and lesson is None and evidence is None:
            raise ReviewError("练习通过结论缺少可定位依据")
        reviews.append(
            ComponentReview(
                **check.model_dump(),
                location=target,
                lesson_location=lesson,
                evidence_location=evidence,
            )
        )
    statuses = {c.status for c in reviews}
    status = (
        "needs_review"
        if "needs_review" in statuses
        else ("revise" if "revise" in statuses else "pass")
    )
    return QuizReport(
        review_id=f"quiz-g-{uuid4().hex}",
        created_at=datetime.now(timezone.utc).isoformat(),
        lesson_id=quiz.lesson_id,
        question_id=quiz.question_id,
        quiz_hash=digest(quiz),
        lesson_hash=digest(lesson_blocks),
        sources_hash=digest(sources),
        context_hash=digest(context),
        status=status,
        summary=result.summary,
        checks=reviews,
        usage=usage,
    )
