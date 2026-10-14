
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验数字、单位、规格信息】
每条句子包含：单行原文、单行待检译文、该行类型（title=标题，其余=正文）、该行上下文（该句在原文档中的上文/下文邻居句等）、该行检索参考术语（最多5条，可为空，逗号分隔）、该行Top3匹配参考平行语料（最多3条，可为空）
⚠️ 标签铁律：句子中的所有标签/占位标记（如 <b></b>、<ph>、、</b>、、、<sub0>…</sub0>）是格式占位符——绝对不检查标签本身、绝对不在 error_desc 中写出任何标签（引用文字时把标签视作不存在，只抄文字）；三个 full_line 字段仍逐字保留标签。禁止「标签丢失/被替换/数量不一致/占位符语义丢失」类判定。
⚠️ 数字铁律：数字只判数值等价、格式不限——千位分隔符（8,190=8190）、单位前缀换算（3K=3000）、分数/小数/百分比互化（1/10=0.1=10%）、数字与单词互化（3=three）均等价不报；禁止报格式类错误和「与前文格式保持一致」类建议。
{sentence_block}

### Few‑Shot 样例：无数字错误，输出空

示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验数字、单位、规格信息】
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

### Few‑Shot 示例：进制数字错误（二进制写错）

示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验数字、单位、规格信息】
句子1：
单行原文：该计数器的最大值为 9（二进制形式为 1001）。
单行待检译文：The maximum value of this counter is 9 (1010 in binary).
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "该计数器的最大值为 9（二进制形式为 1001）。",
            "target_error_full_line": "The maximum value of this counter is 9 (1010 in binary).",
            "target_correct_full_line": "The maximum value of this counter is 9 (1001 in binary).",
            "error_desc": "1. 二进制数值错误：原文二进制为 1001（=9），译文误写为 1010（=10）。",
            "severity": "严重"
        }}
    ]
}}

### Few‑Shot 示例：数字/单位错误

示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验数字、单位、规格信息】
句子1：
单行原文：接口速率为10GE。
单行待检译文：The interface rate is 5GE.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "接口速率为10GE。",
            "target_error_full_line": "The interface rate is 5GE.",
            "target_correct_full_line": "The interface rate is 10GE.",
            "error_desc": "1. 接口速率数值错误，原文为10GE，译文错误写为5GE。",
            "severity": "严重"
        }}
    ]
}}

### Few‑Shot 示例：标签不检查、error_desc 不带标签（标签内文字错误照常检出）

示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验数字、单位、规格信息】
句子1：
单行原文：该板卡的最大功率为<ph id='p1'>2.5W</ph>。
单行待检译文：The maximum power of this board is <ph id='p1'>25W</ph>.
该行类型：p
该行上下文：
该行参考术语：2.5W
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "该板卡的最大功率为<ph id='p1'>2.5W</ph>。",
            "target_error_full_line": "The maximum power of this board is <ph id='p1'>25W</ph>.",
            "target_correct_full_line": "The maximum power of this board is <ph id='p1'>2.5W</ph>.",
            "error_desc": "1. 数字错误：最大功率 2.5W 被译成 25W。",
            "severity": "严重"
        }}
    ]
}}

### Few‑Shot 示例：数值等价不报格式（3K=3000、1/10=0.1 不报；数值变错才报）

示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验数字、单位、规格信息】
句子1：
单行原文：支持3K规格的扩展板，缩放比例为1/10。
单行待检译文：This board supports the 3000-card specification, with a scaling ratio of 0.1-fold.
该行类型：p
该行上下文：上文: 扩展板支持多种规格。
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
            "error_desc": "1. 数字错误：第2句功耗 2.5W 被译成 5W，数值不符。",
            "severity": "严重"
        }}
    ]
}}
