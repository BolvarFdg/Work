【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验术语、缩写、设备型号一致性】
每条句子包含：单行原文、单行待检译文、该行类型（title=标题，其余=正文）、该行上下文（该句在原文档中的上文/下文邻居句等）、该行检索参考术语（最多5条，可为空，逗号分隔）、该行Top3匹配参考平行语料（最多3条，可为空）
⚠️ 标签铁律：句子中的所有标签/占位标记（如 <b>、<ph>、<xref/>、</b>、<x0/>、<ph0/>、<sub0>…</sub0>）是格式占位符——绝对不检查标签本身、绝对不在 error_desc 中写出任何标签（引用文字时把标签视作不存在，只抄文字）；三个 full_line 字段仍逐字保留标签。
⚠️ 语料铁律：该行Top3语料按内部翻译标准产出、正确率极高——译文与语料一致或相似（含多译法命中任一、片段级译法一致）即大概率正确，不得报错；语料只用于判对，不用于报错。
⚠️ 大小写硬性禁令：大小写绝对禁止检查——无论与原文/语料/术语/上下文/标准命名是否一致，大小写永远不是错误，哪怕错了也不报；禁止对大小写做任何判断或比较，error_desc 中禁止出现任何大小写描述。
{sentence_block}

### Few‑Shot 样例：无术语错误，输出空
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验术语、缩写、设备型号一致性】
句子1：
单行原文：该AAU支持LNR频段协同。
单行待检译文：This AAU supports LNR band coordination.
该行类型：p
该行上下文：
该行参考术语：AAU,LNR
该行Top3参考平行语料：

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 示例：术语译法错误
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验术语、缩写、设备型号一致性】
句子1：
单行原文：设备支持SFP+光口。
单行待检译文：The device supports SFP optical port.
该行类型：p
该行上下文：
该行参考术语：SFP+
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "设备支持SFP+光口。",
            "target_error_full_line": "The device supports SFP optical port.",
            "target_correct_full_line": "The device supports SFP+ optical port.",
            "error_desc": "1. 术语型号缩写译错：SFP 应为 SFP+（丢失加号）。",
            "severity": "一般"
        }}
    ]
}}

### Few‑Shot 示例：标签不检查、error_desc 不带标签（标签内文字错误照常检出）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验术语、缩写、设备型号一致性】
句子1：
单行原文：该单板提供<ph id='t1'>时钟同步</ph>功能。
单行待检译文：This board provides the <ph id='t1'>timing alignment</ph> function.
该行类型：p
该行上下文：
该行参考术语：时钟同步,clock synchronization
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "该单板提供<ph id='t1'>时钟同步</ph>功能。",
            "target_error_full_line": "This board provides the <ph id='t1'>timing alignment</ph> function.",
            "target_correct_full_line": "This board provides the <ph id='t1'>clock synchronization</ph> function.",
            "error_desc": "1. 术语译错：时钟同步应译为 clock synchronization，译文译成 timing alignment。",
            "severity": "一般"
        }}
    ]
}}
### Few‑Shot 示例：语料多译法命中任一即判对
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验术语、缩写、设备型号一致性】
句子1：
单行原文：立即升级：系统会立即升级您的数据库内核版本到当前最新版本。
单行待检译文：<b id="1">Upon submission</b>: The system upgrades the minor version immediately after you submit the upgrade request.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "立即升级：系统会立即升级您的数据库内核版本到当前最新版本。", "target": "<b>Upon submission</b>: The system upgrades the kernel version immediately after you submit the upgrade request."}}, {{"source": "立即升级：系统会立即升级您的数据库内核版本到当前最新版本。", "target": "<b>Upon submission</b>: The system upgrades the minor version immediately after your submission of the upgrade request."}}, {{"source": "立即升级：系统会立即升级您的数据库内核版本到当前最新版本。", "target": "<b>Upon submission</b>: The system upgrades the minor version immediately after you have submitted your upgrade request."}}]

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 示例：语料先例均不支持该译法时照常判术语错
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验术语、缩写、设备型号一致性】
句子1：
单行原文：该特性依赖NTP时钟同步功能。
单行待检译文：This feature relies on the GPS time synchronization function.
该行类型：p
该行上下文：
该行参考术语：NTP
该行Top3参考平行语料：[{{"source": "该特性依赖NTP时钟同步功能。", "target": "This feature relies on the NTP time synchronization function."}}, {{"source": "NTP时钟同步的精度为毫秒级。", "target": "The precision of NTP time synchronization is at the millisecond level."}}]

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "该特性依赖NTP时钟同步功能。",
            "target_error_full_line": "This feature relies on the GPS time synchronization function.",
            "target_correct_full_line": "This feature relies on the NTP time synchronization function.",
            "error_desc": "1. 术语译错：NTP 被译成 GPS，两者是不同的协议/系统，且无语料先例支持该译法。",
            "severity": "严重"
        }}
    ]
}}

### Few‑Shot 示例：术语仅大小写不同不算前后不一致
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验术语、缩写、设备型号一致性】
句子1：
单行原文：该设备支持WLAN功能。
单行待检译文：This device supports WLAN functions.
该行类型：p
该行上下文：
该行参考术语：WLAN
该行Top3参考平行语料：
句子2：
单行原文：配置WLAN参数。
单行待检译文：Configure the wlan parameters.
该行类型：p
该行上下文：
该行参考术语：WLAN
该行Top3参考平行语料：

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 示例：术语前后仅大小写不同不算不一致（忽略大小写比对）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验术语、缩写、设备型号一致性】
句子1：
单行原文：IP 地址
单行待检译文：IP Address
该行类型：title
该行上下文：
该行参考术语：
该行Top3参考平行语料：
句子2：
单行原文：配置IP地址。
单行待检译文：Configure the IP address.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": false,
    "error_list": []
}}
