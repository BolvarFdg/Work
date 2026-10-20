【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
每条句子包含：单行原文、单行待检译文、该行类型（title=标题，其余=正文）、该行上下文（该句在原文档中的上文/下文邻居句等）、该行检索参考术语（最多5条，可为空，逗号分隔）、该行Top3匹配参考平行语料（最多3条，可为空）

### Few‑Shot 样例：无错误，输出空
示例输入：
句子1：
单行原文：该设备支持双频Wi-Fi传输。
单行待检译文：This device supports dual-band Wi-Fi transmission.
该行类型：p
该行上下文：
该行参考术语：Wi-Fi
该行Top3参考平行语料：
句子2：
单行原文：该功能支持1/10缩放。
单行待检译文：This function supports 0.1-fold scaling.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：
句子3：
单行原文：description TO-[对端设备]- 端口编号 - 端口带宽 // 配置端口描述
单行待检译文：description TO-[peer device]-port number-port bandwidth //Configure an interface description.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 示例：度量术语与位置限定词译错（照常报）
示例输入：
句子1：
单行原文：该参数的长度固定为 32 位。
单行待检译文：The size of this parameter is fixed at 32 bits.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：
句子2：
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
            "source_full_line": "该参数的长度固定为 32 位。",
            "target_error_full_line": "The size of this parameter is fixed at 32 bits.",
            "target_correct_full_line": "The length of this parameter is fixed at 32 bits.",
            "error_desc": "1. 度量术语译错：长度被译成 size，应为 length。",
            "severity": "一般"
        }},
        {{
            "source_full_line": "寄存器的高 4 位为状态位，低 4 位为数据位。",
            "target_error_full_line": "The 4 bits of the register are the status ID, and the low 4 bits are the data ID.",
            "target_correct_full_line": "The high 4 bits of the register are the status bits, and the low 4 bits are the data bits.",
            "error_desc": "1. 位置限定词丢失：高4位被译成 the 4 bits，应为 the high 4 bits；2. 基本术语译错：状态位被译成 status ID，应为 status bits。",
            "severity": "一般"
        }}
    ]
}}

### Few‑Shot 示例：结构转换与缓和词不判漏译
示例输入：
句子1：
单行原文：公私网 IP 共用模式的选择，主要取决于 SIG 与 NAT 的部署位置关系。
单行待检译文：The public and private IP addresses sharing mode value depends on the deployment relationship between the SIG system and NAT.
该行类型：p
该行上下文：上文: 公私网 IP 共用模式支持多种部署形态。
该行参考术语：SIG,NAT
该行Top3参考平行语料：
句子2：
单行原文：以太网光接口主要用于百兆、千兆、2.5GE、10GE 光接口业务的接收和发送。
单行待检译文：This Ethernet optical port sends and receives service data at 100 Mbit/s, 1000 Mbit/s, 2.5 Gbit/s, or 10 Gbit/s.
该行类型：p
该行上下文：
该行参考术语：2.5GE,10GE
该行Top3参考平行语料：

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### Few‑Shot 示例：标签不检查，只查文字
示例输入：
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
            "error_desc": "1. 语义歪曲：多个元素参数一致被译成 Multi-group parameter，丢失参数一致的语义。",
            "severity": "一般"
        }},
        {{
            "source_full_line": "<ph id=\"3\"/> 元素参数一致 relativepath01",
            "target_error_full_line": "<ph id=\"3\"/> element parameters are consistent. testttttt space space",
            "target_correct_full_line": "<ph id=\"3\"/> element parameters are consistent. relativepath01",
            "error_desc": "1. 错译：relativepath01 被译成 testttttt space space，应为 relativepath01。",
            "severity": "严重"
        }}
    ]
}}

### Few‑Shot 示例：语料命中豁免、不一致作废、无先例真错照报
示例输入：
句子1：
单行原文：DNS 服务器信令故障
单行待检译文：All Links Disconnected in a DNS Server
该行类型：title
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "DNS 服务器信令故障", "target": "All Links Disconnected in a DNS Server"}}]
句子2：
单行原文：风扇转速可调。
单行待检译文：You can adjust the fan speed.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "风扇转速可调。", "target": "The fan speed is adjustable."}}]
句子3：
单行原文：该板卡支持热插拔电源模块。
单行待检译文：This board supports hot standby power modules.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "该板卡支持双电源冗余。", "target": "This board supports dual power redundancy."}}]

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "该板卡支持热插拔电源模块。",
            "target_error_full_line": "This board supports hot standby power modules.",
            "target_correct_full_line": "This board supports hot-swappable power modules.",
            "error_desc": "1. 错译：热插拔被译成 hot standby，应为 hot-swappable。",
            "severity": "严重"
        }}
    ]
}}

