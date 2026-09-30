#!/usr/bin/env python3
"""XML 内联标签规范化工具类（规则与质检 agent 管线完全一致，直接复用原函数，不复制逻辑）。

管线两步（与 agent 相同）::

    normalize_inline   inline_tag_normalizer.py   标签瘦身：x/空ph/sub/sup 去属性+全局序号；
                                                 ph含文本/其余标签（g/b/bpt/ept/it/非seg的mrk…）
                                                 剥容器留内容
    normalize_text     text_normalizer.py         转义还原（&lt;/&amp;lt;/#lt;/\" → 原字符）、
                                                 带属性标签去属性、处理指令去 data

用法::

    from xml_tag_tool import XmlTagNormalizer

    tool = XmlTagNormalizer()
    tool.normalize('<source>速率为<x id="a"/>。</source>')       # 整段模式：一个字符串进出一个
    tool.normalize_segments(xliff的source片段)                   # 分段模式：mrk 切句（与管线逐字一致）
    tool.explain('...')                                          # 分阶段 + 逐标签对照查看全过程

counter：normalize/explain 可传共享计数器（如 ``[0]``）实现跨调用连续编号，
调用后 ``counter[0]`` = 下一个待用序号；不传则本次独立从 0 开始。

命令行::

    python xml_tag_tool.py '<source>速率为<x id="a"/>。</source>'    # 输出规范化结果
    python xml_tag_tool.py -v '<source>…</source>'                   # 输出全过程明细
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from inline_tag_normalizer import KEEP_PAIRED_TAGS, localname, normalize_inline
from text_normalizer import normalize_text

from dita_xliff_loader import _collect_segments

_XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>")


class XmlTagNormalizer:
    """输入 XML 字符串，输出编好序号的规范化字符串。"""

    def parse_fragment(self, xml_string: str) -> ET.Element:
        """解析 XML 字符串为元素。

        支持带根元素的片段 / 带 XML 声明的片段 / 裸句子（自动包一层 root 再解析）。
        裸句子里若含未声明的命名空间前缀或字面 < > & 仍会失败，抛 ValueError。
        """
        s = _XML_DECL_RE.sub("", xml_string, count=1)
        try:
            return ET.fromstring(s)
        except ET.ParseError:
            try:
                return ET.fromstring(f"<root>{s}</root>")
            except ET.ParseError as e:
                raise ValueError(f"无法解析为 XML: {e}") from e

    def normalize(self, xml_string: str, counter: Optional[List[int]] = None) -> str:
        """整段模式：一个字符串进，一个字符串出。

        等价于管线里「无 mrk 分段」的兜底路径：normalize_inline → strip → normalize_text。
        """
        elem = self.parse_fragment(xml_string)
        stage1 = normalize_inline(elem, counter)
        return normalize_text(stage1.strip())

    def normalize_segments(self, xml_string: str) -> List[str]:
        """分段模式：与 agent 管线（parse_xliff 处理 source/target）逐字一致。

        内部直接走 _collect_segments：<mrk mtype="seg"> 切句、counter 跨段共享、
        无 mrk 整段兜底，再对每段过 normalize_text。
        有分段标记时，mrk 段外的游离文本会被丢弃（与管线行为一致）。
        """
        elem = self.parse_fragment(xml_string)
        return [normalize_text(s) for s in _collect_segments(elem)]

    def explain(self, xml_string: str, counter: Optional[List[int]] = None) -> Dict:
        """查看全过程：两阶段输出、逐标签对照、counter 变化。"""
        my_counter = counter if counter is not None else [0]
        before = my_counter[0]
        elem = self.parse_fragment(xml_string)
        stage1 = normalize_inline(elem, my_counter)
        final = normalize_text(stage1.strip())
        return {
            "input": xml_string,
            "stage1_inline": stage1,
            "stage2_text": final,
            "counter_before": before,
            "counter_after": my_counter[0],
            "tags": self._trace_tags(elem, before),
        }

    def _trace_tags(self, elem: ET.Element, start_n: int) -> List[Dict]:
        """逐标签对照明细（仅展示用：编号判定镜像 normalize_inline 的 walk，结果以原函数为准）。"""
        trace: List[Dict] = []
        n = start_n

        def ser(node: ET.Element) -> str:
            tail, node.tail = node.tail, None
            try:
                return ET.tostring(node, encoding="unicode")
            finally:
                node.tail = tail

        def visit(node: ET.Element) -> None:
            nonlocal n
            ln = localname(node.tag)
            if ln == "x":
                trace.append({"tag": ser(node), "result": f"<x{n}/>", "rule": "占位符：去属性+序号"})
                n += 1
            elif ln == "ph":
                if "".join(node.itertext()).strip():
                    trace.append({"tag": ser(node), "result": "(剥容器，内容保留)", "rule": "ph 含文本"})
                else:
                    trace.append({"tag": ser(node), "result": f"<ph{n}/>", "rule": "空占位符：去属性+序号"})
                    n += 1
            elif ln in KEEP_PAIRED_TAGS:
                trace.append({"tag": ser(node), "result": f"<{ln}{n}>…</{ln}{n}>", "rule": "成对保留：去属性+序号"})
                n += 1
            else:
                trace.append({"tag": ser(node), "result": "(剥标签，内容保留)", "rule": "格式类/其余（含非seg的mrk）"})
            for child in node:
                visit(child)

        for child in elem:
            visit(child)
        return trace


def _print_explain(info: Dict) -> None:
    print("【输入】")
    print(f"  {info['input']}")
    print("【第1步 normalize_inline：标签瘦身 + 编号】")
    print(f"  {info['stage1_inline']}")
    print("【第2步 normalize_text：转义还原 / 去属性 / PI 去data】")
    print(f"  {info['stage2_text']}")
    print(f"【counter】 {info['counter_before']} → {info['counter_after']}")
    print("【逐标签对照】")
    for t in info["tags"]:
        print(f"  {t['tag']}")
        print(f"    → {t['result']}    ({t['rule']})")


def _demo() -> None:
    tool = XmlTagNormalizer()
    sample = (
        '<source>接口<x id="x1" xid="file:///t.dita#p1/x1" ctype="x-other"/>支持'
        '<ph id="p1">&lt;?otherlink[{ID:\'123456\'}]?&gt;</ph>，速率等级<sub id="s1">2</sub>，'
        '功率<ph id="p2"/>，协议版本&amp;lt;v2.0&amp;gt;，<g id="g1">链路聚合</g>功能已<b>启用</b></source>'
    )
    _print_explain(tool.explain(sample))
    print()
    print("【共享 counter 跨调用连续编号】")
    counter = [0]
    print(f"  第1次: {tool.normalize('<s>甲<x id="1"/>乙</s>', counter)}   counter={counter}")
    print(f"  第2次: {tool.normalize('<s>丙<ph id="2"/>丁</s>', counter)}   counter={counter}")
    print()
    print("【分段模式（mrk 切句，与 agent 管线一致）】")
    seg_input = (
        '<source><mrk mtype="seg">速率为<x id="a"/>。</mrk>'
        '<mrk mtype="seg">功率为<ph id="b"/>，CO<sub id="c">2</sub>浓度高。</mrk></source>'
    )
    for s in tool.normalize_segments(seg_input):
        print(f"  {s}")
    print()
    print("【裸句子（无根元素，自动包裹解析）】")
    print(f"  {tool.normalize('速率为<x id="a"/>。')}")

if __name__ == "__main__":
    _args = sys.argv[1:]
    _verbose = "-v" in _args
    _xml = " ".join(a for a in _args if a != "-v")
    if _xml:
        if _verbose:
            _print_explain(XmlTagNormalizer().explain(_xml))
        else:
            print(XmlTagNormalizer().normalize(_xml))
    else:
        _demo()
