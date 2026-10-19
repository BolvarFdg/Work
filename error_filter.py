import json
import re

from text_normalizer import strip_code_fence

# 首尾空白与中英文标点（含括号/引号/尖括号）
_STRIP_CHARS = r'\s\u3000，。、；：！？（）【】《》\u201c\u201d\u2018\u2019.,;:!?()<>"\'\u200b'
_STRIP_RE = re.compile(rf'^[{_STRIP_CHARS}]+|[{_STRIP_CHARS}]+$', re.UNICODE)


def normalize_for_fix_check(text: str) -> str:
    """归一化用于修正有效性判定：去首尾空白/标点 + 转小写。"""
    return _STRIP_RE.sub('', text).lower()


def filter_ineffective_errors(content: str) -> str:
    """过滤修正未生效的错误条目。

    判定口径：target_correct_full_line 与 target_error_full_line 归一化
    （去首尾空白/标点 + 转小写）后相同 → 该条修正无效，丢弃。

    输入：子 agent 的 content（JSON 字符串）
    输出：过滤后的 content（JSON 字符串）
    - 有条目被过滤 → 重新序列化；全被过滤 → 返回 has_error=false 的空结果
    - 解析失败 / 无需过滤 → 原样返回
    """
    stripped = strip_code_fence(content)
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return content

    if not isinstance(parsed, dict):
        return content

    error_list = parsed.get("error_list") or []
    if not error_list:
        return content

    filtered = []
    for e in error_list:
        if not isinstance(e, dict):
            continue
        orig = normalize_for_fix_check(e.get("target_error_full_line") or "")
        fix = normalize_for_fix_check(e.get("target_correct_full_line") or "")
        if orig != fix:
            filtered.append(e)

    if len(filtered) == len(error_list):
        return content  # 没有条目被过滤

    parsed["error_list"] = filtered
    parsed["has_error"] = len(filtered) > 0
    return json.dumps(parsed, ensure_ascii=False)
