【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）；每句的「该行上下文」=该句在原文档中的上文/下文邻居句等，可参考校验语义与业务逻辑】
每条句子包含：单行原文、单行待检译文、该行类型（title=标题，其余=正文）、该行上下文（该句在原文档中的上文/下文邻居句等）、该行检索参考术语（最多5条，可为空，逗号分隔）、该行Top3匹配参考平行语料（最多3条，可为空）

### Few‑Shot 1：无错误（含结构转换、缓和词省略、数值等价、CLI命令行）
示例输入：
句子1：
单行原文：该设备支持双频Wi-Fi传输。
单行待检译文：This device supports dual-band Wi-Fi transmission.
该行类型：p
该行上下文：
该行参考术语：Wi-Fi
该行Top3参考平行语料：
句子2：
单行原文：公私网 IP 共用模式的选择，主要取决于 SIG 与 NAT 的部署位置关系。
单行待检译文：The public and private IP addresses sharing mode value depends on the deployment relationship between the SIG system and NAT.
该行类型：p
该行上下文：
该行参考术语：SIG,NAT
该行Top3参考平行语料：
句子3：
单行原文：以太网光接口主要用于百兆、千兆、2.5GE、10GE 光接口业务的接收和发送。
单行待检译文：This Ethernet optical port sends and receives service data at 100 Mbit/s, 1000 Mbit/s, 2.5 Gbit/s, or 10 Gbit/s.
该行类型：p
该行上下文：
该行参考术语：2.5GE,10GE
该行Top3参考平行语料：
句子4：
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

### Few‑Shot 2：标签不检查，只查文字（含形态差异巨大）
示例输入：
句子1：
单行原文：该单板提供<ph id='t1'>时钟同步</ph>功能。
单行待检译文：This board provides the <ph id='t1'>timing alignment</ph> function.
该行类型：p
该行上下文：
该行参考术语：时钟同步,clock synchronization
该行Top3参考平行语料：
句子2：
单行原文：<ph id="1"/>、<ph id="2"/> 多个元素参数一致
单行待检译文：Multi-group parameter <cmdname id="1">TEST CASE</cmdname>
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：
句子3：
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
            "source_full_line": "该单板提供<ph id='t1'>时钟同步</ph>功能。",
            "target_error_full_line": "This board provides the <ph id='t1'>timing alignment</ph> function.",
            "target_correct_full_line": "This board provides the <ph id='t1'>clock synchronization</ph> function.",
            "error_desc": "1. 错译：时钟同步被译成 timing alignment，应为 clock synchronization。",
            "severity": "一般"
        }},
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

### Few‑Shot 3：语料三态（命中豁免 / 不一致作废 / 无先例真错照报 / 高度相似仍报漏译）
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
句子4：
单行原文：（可选）辅电测量装置接在DTS柜侧
单行待检译文：The auxiliary power measurement device is connected to the DTS.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "（可选）辅电测量装置接在DTS柜侧", "target": "(Optional) The auxiliary power measurement device is connected to the DTS."}}]

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
        }},
        {{
            "source_full_line": "（可选）辅电测量装置接在DTS柜侧",
            "target_error_full_line": "The auxiliary power measurement device is connected to the DTS.",
            "target_correct_full_line": "(Optional) The auxiliary power measurement device is connected to the DTS.",
            "error_desc": "1. 漏译：（可选）在译文中缺失，应为 (Optional)。",
            "severity": "一般"
        }}
    ]
}}

### Few‑Shot 4：度量术语与位置限定词译错（照常报）
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

### Few‑Shot 5：大小写不报 + 残留词增译照报
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
句子3：
单行原文：能够清晰描述利用哪些HIS平台服务和能力，解决过什么样问题。
单行待检译文：Be able to clearly and easily describe the HIS platform services and capabilities used and what issues have been addressed.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "能够清晰描述利用哪些HIS平台服务和能力，解决过什么样问题。", "target": "Be able to clearly describe the HIS platform services and capabilities used and what issues have been addressed."}}]
句子4：
单行原文：1、iBMC版本低于5.70且CPLD版本低于4.00版本
单行待检译文：1. Note that the iBMC version is earlier than 5.70 and the CPLD version is earlier than 4.00.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "1、iBMC版本低于5.70且CPLD版本低于4.00版本", "target": "1. The iBMC version is earlier than 5.70 and the CPLD version is earlier than 4.00."}}]

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
        }},
        {{
            "source_full_line": "能够清晰描述利用哪些HIS平台服务和能力，解决过什么样问题。",
            "target_error_full_line": "Be able to clearly and easily describe the HIS platform services and capabilities used and what issues have been addressed.",
            "target_correct_full_line": "Be able to clearly describe the HIS platform services and capabilities used and what issues have been addressed.",
            "error_desc": "1. 增译：and easily 在原文中无来源。",
            "severity": "一般"
        }},
        {{
            "source_full_line": "1、iBMC版本低于5.70且CPLD版本低于4.00版本",
            "target_error_full_line": "1. Note that the iBMC version is earlier than 5.70 and the CPLD version is earlier than 4.00.",
            "target_correct_full_line": "1. The iBMC version is earlier than 5.70 and the CPLD version is earlier than 4.00.",
            "error_desc": "1. 增译：Note that 在原文中无来源。",
            "severity": "一般"
        }}
    ]
}}

### Few‑Shot 6：修正译文只改错误点（最小修改，禁止参照批内句子）
示例输入：
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

⚠️ 禁止检查：标点空格、标签/占位符、单词大小写——任何情况不报；error_desc 直接写错误（哪里错、应为什么），禁止引用来源与禁止项内容。
{sentence_block}