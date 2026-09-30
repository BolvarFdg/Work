



## 执行顺序：先串行准备 → 4 个检测 Agent **并行** → 串行汇总

`TranslationQAChecker.check`（agent/base.py:149）的编排逻辑：

```
PrepareAgent.prepare                    ── ① 串行：拼 sentence_block（纯本地，无 LLM 调用）
        │
        ▼
asyncio.gather(                         ── ② 并行：4 个检测 Agent 同时发起 LLM 请求
  AccuracyAgent.check ─┐
  NumberAgent.check    ├─ 4 路 async 并发
  TermAgent.check      │
  SyntaxAgent.check   ─┘
)
        │
        ▼
全部成功？ ──否──► summary 直接标记失败（success=False，                 ── ③ 串行
              error="部分检查失败：accuracy: xxx, ..."）                  不再调 LLM
        │是
        ▼
SummaryAgent.summarize                  ── ④ 串行：汇总校验（第 2 轮 LLM 调用）
```

## 关键细节

**1. 并行的实现方式**（agent/base.py:25-33）：

```python
async def detection(self, system_prompt, user_prompt, temperature=0.0):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: self.detection_client.chat(...))
```

`LLMClient.chat` 是**同步的 `requests.post`**，靠 `run_in_executor` 丢进线程池实现并发——不是真正的异步 HTTP，但 4 路互不阻塞，效果等价。

**2. 失败短路**（agent/base.py:158-165）：4 个检测里**任何一个失败**（LLM 超时/返回空/异常），SummaryAgent 就不执行，整批结果 `success=False`——客户端会把这个批次记入 `failures`（failed.txt），**不会**拿 4 个残缺结果去汇总。但 4 个 Agent 各自的 success/error 仍逐个返回。

**3. 顺序有保证但无依赖**：`asyncio.gather` 按输入顺序返回结果，`results[0..3]` 固定对应 accuracy/number/term/syntax，按此固定顺序传给 SummaryAgent——4 个检测 Agent 之间**没有数据依赖**（共用同一个 sentence_block），纯粹是为了汇总时字段对齐。

**4. 每个批次请求 = 2 轮 LLM 往返**：4 路并行检测（取最慢的）+ 1 次汇总。

**5. 外层还有两层并发叠加**：

```
客户端 ThreadPoolExecutor（MAX_WORKERS=5 个批次并发）
  × FastAPI async 端点（多请求并发处理）
    × 每请求 4 路检测 Agent 并发
```

理论峰值 ≈ 5 批 × 4 Agent = 20 路并发 LLM 请求（汇总轮再 +5）。这也解释了为什么 config 里 `BATCH=5 / MAX_WORKERS=5 / LLM_TIMEOUT=120 / TIMEOUT=600` 的梯度设置——单请求要容忍 2 轮串行 LLM 调用。

## 入口

**服务端**：`python server.py [port] [host]` 启动 FastAPI（默认 `0.0.0.0:8000`，server.py:176）

**质检 HTTP 入口**（server.py:96）：

- `POST /api/v1/check` — 完整结果（4 个 Agent 原始输出 + 汇总）
- `POST /api/v1/check/simple` — 精简版（只返回汇总结果）

**批量客户端**：`check_manual.py` / `eval_planted.py` / `eval_plain_xliff.py`（配置好 `config.py` 的手册列表后运行，内部按 5 句/批并发调上面接口）

## 请求参数（TranslationCheckRequest，server.py:24）

```jsonc
{
  // 三个多行文本：按 \n 拆行后逐行对齐成句对，行数必须一致
  "source_text":  "原文第1句\n原文第2句",        // str，必填，多行
  "target_text":  "译文第1句\n译文第2句",        // str，必填，多行
  "corpus_text":  "语料第1行\n语料第2行",        // str，必填(可空串)，多行；不足行数服务端自动补空

  // 三个可选列表：与 source_text 的行逐一对齐（缺省则不区分）
  "element_tags": ["title", "p"],               // List[str]，每行元素类型
  "context_list": ["章节: xx > yy\n前句: ..."],  // List[str]，每行上下文（可含换行）
  "keywords":     ["10GE,2.5W", ""],            // List[str]，每行参考术语（逗号分隔）

  // 输出控制
  "check_types":      ["accuracy", "number"],   // List[str]，可选，过滤返回的检查类型
                                                 // 可选值: accuracy/number/term/syntax/summary
  "return_details":   true                       // bool，默认 true；false 时只返回汇总
}
```

