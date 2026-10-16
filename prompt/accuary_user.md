【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
每条句子包含：单行原文、单行待检译文、该行类型（title=标题，其余=正文）、该行上下文（该句在原文档中的上文/下文邻居句等）、该行检索参考术语（最多5条，可为空，逗号分隔）、该行Top3匹配参考平行语料（最多3条，可为空）
⚠️ 标签铁律：句子中的所有标签/占位标记（如 <b>、<ph>、<xref/>、</b>、<x0/>、<ph0/>、<sub0>…</sub0>）是格式占位符——绝对不检查标签本身、绝对不在 error_desc 中写出任何标签（引用文字时把标签视作不存在，只抄文字）；三个 full_line 字段仍逐字保留标签。禁止「标签丢失/被替换/数量不一致/占位符语义丢失」类判定。
⚠️ 语料铁律：该行Top3语料按内部翻译标准产出、正确率极高——译文与语料一致或相似（含多译法命中任一、片段级译法一致）即大概率正确，不得报错；与语料不一致时把语料当作不存在，按无资料的通用翻译标准正常判定，不得因不一致而怀疑译文；语料只用于判对，不用于报错。
⚠️ 大小写硬性禁令：大小写绝对禁止检查——无论与原文/语料/术语/上下文/标准命名是否一致，大小写永远不是错误，哪怕错了也不报；禁止对大小写做任何判断或比较，error_desc 中禁止出现任何大小写描述。
{sentence_block}

### Few‑Shot 样例：无准确度错误，输出空
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
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

### Few‑Shot 样例：标题精简表达（标题允许省略冠词/虚词，不判漏译）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：基站安装
单行待检译文：Base Station Installation
该行类型：title
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 示例：度量术语译错（长度 → 大小/尺寸）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：该参数的长度固定为 32 位。
单行待检译文：The size of this parameter is fixed at 32 bits.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "该参数的长度固定为 32 位。",
            "target_error_full_line": "The size of this parameter is fixed at 32 bits.",
            "target_correct_full_line": "The length of this parameter is fixed at 32 bits.",
            "error_desc": "1. 度量术语译错：长度（length）被译成 size（大小），length 与 size 不可互换。",
            "severity": "一般"
        }}
    ]
}}

### Few‑Shot 示例：位置限定词/基本术语译错（高 4 位→4 bits、状态位→status ID）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：寄存器的高 4 位为状态位，低 4 位为数据位。
单行待检译文：The 4 bits of the register are the status ID, and the low 4 bits are the data ID.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "寄存器的高 4 位为状态位，低 4 位为数据位。",
            "target_error_full_line": "The 4 bits of the register are the status ID, and the low 4 bits are the data ID.",
            "target_correct_full_line": "The high 4 bits of the register are the status bits, and the low 4 bits are the data bits.",
            "error_desc": "1. 位置限定词丢失：高 4 位（the high 4 bits）被译成 the 4 bits，丢失「高/high」；2. 基本术语译错：状态位/数据位（status/data bits）被译成 status/data ID，bit 与 ID 不可互换。",
            "severity": "一般"
        }}
    ]
}}

### Few‑Shot 示例：主客体颠倒语义偏差（通信设备场景）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：新增 AAU5385d 支持 LNR 频段间深度协同，请参见：
单行待检译文：Added support to L/NR Inter-band Deep Coordination by the AAU5385d. For details, see:
该行类型：p
该行上下文：
该行参考术语：AAU5385d,LNR
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "新增 AAU5385d 支持 LNR 频段间深度协同，请参见：",
            "target_error_full_line": "Added support to L/NR Inter-band Deep Coordination by the AAU5385d. For details, see:",
            "target_correct_full_line": "AAU5385d is newly added to support L/NR inter-band deep coordination. For details, see:",
            "error_desc": "1. 主客体语义颠倒。原文含义：新增AAU5385d设备，该设备具备LNR频段间深度协同支持能力；译文句式结构将AAU5385d变成被动施事方，语义理解为向频段协同能力增加支持，与原意相反。",
            "severity": "严重"
        }}
    ]
}}

### Few‑Shot 示例：标签不检查、error_desc 不带标签（标签内文字错误照常检出）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：该设备支持<ph id='p1'>双频传输</ph>，并支持<ph id='p2'>手动重启</ph>功能。
单行待检译文：This device supports <ph id='p1'>dual-band transmission</ph> and the <ph id='p2'>automatic restart</ph> function.
该行类型：p
该行上下文：上文: 双频传输需配合天线规格使用。
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "该设备支持<ph id='p1'>双频传输</ph>，并支持<ph id='p2'>手动重启</ph>功能。",
            "target_error_full_line": "This device supports <ph id='p1'>dual-band transmission</ph> and the <ph id='p2'>automatic restart</ph> function.",
            "target_correct_full_line": "This device supports <ph id='p1'>dual-band transmission</ph> and the <ph id='p2'>manual restart</ph> function.",
            "error_desc": "1. 语义错译：手动重启被译成 automatic restart（自动重启），与原文语义相反。",
            "severity": "严重"
        }}
    ]
}}

