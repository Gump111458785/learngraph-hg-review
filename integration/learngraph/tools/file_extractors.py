"""成员 2：本地文件解析与页/段落定位；不执行用户文件、不自动采纳。"""

from __future__ import annotations

from pathlib import Path

ALLOWED_SUFFIXES = {".txt", ".md", ".pdf", ".docx", ".pptx"}
MAX_BYTES = 10 * 1024 * 1024


def validate_input_file(path: str | Path) -> Path:
    """仅做扩展名/大小预校验；不代表已审查真实性或内容安全。"""
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(p)
    if p.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"不支持的文件格式：{p.suffix}")
    if p.stat().st_size > MAX_BYTES:
        raise ValueError("单文件超过 10 MB 的示例限制")
    return p


def extract_text_with_locators(path: str | Path):
    """返回内部 Material（blocks 含页/段落/字符定位），保留公共入口名称。"""
    from learngraph_review.extract import extract_file

    return extract_file(validate_input_file(path))
