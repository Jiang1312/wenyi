# Translate Agent Loop 与固定 Pipeline 对比实验说明

## 1. 实验目的

本实验比较两种长篇翻译流程：

1. Translate Agent Loop：模型在有界循环内翻译当前 batch，并按需维护章节记忆和术语；
2. 固定 Pipeline：每个 batch 依次执行正式 Wenyi 的 Translator、Polisher 和
   GlossaryExtractor。

实验主要观察运行时间、Token usage、缓存命中、估算费用、最终术语表和逐 segment 译文。
它是一次探索性架构实验，不是译文质量基准测试。

## 2. 测试数据

测试文本来自：

```text
Alexei Yurchak
Everything Was Forever, Until It Was No More
Late Socialism: An Eternal State
```

相关文件：

- `fixtures/sample_texts.md`：原始采样文本；
- `fixtures/test_chapter.json`：实际运行输入。

fixture 已预先切分，不在运行时重新解析或分段：

- 13 个连续 batch；
- 97 个 segment；
- 每个 batch 约 500–1,800 个英文词；
- 初始章节摘要为空；
- 初始术语为 `performative → 述行性`；
- 风格要求为社会科学学术风格；
- fixture 提供固定的全书概览。

## 3. 公共条件

| 项目 | 设置 |
|---|---|
| 模型 | DeepSeek V4 Flash |
| API Base | `https://api.deepseek.com` |
| 源语言 | 英语 |
| 目标语言 | 中文 |
| 原文与 batch 划分 | 相同 fixture |
| 初始术语、风格和全书概览 | 相同 fixture |
| Review | 不包含 |
| Back Translation | 不包含 |

本实验控制了模型和业务输入，但不是逐 Prompt 完全相同的测试。两套流程使用不同的 Prompt、
上下文组织和模型调用协议；这些差异正是被比较的流程设计的一部分。

## 4. Agent Loop 设置

Agent 侧通过 LiteLLM 调用：

```text
deepseek/deepseek-v4-flash
```

Agent runner 没有显式传入 thinking 开关，使用 LiteLLM 和 DeepSeek 对该模型的请求默认
行为；实际 trace 中包含 reasoning 内容。Pipeline 侧则显式开启 Translator、Polisher 的
thinking，并关闭 GlossaryExtractor 的 thinking。因此两侧使用相同模型，但推理配置不是
严格一致的单变量控制。

每个 batch 创建一次独立 Agent Loop。输入为 `TranslationBatchInput`：

```text
sources
glossary_terms
style
context
book_synopsis
chapter_digest
```

模型看到的 source 使用从 1 开始的显式 `segment_number`；业务对象内部仍为有序字符串
列表。

Agent 可以调用：

- `save_draft`
- `modify_draft`
- `update_chapter_digest`
- `add_glossary_terms`
- `raise_question`
- `submit_translation`

最大模型轮数和 Tool 调用数均为 20。当前 batch 使用独立 working state，只有
`submit_translation` 成功后才把章节摘要和术语提交到全局 `TranslationState`。

后续 batch 会读取最新章节摘要，并从完整术语状态中筛选与当前原文相关的术语。筛选使用
RapidFuzz `partial_ratio`，阈值为 80。fixture 的局部 `context` 为空，Agent 侧没有额外
注入滚动译文尾段。

LiteLLM 返回的每次 `response.usage` 被原样保存在 round trace，并汇总以下字段：

- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `prompt_cache_hit_tokens`
- `prompt_cache_miss_tokens`

如果 LiteLLM 使用 OpenAI 风格缓存字段，则从 `prompt_tokens_details.cached_tokens` 读取
缓存命中量。

## 5. 固定 Pipeline 设置

Pipeline 基线直接复用正式 Wenyi 的三个组件及其 Prompt：

```text
Translator.translate_batch
        ↓
Polisher.polish
        ↓
GlossaryExtractor.extract
```

配置为：

| 项目 | 设置 |
|---|---|
| strong 模型 | `deepseek-v4-flash` |
| strong thinking | 开启，`reasoning_effort=high` |
| fast 模型 | `deepseek-v4-flash` |
| fast thinking | 关闭 |
| Translate 对齐重试上限 | 2 |
| Polish | 开启 |
| Rolling context | 最近 6 条润色后译文 |
| Book understanding 预扫 | 关闭，直接使用 fixture 概览 |
| 标点后处理 | 关闭 |

Translator 和 Polisher 使用 strong tier，GlossaryExtractor 使用 fast tier。最终 trace 中
恰好有 39 次成功调用，即每个 batch 三次，没有发生对齐重试。

Pipeline 同样复用 `TranslationBatchInput`。Translator 与 Polisher 接收当前 batch 相关
术语；GlossaryExtractor 接收当时的完整内存术语表。抽取结果使用首次译法优先的简单内存
规则合并：新 source 加入，已有 source 的不同 target 记录为冲突但不覆盖。