### Few‑Shot 示例：源译文标签形态差异巨大时，只查文字、不比较标签、描述不带标签
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：<ph id="1"/>、<ph id="2"/> 多个元素参数一致
单行待检译文：Multi-group parameter <cmdname id="1">TEST CASE</cmdname>
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：
句子2：
单行原文：<ph id="3"/> 元素参数一致 relativepath01
单行待检译文：<ph id="3"/> element parameters are consistent. testttttt space space
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "<ph id=\"1\"/>、<ph id=\"2\"/> 多个元素参数一致",
            "target_error_full_line": "Multi-group parameter <cmdname id=\"1\">TEST CASE</cmdname>",
            "target_correct_full_line": "The parameters of multiple elements are consistent <cmdname id=\"1\">TEST CASE</cmdname>",
            "error_desc": "1. 语义歪曲：第1句「多个元素参数一致」被译成 Multi-group parameter，丢失「参数一致」的语义。",
            "severity": "一般"
        }},
        {{
            "source_full_line": "<ph id=\"3\"/> 元素参数一致 relativepath01",
            "target_error_full_line": "<ph id=\"3\"/> element parameters are consistent. testttttt space space",
            "target_correct_full_line": "<ph id=\"3\"/> element parameters are consistent. relativepath01",
            "error_desc": "1. 错译：第2句句尾的 relativepath01 被译成 testttttt space space（乱码），与本义不符。",
            "severity": "严重"
        }}
    ]
}}

### Few‑Shot 示例：结构转换不判漏译（名词化融入动词，含跳检上下文）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：公私网 IP 共用模式的选择，主要取决于 SIG 与 NAT 的部署位置关系以及所监控用户分配的 IP 地址类型。
单行待检译文：The public and private IP addresses sharing mode value depends on the deployment relationship between the SIG system and NAT and the type of IP address allocated to monitored users.
该行类型：p
该行上下文：上文: 公私网 IP 共用模式支持多种部署形态。
下文: 监控用户的 IP 地址类型包括私网地址与公网地址。
该行参考术语：SIG,NAT
该行Top3参考平行语料：

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 示例：程度缓和词省略不判漏译（"主要用于"→平铺陈述）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：以太网光接口主要用于百兆、千兆、2.5GE、10GE 光接口业务的接收和发送。
单行待检译文：This Ethernet optical port sends and receives service data at 100 Mbit/s, 1000 Mbit/s, 2.5 Gbit/s, or 10 Gbit/s.
该行类型：p
该行上下文：上文: 以太网光接口支持多种速率。
下文: 光接口的收发模式由单板配置决定。
该行参考术语：2.5GE,10GE
该行Top3参考平行语料：

示例输出：
{{
    "has_error": false,
    "error_list": []
}}
### Few‑Shot 示例：译文与语料逐字一致即判对（告警名为约定译名）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：DNS 服务器信令故障
单行待检译文：All Links Disconnected in a DNS Server
该行类型：title
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "DNS 服务器信令故障", "target": "All Links Disconnected in a DNS Server"}}]

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 示例：语料无先例支持的译法照常判错（语料只用于判对）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：该板卡支持热插拔电源模块。
单行待检译文：This board supports hot standby power modules.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "该板卡支持双电源冗余。", "target": "This board supports dual power redundancy."}}, {{"source": "电源模块支持在线更换。", "target": "The power module supports online replacement."}}]

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "该板卡支持热插拔电源模块。",
            "target_error_full_line": "This board supports hot standby power modules.",
            "target_correct_full_line": "This board supports hot-swappable power modules.",
            "error_desc": "1. 错译：热插拔（hot swap）被译成 hot standby（热备），两者含义不同，且无语料先例支持该译法。",
            "severity": "严重"
        }}
    ]
}}

### Few‑Shot 示例：仅大小写不同不判错（专有帐户名大小写不敏感）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：启用Guest帐户。
单行待检译文：Enable the guest account.
该行类型：p
该行上下文：上文: 按照至的方法停止Symantec Endpoint Protection服务。
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 示例：内容错误不受大小写豁免影响（UI 按钮指向错误照常报）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：单击"停止"停止该服务。
单行待检译文：Click "Start" to stop the service.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "单击\"停止\"停止该服务。",
            "target_error_full_line": "Click \"Start\" to stop the service.",
            "target_correct_full_line": "Click \"Stop\" to stop the service.",
            "error_desc": "1. 错译：第1句句中的UI按钮 停止 被译成 Start，与原文含义相反，会导致读者执行相反操作。",
            "severity": "严重"
        }}
    ]
}}

### Few‑Shot 示例：菜单项大小写不报（不得以"标准命名/找不到选项"变相上报）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：单击网络访问菜单项。
单行待检译文：Click the Network access menu item.
该行类型：p
该行上下文：上文: 在安全选项下的策略项中进行配置。
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 示例：译文与语料不一致但语义正确——按无资料判定，不报
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：风扇转速可调。
单行待检译文：You can adjust the fan speed.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "风扇转速可调。", "target": "The fan speed is adjustable."}}]

示例输出：
{{
    "has_error": false,
    "error_list": []
}}
