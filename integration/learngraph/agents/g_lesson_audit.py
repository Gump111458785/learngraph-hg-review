"""成员 2：G 来源与教学核查；真实模式需原文，默认保留 Mock 回归。"""

from __future__ import annotations

from core.contracts import EvidenceItem, LessonAudit, LessonDraft


def run_g(draft: LessonDraft, evidence: list[EvidenceItem]) -> LessonAudit:
    from learngraph_review.team_adapter import review_mode, run_g_live

    if review_mode() == "live":
        return run_g_live(draft, evidence)
    allowed = {e.source_id for e in evidence}
    issues = []
    if not draft.sections:
        issues.append("没有教学内容段落")
    if not draft.objective.strip():
        issues.append("缺少单元目标")
    cited = sorted({src for section in draft.sections for src in section.source_ids})
    for sid in cited:
        if sid not in allowed:
            issues.append(f"引用了未知来源 {sid}")
    if not cited:
        issues.append("缺少可追溯来源标识")
    return LessonAudit(
        lesson_id=draft.lesson_id, passed=not issues, issues=issues, checked_source_ids=cited
    )