为遵守 `loop-lab/PLAN.md` 的实验约束，本实验没有接入正式 Orchestrator、RunStore 或
glossary DB，也没有运行正式 glossary DB 的重复出现过滤、历史译法校准和持久化冲突
处理。因此该基线复用了正式的三个模型组件和调用顺序，但不是完整生产 Pipeline 的端到端
运行。

Wenyi 的 DeepSeek Client 直接从 API `response.usage` 读取 Token 和
`prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`，并由 `UsageTracker` 按 tier 和
stage 汇总。

## 6. 运行命令

在 `loop-lab/` 目录中准备环境：

```bash
uv sync --dev
export DEEPSEEK_API_KEY=...
```

运行 Agent Loop：

```bash
uv run python run_fixture.py \
  --model deepseek/deepseek-v4-flash \
  --api-base https://api.deepseek.com \
  --trace-path traces/agent-comparison.json
```

运行固定 Pipeline：

```bash
uv run python run_pipeline_fixture.py \
  --model deepseek-v4-flash \
  --api-base https://api.deepseek.com \
  --trace-path traces/pipeline-baseline.json
```

生成完整对照：

```bash
uv run python compare_runs.py \
  --fixture fixtures/test_chapter.json \
  --agent-trace traces/agent-comparison.json \
  --pipeline-trace traces/pipeline-baseline.json \
  --output AGENT_PIPELINE_COMPARISON.md
```

## 7. 实验结果

| 指标 | Agent Loop | 固定 Pipeline |
|---|---:|---:|
| 成功 batch | 13/13 | 13/13 |
| 成功 segment | 97/97 | 97/97 |
| 模型调用 | 29 | 39 |
| 输入 Token | 234,718 | 131,226 |
| 输出 Token | 125,177 | 236,340 |
| 总 Token | 359,895 | 367,566 |
| 缓存命中 Token | 139,008 | 40,576 |
| 缓存未命中 Token | 95,710 | 90,650 |
| 缓存命中率 | 59.22% | 30.92% |
| 运行时间 | 1,088.467 秒 | 2,143.518 秒 |
| 最终术语 | 35 | 257 |

Pipeline 分阶段 usage：

| 阶段 | 输入 Token | 输出 Token | 总 Token |
|---|---:|---:|---:|
| Translator | 44,701 | 116,711 | 161,412 |
| Polisher | 22,970 | 105,744 | 128,714 |
| GlossaryExtractor | 63,555 | 13,885 | 77,440 |

按实验时的 DeepSeek V4 Flash 价格：

| 计费项 | 单价 |
|---|---:|
| 每百万缓存命中输入 Token | ¥0.02 |
| 每百万缓存未命中输入 Token | ¥1.00 |
| 每百万输出 Token | ¥2.00 |

费用结果：

| 流程 | 输入费用 | 输出费用 | 总费用 |
|---|---:|---:|---:|
| Agent Loop | ¥0.0985 | ¥0.2504 | **¥0.3488** |
| 固定 Pipeline | ¥0.0915 | ¥0.4727 | **¥0.5641** |

完整术语差异和逐 segment 译文位于 `AGENT_PIPELINE_COMPARISON.md`。

## 8. Trace 内容

`traces/agent-comparison.json` 包含：

- 每个 batch 的状态、耗时和最终 `output.targets`；
- 每轮模型输入、模型输出和 Tool 调用；
- 每次 LiteLLM 原始 usage；
- 汇总后的运行 usage；
- 最终 `TranslationState`。

`traces/pipeline-baseline.json` 包含：

- 每个 batch 的完整 `TranslationBatchInput`；
- Translator 原始译文；
- Polisher 最终译文；
- 抽取术语、新增术语和术语冲突；
- 每批总耗时与三个阶段耗时；
- 按 tier 和 stage 统计的 usage；
- 最终内存术语状态。

## 9. 已知限制

- 只有一个章节、一次完整对比，不能代表其他文体和模型；
- 没有人工盲评，不能判断哪套流程的译文质量更高；
- 没有动态状态消融实验，不能证明章节摘要和术语更新改善了后文；
- Agent Loop 的 `raise_question` 本次没有触发；
- 两套流程的 Prompt、思考配置和局部上下文策略不同，本实验比较的是完整流程设计，不是
  单变量 Prompt 实验；
- Pipeline 前三个 batch 曾与一个意外重复启动的同配置进程重叠，wall time 和缓存命中率
  只适合作为探索性数据；
- Pipeline 基线未接入生产 glossary DB，因此 257 项术语不能视为正式 Wenyi 术语库的
  典型结果；
- DeepSeek 服务端缓存可能受运行顺序和此前请求影响，不能由客户端清空。

## 10. 离线验证

实验代码运行前后均执行：

```bash
uv run pytest -q
uv run ruff check .
```

最终结果：36 tests passed，Ruff 通过。
