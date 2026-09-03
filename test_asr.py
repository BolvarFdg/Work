import re

RETRACT = re.compile(
    r"不判定为错|不视为|不构成|不属于|无实质性?差异|"
    r"无错误|没有错误|不存在.{0,6}(?:错误|问题|漏译)|误报|"
    r"(?<!不)可接受|维持原译|保留原译"
)
_SENT_SPLIT = re.compile(r"[。；;！!？?]|\.(?=\s|$)")

def filter_contradictions(errors: list[str]) -> list[str]:
    """丢弃自相矛盾（开头报错、结尾撤回）的条目，返回正常错误列表"""
    cleaned = []
    for item in errors:
        sents = [s for s in _SENT_SPLIT.split(item) if s.strip()]
        if sents and RETRACT.search("".join(sents[-2:])):
            continue
        cleaned.append(item)
    return cleaned