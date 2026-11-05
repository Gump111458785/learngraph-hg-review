"""Add to team agents/learning_services.py; depends on V3 public contracts."""
from core.learning_contracts import AuditDecision, RepairIssue


def audit_practice(draft, quiz, evidence, sources):
    """Dedicated Live quiz review; returns the existing V3 public contract."""
    from learngraph_review.team_adapter import run_quiz_live

    report, path = run_quiz_live(draft, quiz, evidence, sources)
    issues = [
        RepairIssue(
            category="uncertain" if c.status == "needs_review" else "content",
            reason=f"{c.component}: {c.reason}；建议：{c.suggestion}",
            evidence=(
                f"question_id={report.question_id}; component={c.component}; "
                f"字符 {c.location.start}:{c.location.end}; report={path.name}"
            ),
            knowledge_ids=quiz.questions[0].knowledge_ids,
        )
        for c in report.checks
        if c.status != "pass"
    ]
    return AuditDecision(
        passed=report.status == "pass", issues=issues, mode="live", report_path=str(path)
    )