### Few‑Shot 示例：大小写不报，内容错误照报
示例输入：
句子1：
单行原文：启用Guest帐户。
单行待检译文：Enable the guest account.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：
句子2：
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
            "error_desc": "1. 错译：UI按钮 停止 被译成 Start，应为 Stop。",
            "severity": "严重"
        }}
    ]
}}

⚠️ 禁止检查：标点空格、标签/占位符、单词大小写——任何情况不报；error_desc 直接写错误（哪里错、应为什么），禁止引用来源与禁止项内容。
{sentence_block}
### Few‑Shot 示例：修正译文只改错误点，禁止参照批内其他句子改写句式
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：显示静态认证在线用户信息。
单行待检译文：The information about online iPush users is displayed.
该行类型：p
该行上下文：下文: Displays information about online Portal authentication users.
该行参考术语：
该行Top3参考平行语料：
句子2：
单行原文：显示Portal认证在线用户信息。
单行待检译文：Displays information about online Portal authentication users.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "显示静态认证在线用户信息。",
            "target_error_full_line": "The information about online iPush users is displayed.",
            "target_correct_full_line": "The information about online static authentication users is displayed.",
            "error_desc": "1. 错译：静态认证被译成 iPush，应为 static authentication。",
            "severity": "严重"
        }}
    ]
}}

### Few‑Shot 示例：修正译文必须体现 error_desc 的修正（报错必改，修正≠原文）
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：定制批配置采集表。
单行待检译文：Customize a summary data file for batch configuration.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "定制批配置采集表。",
            "target_error_full_line": "Customize a summary data file for batch configuration.",
            "target_correct_full_line": "Customize a collection table for batch configuration.",
            "error_desc": "1. 术语译错：采集表被译成 summary data file，应为 collection table。",
            "severity": "一般"
        }}
    ]
}}

### Few‑Shot 示例：译文与语料高度相似但缺少内容——仍报漏译
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：因此，对于电信云未来长期演进的场景，如何提高管理架构中的功能交互简易性和可扩展性是亟需解决的问题。
单行待检译文：Therefore, in a long-term evolution scenario in the future, how to improve function interaction simplicity and scalability in a management architecture is an urgent problem to be resolved.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "因此，对于电信云未来长期演进的场景，如何提高管理架构中的功能交互简易性和可扩展性是亟需解决的问题。", "target": "Therefore, in a long-term evolution scenario of the telco cloud in the future, how to improve function interaction simplicity and scalability in a management architecture is an urgent problem to be resolved."}}]

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "因此，对于电信云未来长期演进的场景，如何提高管理架构中的功能交互简易性和可扩展性是亟需解决的问题。",
            "target_error_full_line": "Therefore, in a long-term evolution scenario in the future, how to improve function interaction simplicity and scalability in a management architecture is an urgent problem to be resolved.",
            "target_correct_full_line": "Therefore, in a long-term evolution scenario of the telco cloud in the future, how to improve function interaction simplicity and scalability in a management architecture is an urgent problem to be resolved.",
            "error_desc": "1. 漏译：电信云在译文中缺失，应为 of the telco cloud。",
            "severity": "一般"
        }}
    ]
}}

### Few‑Shot 示例：反向溯源——译文中多出原文没有的内容，照报增译
示例输入：
【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
句子1：
单行原文：工单处理
单行待检译文：FO Copilot > Ticket processing
该行类型：title
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "工单处理", "target": "Ticket Processing"}}]

示例输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "工单处理",
            "target_error_full_line": "FO Copilot > Ticket processing",
            "target_correct_full_line": "Ticket processing",
            "error_desc": "1. 增译：FO Copilot > 在原文中无来源。",
            "severity": "一般"
        }}
    ]
}}
