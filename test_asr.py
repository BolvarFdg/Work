import re

RETRACT = re.compile(
    r"不判定为错|不定为错|不视为|不构成|不属于|"
    r"(?:不存在|未发现|没|无)(?:明显|实质性?|重大|关键|其他){0,2}的?"
    r"(?:问题|错误|差异|缺失|漏译|错译|过译|误译)|"
    r"无误|无需(?:报错|修改|改动)|取消报错|撤销报错|移除本[条项]|误报|"
    r"(?<!不)可接受|维持原译|保留原译|"
    r"本[句条]通过|(?:判定|复核|检查|审查)通过|[，,]通过\s*$"
)
_SENT_SPLIT = re.compile(r"[。；;！!？?]|\.(?=\s|$)")

def filter_contradictions(errors: list) -> list:
    """丢弃自相矛盾（开头报错、结尾撤回）的条目，返回正常错误列表"""
    cleaned = []
    for item in errors:
        sents = [s for s in _SENT_SPLIT.split(item) if s.strip()]
        if sents and RETRACT.search("".join(sents[-2:])):
            continue
        cleaned.append(item)
    return cleaned