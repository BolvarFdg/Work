【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）】
每条句子包含：单行原文、单行待检译文、该行类型（title=标题，其余=正文）、该行上下文、该行参考术语（最多5条，可为空）、该行Top3参考平行语料（最多3条，可为空）。
逐句独立检查：术语、型号、缩写、专有名词、协议名称的译法；语义和数字问题归对应模块。

### 示例1：无术语错误（大小写/写法差异不报、语料多译法命中任一即对）
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

### 示例2：术语错译 / 缩写被替换 / 近义术语不精确
示例输入：
句子1：
单行原文：该单板提供<ph id='t1'>时钟同步</ph>功能。
单行待检译文：This board provides the <ph id='t1'>timing alignment</ph> function.
该行类型：p
该行上下文：
该行参考术语：时钟同步,clock synchronization
该行Top3参考平行语料：
句子2：
单行原文：该特性依赖NTP时钟同步功能。
单行待检译文：This feature relies on the GPS time synchronization function.
该行类型：p
该行上下文：
该行参考术语：NTP
该行Top3参考平行语料：[{{"source": "该特性依赖NTP时钟同步功能。", "target": "This feature relies on the NTP time synchronization function."}}]
句子3：
单行原文：两台OSPF路由设备在二层相邻，并不意味着它们一定能够建立邻接关系。
单行待检译文：two OSPF devices that are Layer 2 neighbors may not necessarily establish a neighbor relationship.
该行类型：p
该行上下文：
该行参考术语：OSPF,邻接关系,adjacency
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
        }},
        {{
            "source_full_line": "该特性依赖NTP时钟同步功能。",
            "target_error_full_line": "This feature relies on the GPS time synchronization function.",
            "target_correct_full_line": "This feature relies on the NTP time synchronization function.",
            "error_desc": "1. 术语译错：NTP 被译成 GPS，应为 NTP。",
            "severity": "严重"
        }},
        {{
            "source_full_line": "两台OSPF路由设备在二层相邻，并不意味着它们一定能够建立邻接关系。",
            "target_error_full_line": "two OSPF devices that are Layer 2 neighbors may not necessarily establish a neighbor relationship.",
            "target_correct_full_line": "two OSPF devices that are Layer 2 neighbors may not necessarily establish an adjacency.",
            "error_desc": "1. 术语译错：邻接关系应为 adjacency（OSPF 术语，与 neighbor 是不同概念），译文用了 neighbor relationship。",
            "severity": "一般"
        }}
    ]
}}

⚠️ 逐句检查下列每一句，禁止跳过；只查术语/型号/缩写/专有名词译法；标点空格、标签占位符、大小写写法不报；语义错译归准确度模块、数字单位归数字模块；修正只改错误术语。
{sentence_block}
