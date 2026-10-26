【批量待检句子列表，按文档先后顺序排列（因跳检未必连续）】
每条句子包含：单行原文、单行待检译文、该行类型（title=标题，其余=正文）、该行上下文、该行参考术语（最多5条，可为空）、该行Top3参考平行语料（最多3条，可为空）。
逐句独立检查：错译、漏译、增译、逻辑错误；术语、数字问题归对应模块。

### 示例1：无错误（结构转换 / 缓和词省略 / 仅措辞不同 / 术语问题不归本模块）
示例输入：
句子1：
单行原文：公私网 IP 共用模式的选择，主要取决于 SIG 与 NAT 的部署位置关系。
单行待检译文：The public and private IP addresses sharing mode depends on the deployment relationship between the SIG system and NAT.
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

示例输出：
{{
    "has_error": false,
    "error_list": []
}}

### 示例2：错译 / 漏译 / 增译（逐句独立判定，最小修正）
示例输入：
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
单行原文：具体分为以下两个步骤，
单行待检译文：The procedure is as follows:
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
        }},
        {{
            "source_full_line": "（可选）辅电测量装置接在DTS柜侧",
            "target_error_full_line": "The auxiliary power measurement device is connected to the DTS.",
            "target_correct_full_line": "(Optional) The auxiliary power measurement device is connected to the DTS.",
            "error_desc": "1. 漏译：（可选）在译文中缺失，应为 (Optional)。",
            "severity": "一般"
        }},
        {{
            "source_full_line": "具体分为以下两个步骤，",
            "target_error_full_line": "The procedure is as follows:",
            "target_correct_full_line": "The procedure is divided into the following two steps:",
            "error_desc": "1. 漏译：数量词 两个 缺失，应为 two steps。",
            "severity": "一般"
        }}
    ]
}}

⚠️ 逐句检查下列每一句，禁止跳过；只报错译/漏译/增译/逻辑错误；标点空格、标签占位符、大小写写法不报；数字归数字模块、术语选词归术语模块；修正只改错误点。
{sentence_block}
