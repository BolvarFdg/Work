【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验数字、单位、规格信息】
每条句子包含：单行原文、单行待检译文、该行类型（title=标题，其余=正文）、该行上下文（该句在原文档中的上文/下文邻居句等）、该行检索参考术语（最多5条，可为空，逗号分隔）、该行Top3匹配参考平行语料（最多3条，可为空）

### Few‑Shot 样例：无数字错误，输出空
示例输入：
句子1：
单行原文：该模块最大输出功率2.5W。
单行待检译文：The module supports maximum output power of 2.5W.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 示例：数值等价不报，数值错误照报
示例输入：
句子1：
单行原文：支持3K规格的扩展板，缩放比例为1/10。
单行待检译文：This board supports the 3000-card specification, with a scaling ratio of 0.1-fold.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：
句子2：
单行原文：该单板功耗为2.5W。
单行待检译文：The power consumption of this board is 5W.
该行类型：p
该行上下文：
该行参考术语：2.5W
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "该单板功耗为2.5W。",
            "target_error_full_line": "The power consumption of this board is 5W.",
            "target_correct_full_line": "The power consumption of this board is 2.5W.",
            "error_desc": "1. 数字错误：功耗 2.5W 被译成 5W。",
            "severity": "严重"
        }}
    ]
}}

⚠️ 禁止检查：标点空格、标签/占位符、单词大小写——任何情况不报；数值只判等价、格式不限；error_desc 直接写错误，禁止引用来源与禁止项内容。
{sentence_block}