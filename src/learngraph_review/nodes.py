"""Small LangGraph-compatible node factories, without owning the group's graph/state."""

from typing import Any

from .agents import ReviewService, approved_material
from .errors import ReviewError
from .models import Context, GReport, LessonDraft, Material


def make_h_node(service: ReviewService):
    def h_node(state: dict[str, Any]) -> dict[str, Any]:
        context = Context.model_validate(state["context"])
        materials = [Material.model_validate(x) for x in state.get("uploads", [])]
        if len({m.id for m in materials}) != len(materials):
            raise ReviewError("上传资料 id 必须唯一")
        reports = [service.review_material(context, material) for material in materials]
        accepted = [approved_material(m, r, context) for m, r in zip(materials, reports)]
        return {
            "h_reports": [r.model_dump(mode="json") for r in reports],
            "approved_uploads": [m.model_dump(mode="json") for m in accepted if m is not None],
        }

    return h_node


def make_g_node(service: ReviewService):
    def g_node(state: dict[str, Any]) -> dict[str, Any]:
        lesson = LessonDraft.model_validate(state["lesson"])
        previous = GReport.model_validate(state["g_report"]) if state.get("g_report") else None
        # Moving to a new unit is not a revision of the preceding unit's lesson.
        if previous is not None and previous.unit_id != lesson.unit_id:
            previous = None
        report = service.review_lesson(
            Context.model_validate(state["context"]),
            lesson,
            [Material.model_validate(x) for x in state.get("sources", [])],
            previous=previous,
        )
        return {"g_report": report.model_dump(mode="json"), "next_agent": report.next_agent}

    return g_node
