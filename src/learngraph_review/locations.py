from .errors import ReviewError
from .models import Anchor, Location, TextBlock


def locate(document_id: str, blocks: list[TextBlock], anchor: Anchor) -> Location:
    block = next((b for b in blocks if b.id == anchor.block_id), None)
    if block is None:
        raise ReviewError(f"定位失败：不存在文本块 {anchor.block_id}")
    start = -1
    search_from = 0
    for _ in range(anchor.occurrence + 1):
        start = block.text.find(anchor.quote, search_from)
        if start < 0:
            raise ReviewError(f"定位失败：{anchor.block_id} 中找不到指定次数的原文引句")
        search_from = start + len(anchor.quote)
    end = start + len(anchor.quote)
    return Location(
        document_id=document_id,
        block_id=block.id,
        quote=anchor.quote,
        occurrence=anchor.occurrence,
        start=start,
        end=end,
        line_start=block.text.count("\n", 0, start) + 1,
        line_end=block.text.count("\n", 0, end - 1) + 1,
        page=block.page,
        paragraph=block.paragraph,
        source_start=block.source_start + start,
    )
