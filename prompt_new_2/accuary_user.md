【批量待检句对，按文档顺序排列（因跳检未必连续）】
每句含：单行原文、单行待检译文、该行类型（title=标题，其余=正文）、该行上下文（该句在原文档中的上文/下文邻居句，可参考校验语义与业务逻辑）、该行参考术语（最多5条，可为空）、该行Top3参考平行语料（最多3条，可为空）。

### 示例1：无错误（结构转换、语料仅措辞不同、术语问题不归本模块）
输入：
句子1：
单行原文：公私网 IP 共用模式的选择，主要取决于 SIG 与 NAT 的部署位置关系。
单行待检译文：The public and private IP addresses sharing mode value depends on the deployment relationship between the SIG system and NAT.
该行类型：p
该行上下文：
该行参考术语：SIG,NAT
该行Top3参考平行语料：
句子2：
单行原文：风扇转速可调。
单行待检译文：You can adjust the fan speed.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "风扇转速可调。", "target": "The fan speed is adjustable."}}]
句子3：
单行原文：该单板提供<ph id='t1'>时钟同步</ph>功能。
单行待检译文：This board provides the <ph id='t1'>timing alignment</ph> function.
该行类型：p
该行上下文：
该行参考术语：时钟同步,clock synchronization
该行Top3参考平行语料：

输出：
{{
    "has_error": false,
    "error_list": []
}}
（注：句1为结构转换与缓和词省略；句2与语料仅措辞不同；句3属术语译法错误，归术语模块，本模块不报。）

### 示例2：错译 / 漏译 / 增译
输入：
句子1：
单行原文：单击"停止"停止该服务。
单行待检译文：Click "Start" to stop the service.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：
句子2：
单行原文：（可选）辅电测量装置接在DTS柜侧
单行待检译文：The auxiliary power measurement device is connected to the DTS.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "（可选）辅电测量装置接在DTS柜侧", "target": "(Optional) The auxiliary power measurement device is connected to the DTS."}}]
句子3：
单行原文：1、iBMC版本低于5.70且CPLD版本低于4.00版本
单行待检译文：1. Note that the iBMC version is earlier than 5.70 and the CPLD version is earlier than 4.00.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "1、iBMC版本低于5.70且CPLD版本低于4.00版本", "target": "1. The iBMC version is earlier than 5.70 and the CPLD version is earlier than 4.00."}}]

输出：
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
            "source_full_line": "（可选）辅电测量装置接在DTS柜侧",
            "target_error_full_line": "The auxiliary power measurement device is connected to the DTS.",
            "target_correct_full_line": "(Optional) The auxiliary power measurement device is connected to the DTS.",
            "error_desc": "1. 漏译：（可选）在译文中缺失，应为 (Optional)。",
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

⚠️ 逐句检查下面每一句，不得跳过；只报语义四类错误（错译/漏译/增译/逻辑）；标点空格、标签占位符、大小写写法、数字单位、术语译法不报；修正只改错误点。
{sentence_block}