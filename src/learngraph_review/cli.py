from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from .agents import ReviewService, approved_material
from .errors import ReviewError
from .extract import extract_file
from .models import Context, GReport, HReport, LessonDraft, Material


def _read(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: str, value) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    # O_EXCL semantics: original review / delivery records are never overwritten.
    with target.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="任务 2：H 输入审查与 G 内容/来源核查")
    parser.add_argument("--env-file", default=".env", help="本机配置文件；不会覆盖已有环境变量")
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="本地文件解析，不调用 API")
    extract.add_argument("file")
    extract.add_argument("--id", dest="material_id")
    extract.add_argument("--out", required=True)
    h = commands.add_parser("h", help="H：审查已解析上传资料")
    h.add_argument("--context", required=True)
    h.add_argument("--material", required=True)
    h.add_argument("--out", required=True)
    approved = commands.add_parser("handoff", help="依据 H 记录导出可交给 A 的资料数组，不调用 API")
    approved.add_argument("--context", required=True)
    approved.add_argument("--material", required=True)
    approved.add_argument("--report", required=True)
    approved.add_argument("--out", required=True)
    g = commands.add_parser("g", help="G：核查单节教学稿")
    g.add_argument("--context", required=True)
    g.add_argument("--lesson", required=True)
    g.add_argument("--sources", required=True, help="Material 数组 JSON，由 A 提供本节使用的资料")
    g.add_argument("--previous", help="上轮 G 审查记录，用于生成修订对比")
    g.add_argument("--out", required=True)
    schemas = commands.add_parser("schemas", help="导出数据交换 JSON Schema，不调用 API")
    schemas.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(args.env_file, override=False)
    try:
        # Refuse overwriting before issuing any paid request.
        if Path(args.out).exists():
            raise ReviewError("输出文件已存在，请使用新的文件名以保留原始记录")
        if args.command == "extract":
            result = extract_file(args.file, material_id=args.material_id)
        elif args.command == "schemas":
            result = {
                m.__name__: m.model_json_schema()
                for m in (
                    Context,
                    Material,
                    LessonDraft,
                    HReport,
                    GReport,
                )
            }
        else:
            context = Context.model_validate(_read(args.context))
            if args.command == "handoff":
                material = Material.model_validate(_read(args.material))
                report = HReport.model_validate(_read(args.report))
                accepted = approved_material(material, report, context)
                result = [accepted.model_dump(mode="json")] if accepted is not None else []
            elif args.command == "h":
                material = Material.model_validate(_read(args.material))
                result = ReviewService().review_material(context, material)
            else:
                lesson = LessonDraft.model_validate(_read(args.lesson))
                sources = [Material.model_validate(x) for x in _read(args.sources)]
                previous = GReport.model_validate(_read(args.previous)) if args.previous else None
                result = ReviewService().review_lesson(context, lesson, sources, previous=previous)
        _write(args.out, result)
        status = getattr(result, "status", "written")
        print(f"{args.command}: {status}; result: {args.out}")
        if status in {"revise", "reject", "needs_review", "partial"}:
            return 2
        return 0
    except (ReviewError, ValidationError, OSError, ValueError, TypeError) as exc:
        # ValidationError / JSON errors may contain user text: do not print their body.
        message = str(exc) if isinstance(exc, ReviewError) else type(exc).__name__
        print(f"审查未完成：{message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
