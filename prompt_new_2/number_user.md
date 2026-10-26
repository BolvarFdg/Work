【批量待检句对，按文档顺序排列（因跳检未必连续）】
每句含：单行原文、单行待检译文、该行类型（title=标题，其余=正文）、该行上下文（该句在原文档中的上文/下文邻居句，可参考校验数字、单位、规格信息）、该行参考术语（最多5条，可为空）、该行Top3参考平行语料（最多3条，可为空）。

### 示例1：数值等价不报 / 语料一致不报
输入：
句子1：
单行原文：支持3K规格的扩展板，缩放比例为1/10。
单行待检译文：This board supports the 3000-card specification, with a scaling ratio of 0.1-fold.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：
句子2：
单行原文：该系列包括3900型号。
单行待检译文：The series includes the 3,900 model.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：[{{"source": "该系列包括3900型号。", "target": "The series includes the 3,900 model."}}]

输出：
{{
    "has_error": false,
    "error_list": []
}}
（注：句1中 3K=3000、1/10=0.1-fold 均为数值等价；句2与语料逐字一致，判对。）

### 示例2：数值错误 / 术语数字加千位分隔符 / 单位大小写
输入：
句子1：
单行原文：该单板功耗为2.5W。
单行待检译文：The power consumption of this board is 5W.
该行类型：p
该行上下文：
该行参考术语：2.5W
该行Top3参考平行语料：
句子2：
单行原文：系统支持最高1024QAM调制方式。
单行待检译文：The system supports up to 1,024QAM modulation.
该行类型：p
该行上下文：
该行参考术语：1024QAM
该行Top3参考平行语料：
句子3：
单行原文：载波频率配置为10MHz。
单行待检译文：The carrier frequency is configured as 10 mHz.
该行类型：p
该行上下文：
该行参考术语：
该行Top3参考平行语料：

输出：
{{
    "has_error": true,
    "error_list": [
        {{
            "source_full_line": "该单板功耗为2.5W。",
            "target_error_full_line": "The power consumption of this board is 5W.",
            "target_correct_full_line": "The power consumption of this board is 2.5W.",
            "error_desc": "1. 数字错误：功耗 2.5W 被译成 5W。",
            "severity": "严重"
        }},
        {{
            "source_full_line": "系统支持最高1024QAM调制方式。",
            "target_error_full_line": "The system supports up to 1,024QAM modulation.",
            "target_correct_full_line": "The system supports up to 1024QAM modulation.",
            "error_desc": "1. 数字错误：术语 1024QAM 中的数字被加了千位分隔符，应为 1024QAM。",
            "severity": "一般"
        }},
        {{
            "source_full_line": "载波频率配置为10MHz。",
            "target_error_full_line": "The carrier frequency is configured as 10 mHz.",
            "target_correct_full_line": "The carrier frequency is configured as 10 MHz.",
            "error_desc": "1. 单位错误：单位 MHz 被写成 mHz，大小写不一致。",
            "severity": "严重"
        }}
    ]
}}

⚠️ 逐句检查下面每一句，不得跳过；数值等价不报（千分位、前缀换算、互化、进制表达）；标点空格、标签占位符不报；单位大小写属于本模块照报。
{sentence_block}