客户端实际构造方式参考 `eval_base.send_batch`（eval_base.py:102）：把一批 `CheckUnit` 的各字段用 `"\n".join` 拼成多行文本、列表字段按行收集。

## 响应格式

```jsonc
{
  "success": true,
  "message": "检查完成",
  "data": {
    "accuracy": { "content": "{...json...}", "success": true, "error": null },
    "number":   { "content": "...", "success": true, "error": null },
    "term":     { "content": "...", "success": true, "error": null },
    "syntax":   { "content": "...", "success": true, "error": null },
    "summary":  { "content": "...", "success": true, "error": null },
    "success":  true
  }
}
```

`summary.content` 是 JSON 字符串（summary_system.md 定义的 schema）：

```json
{
  "final_has_error": false,
  "error_list": [{
    "source_full_line": "单行原文（逐字保留 <x0/> 等占位符）",
    "target_error_full_line": "单行错误译文",
    "target_correct_full_line": "修正后的单行译文",
    "error_desc": "1.xxx\n2.xxx",
    "severity": "严重|一般",
    "sources": ["accuracy", "number", "term", "syntax"]
  }]
}
```

调用示例：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/check \
  -H "Content-Type: application/json" \
  -d '{
    "source_text": "该设备支持10GE。",
    "target_text": "This device supports 5GE.",
    "corpus_text": "",
    "element_tags": ["p"],
    "keywords": ["10GE"]
  }'


  {
  "source_text": "在配置光接口之前，请确保设备已接地。\n该设备支持10GE光接口，速率为<x0/>。\n最大功率2.5W，工作温度范围为-40°C至+65°C。",
  "target_text": "Before configuring an optical interface, ensure that the device has been grounded.\nThis device supports 10GE optical interfaces, and the rate is <x0/>.\nThe maximum power is 5W, and the operating temperature ranges from -40°C to +65°C.",
  "corpus_text": "[{\"source\": \"配置设备之前，请确保设备已接地。\", \"target\": \"Before configuring the device, ensure that the device has been grounded.\"}, {\"source\": \"请确保设备已连接地线。\", \"target\": \"Ensure that the device is connected to a ground cable.\"}]\n[{\"source\": \"该设备支持10GE光接口。\", \"target\": \"This device supports 10GE optical interfaces.\"}, {\"source\": \"接口速率为10GE。\", \"target\": \"The interface rate is 10GE.\"}, {\"source\": \"该设备支持25GE光接口。\", \"target\": \"This device supports 25GE optical interfaces.\"}]\n[{\"source\": \"最大功率2.5W。\", \"target\": \"The maximum power is 2.5W.\"}, {\"source\": \"工作温度范围为-40°C至+65°C。\", \"target\": \"The operating temperature ranges from -40°C to +65°C.\"}]",
  "element_tags": [
    "p",
    "p",
    "p"
  ],
  "context_list": [
    "章节: 接口配置指南 > 光接口规格\n相邻: 该设备支持10GE光接口，速率为<x0/>。\n前段末句: 光接口规格\n后段首句: 该设备支持10GE光接口，速率为<x0/>。",
    "章节: 接口配置指南 > 光接口规格\n相邻: 在配置光接口之前，请确保设备已接地。 | 最大功率2.5W，工作温度范围为-40°C至+65°C。\n前段末句: 在配置光接口之前，请确保设备已接地。\n后段首句: 最大功率2.5W，工作温度范围为-40°C至+65°C。",
    "章节: 接口配置指南 > 光接口规格\n相邻: 该设备支持10GE光接口，速率为<x0/>。 | 更多参数请参见附录。\n前段末句: 该设备支持10GE光接口，速率为<x0/>。\n后段首句: 更多参数请参见附录。"
  ],
  "keywords": [
    "",
    "10GE",
    "2.5W"
  ],
  "return_details": true
}



element_tags:  title | <任意DITA标签名> | ""        （行为二分：title / 非title）

context_list:  章节: <标题路径, " > " 连接>
               相邻: <兄弟段落, " | " 连接>          ┐ 仅 DITA 流程
               前段末句: <跨段前句原文>              ┘
               前句: <同段/跨文件前句原文>
               后句: <同段/跨文件后句原文>
               后段首句: <跨段后句原文>              ┐ 仅 DITA 流程
               "" （无任何上下文）
```
