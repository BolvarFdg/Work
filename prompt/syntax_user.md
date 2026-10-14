【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考检查语法与句式统一性】
每条句子包含：单行原文、单行待检译文、该行类型（title=标题，其余=正文）、该行上下文（该句在原文档中的上文/下文邻居句等）、该行检索参考术语（最多5条，可为空，逗号分隔）、该行Top3匹配参考平行语料（最多3条，可为空）
⚠️ 标签铁律：句子中的所有标签/占位标记（如 <b>、<ph>、<xref/>、</b>、<x0/>、<ph0/>、<sub0>…</sub0>）是格式占位符——绝对不检查标签本身、绝对不在 error_desc 中写出任何标签（引用文字时把标签视作不存在，只抄文字）；三个 full_line 字段仍逐字保留标签。
{sentence_block}

### Few‑Shot 样例：无语法错误，输出空
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考检查语法与句式统一性】
句子1：
单行原文：该设备支持双频Wi-Fi传输。
单行待检译文：This device supports dual-band Wi-Fi transmission.
该行类型：p
该行上下文：
该行参考术语：Wi-Fi
该行Top3参考平行语料：

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 样例：标题精简表达（标题允许省略冠词/系动词，不判句子不完整）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考检查语法与句式统一性】
句子1：
单行原文：系统配置
单行待检译文：System Configuration
该行类型：title
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 示例：拼写错误（字母漏写/错写，且拼后仍是合法词）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考检查语法与句式统一性】
句子1：
单行原文：设备需要接收并转发数据包。
单行待检译文：The device needs to recieve and forward the packets.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "设备需要接收并转发数据包。",
            "target_error_full_line": "The device needs to recieve and forward the packets.",
            "target_correct_full_line": "The device needs to receive and forward the packets.",
            "error_desc": "1. 拼写错误：recieve 应为 receive（ie 与 ei 字母顺序错）。",
            "severity": "一般"
        }}
    ]
}}

### Few‑Shot 示例：存在英文语法错误
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考检查语法与句式统一性】
句子1：
单行原文：设备每秒处理大量数据。
单行待检译文：The device process large amounts of data every second.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "设备每秒处理大量数据。",
            "target_error_full_line": "The device process large amounts of data every second.",
            "target_correct_full_line": "The device processes large amounts of data every second.",
            "error_desc": "1. 主谓不一致，主语The device为第三人称单数，谓语动词未使用第三人称单数形式processes",
            "severity": "一般"
        }}
    ]
}}

### Few‑Shot 示例：标签不检查、error_desc 不带标签（标签内文字错误照常检出）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考检查语法与句式统一性】
句子1：
单行原文：设备<ph id='s1'>重启后</ph>自动恢复配置。
单行待检译文：The device <ph id='s1'>after restart</ph> automatically restores the configuration.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "设备<ph id='s1'>重启后</ph>自动恢复配置。",
            "target_error_full_line": "The device <ph id='s1'>after restart</ph> automatically restores the configuration.",
            "target_correct_full_line": "After restart, the device <ph id='s1'>automatically</ph> restores the configuration.",
            "error_desc": "1. 语法错误：after restart 短语悬垂导致句子结构不完整，应调整语序为 After restart, the device automatically restores the configuration。",
            "severity": "一般"
        }}
    ]
}}
