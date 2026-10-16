【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验术语、缩写、设备型号一致性】
每条句子包含：单行原文、单行待检译文、该行类型（title=标题，其余=正文）、该行上下文（该句在原文档中的上文/下文邻居句等）、该行检索参考术语（最多5条，可为空，逗号分隔）、该行Top3匹配参考平行语料（最多3条，可为空）

### Few‑Shot 样例：无术语错误，输出空
示例输入：
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

### Few‑Shot 示例：语料多译法命中任一即判对
示例输入：
句子1：
单行原文：立即升级：系统会立即升级您的数据库内核版本到当前最新版本。
单行待检译文：<b id="1">Upon submission</b>: The system upgrades the minor version immediately after you submit the upgrade request.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "立即升级：系统会立即升级您的数据库内核版本到当前最新版本。", "target": "<b>Upon submission</b>: The system upgrades the kernel version immediately after you submit the upgrade request."}}, {{"source": "立即升级：系统会立即升级您的数据库内核版本到当前最新版本。", "target": "<b>Upon submission</b>: The system upgrades the minor version immediately after your submission of the upgrade request."}}]

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 示例：标签不检查，只查文字
示例输入：
句子1：
单行原文：该单板提供<ph id='t1'>时钟同步</ph>功能。
单行待检译文：This board provides the <ph id='t1'>timing alignment</ph> function.
该行类型：p
该行上下文：
该行参考术语：时钟同步,clock synchronization
该行Top3参考平行语料：

句子2：
单行原文：<i id="1"><b id="2">DlExit256QamCqiTblTbsThld</b></i> 参数用于配置信道质量指示。
单行待检译文：The DlExit256QamCqiTblTbsThld parameter is used to configure the channel quality indicator.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "该单板提供<ph id='t1'>时钟同步</ph>功能。",
            "target_error_full_line": "This board provides the <ph id='t1'>timing alignment</ph> function.",
            "target_correct_full_line": "This board provides the <ph id='t1'>clock synchronization</ph> function.",
            "error_desc": "1. 术语译错：时钟同步被译成 timing alignment，应为 clock synchronization。",
            "severity": "一般"
        }}
    ]
}}

### Few‑Shot 示例：大小写不报，无先例真错照报
示例输入：
句子1：
单行原文：IP 地址
单行待检译文：IP Address
该行类型：title
该行上下文：
该行参考术语：
该行Top3参考平行语料：
句子2：
单行原文：配置TDM-Pattern参数。
单行待检译文：Configure the TDM pattern parameters.
该行类型：p
该行上下文：
该行参考术语：TDM-Pattern
该行Top3参考平行语料：
句子3：
单行原文：启用Guest帐户。
单行待检译文：Enable the guest account.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：
句子4：
单行原文：该特性依赖NTP时钟同步功能。
单行待检译文：This feature relies on the GPS time synchronization function.
该行类型：p
该行上下文：
该行参考术语：NTP
该行Top3参考平行语料：[{{"source": "该特性依赖NTP时钟同步功能。", "target": "This feature relies on the NTP time synchronization function."}}]

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "该特性依赖NTP时钟同步功能。",
            "target_error_full_line": "This feature relies on the GPS time synchronization function.",
            "target_correct_full_line": "This feature relies on the NTP time synchronization function.",
            "error_desc": "1. 术语译错：NTP 被译成 GPS，应为 NTP。",
            "severity": "严重"
        }}
    ]
}}

⚠️ 禁止检查：标点空格、标签/占位符、单词大小写——任何情况不报；error_desc 直接写错误（哪里错、应为什么），禁止引用来源与禁止项内容。
{sentence_block}