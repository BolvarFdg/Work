import re
from collections import Counter

def diff_words(sentence_a: str, sentence_b: str) -> list[str]:
    """返回 A 中与 B 不同的单词（忽略大小写和标点，保留 A 的顺序和重复次数）"""
    words_a = re.findall(r"[a-zA-Z']+", sentence_a.lower())
    words_b = re.findall(r"[a-zA-Z']+", sentence_b.lower())
    remaining = Counter(words_a) - Counter(words_b)  # 多集合差：A 减去 B
    result = []
    for w in words_a:
        if remaining[w] > 0:
            result.append(w)
            remaining[w] -= 1
    return result