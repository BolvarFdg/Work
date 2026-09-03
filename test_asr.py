import re

RETRACT = re.compile(
    r"不判定为错|不视为|不构成|不属于|无实质性?差异|"
    r"无错误|没有错误|不存在.{0,6}(?:错误|问题|漏译)|误报|"
    r"(?<!不)可接受|维持原译|保留原译"
)
_SENT_SPLIT = re.compile(r"[。；;！!？?]|\.(?=\s|$)")   # . 仅在句末/后接空白时切分

def is_self_contradicted(item: str) -> bool:
    sents = [s for s in _SENT_SPLIT.split(item) if s.strip()]
    if not sents:
        return False
    return bool(RETRACT.search("".join(sents[-2:])))    # 最后两句拼接