"""成员 2：H 资料审查；HG_REVIEW_MODE=live 开启真实 API，默认保留 Mock。"""

from __future__ import annotations

from core.contracts import FileReviewReport, LearningRequest


def run_h(request: LearningRequest) -> list[FileReviewReport]:
    from learngraph_review.team_adapter import review_mode, run_h_live

    if review_mode() == "live":
        return run_h_live(request)
    return [
        FileReviewReport(
            file_path=path,
            status="unreviewed",
            reason="MOCK：尚未解析或核验此文件；A 不得将其当作可靠来源。",
        )
        for path in request.uploaded_files
    ]
