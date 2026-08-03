# Wenyi Translation Agent Loop 实验计划

更新时间：2026-07-31

## 1. 总目标

本实验探索如何基于 Agent Loop 实现长篇翻译中的动态基础功能。

当前关注的能力包括：

- 根据已读内容动态更新章节概览；
- 在翻译过程中动态提取术语；
- 让新状态立即影响后续 batch；
- 在提交译文时执行确定性约束；
- 未来按需扩展全书概览、人工介入等跨 batch 能力。

Agent Loop 当前不以自动 review、自主评分或反复优化译文为主要目标。实验重点是：

> 让 Agent 根据当前文本决定是否调用基础能力、写入什么全局信息，并在明确约束下
> 完成当前翻译任务。

Wenyi 正式版本仍使用固定 Pipeline。`loop-lab/` 是独立实验，不修改主流程，也不
预设最终一定由 Agent Loop 替代正式 Pipeline。

## 2. 工程简洁约束

实验正在逐步迭代，不要过快工程化或防御化。

- 一次只验证一个新假设；
- 只实现当前实验直接需要的功能；
- 优先使用直接、容易阅读的代码；
- 不提前设计 Hook、插件、事件总线或通用工作流框架；
- 不因未来可能出现的问题增加抽象；
- 没有真实失败案例时，不增加复杂保护逻辑；
- 不实现断点续跑；
- 不接入 Wenyi 的 `RunStore`、glossary DB 或正式 Orchestrator；
- 不为了展示完整性不断增加 Tool；
- 不把时间耗在反复微调不可稳定评估的 LLM 输出细节上。

当新增类、校验或抽象时，必须说明它解决的当前问题。已经存在清晰对象边界时，不要
再包一层接口。

## 3. 当前框架

### 3.1 测试数据

当前只使用一本书的一个连续长章节：

```text
Alexei Yurchak
Everything Was Forever, Until It Was No More
Late Socialism: An Eternal State
```

文件：

```text
fixtures/sample_texts.md   原始采样文本
fixtures/test_chapter.json 实际运行 fixture
```

正文已经直接写入 `test_chapter.json`。运行时不解析 Markdown，也不动态切分。

章节按 13 个连续子章节分成 13 个 batch，每批约 500–1,800 个英文词。fixture 顶层
的 `initial_chapter_digest` 和 `initial_glossary` 只用于初始化全局状态。

### 3.2 batch 与 Loop

batch 是 Agent Loop 的基本执行单位，不是章节或整本书：

```text
Book
└── Chapter
    ├── Batch 1
    │   ├── Segment 1
    │   └── Segment 2
    ├── Batch 2
    └── ...
```

- Segment 是需要按位置回填的原文单元；
- 若干相邻 Segment 组成一个 batch；
- 每个 batch 创建一次独立 Agent Loop；
- 一个章节由多个按顺序运行的 batch 构成；
- 不依赖持续增长的跨 batch 模型消息历史；
- 跨 batch 信息通过显式状态传递。

单批输入输出：

```text
TranslationBatchInput
├── sources
├── glossary_terms
├── style
├── context
├── book_synopsis
└── chapter_digest

TranslationBatchOutput
└── targets
```

`targets` 必须与 `sources` 等长、按下标对应，并且每项都是非空字符串。

### 3.3 数据流

```text
run_chapter
  │
  ├── TranslationState
  │     已提交的跨 batch 状态
  │
  ├── 构造 TranslationBatchInput 快照
  │
  └── agent_loop
        │
        ├── 从 TranslationState 创建 BatchWorkingState
        │
        └── Toolbox
              └── 只操作 BatchWorkingState
```

成功提交：

```text
Toolbox 校验当前草稿
        ↓
submit_translation 成功
        ↓
agent_loop 将 BatchWorkingState commit 到 TranslationState
        ↓
返回 TranslationBatchOutput
```

Loop 未成功提交时，working state 被丢弃，不得污染全局状态。

### 3.4 对象关系与边界

#### `TranslationBatchInput`

一次模型调用看到的不可变输入快照。它不随当前 batch 内的 Tool 调用变化。
模型消息会把 `sources` 渲染为带 `segment_number` 的对象列表，编号从 1 开始；业务
对象内部仍保持 `list[str]`。

#### `TranslationBatchOutput`

成功提交的当前 batch 译文，只包含 `targets`，不承载全局状态或 trace。

#### `GlossaryTermInput`

术语值对象，用于初始术语、动态术语和 batch 输入。

#### `TranslationState`

已经提交、可供后续 batch 使用的全局内存状态：

```text
chapter_digest
glossary_terms
```

未来需要新的动态全局字段时，优先扩展该对象，不要给 `agent_loop` 增加多个专用
callback。

#### `BatchWorkingState`

当前 batch 尚未提交的状态：

```text
translation_state   TranslationState 的独立副本
current_draft       当前有效草稿
```

它负责从 committed state 创建副本，并在成功时提交回全局状态。

#### `Toolbox`

Agent 可调用能力的边界，负责：

- Tool definitions；
- Tool 名称到 handler 的分发；
- 参数和业务约束校验；
- 读取当前 `TranslationBatchInput`；
- 修改 `BatchWorkingState`；
- 返回 `ToolResult`。

Toolbox 不直接修改 committed `TranslationState`。

#### `ToolResult`

一次 Tool 调用的结果。普通 Tool 返回消息；成功的终止 Tool 还携带
`TranslationBatchOutput`。

#### `agent_loop()`

负责：

- 模型消息循环；
- Tool 调用次数与轮数限制；
- Tool 执行和结果回填；
- trace 收集；
- 成功终止时 commit working state。

当前不需要把它改成类。

#### `run_chapter()`

模拟 Wenyi 外层流程：

- 持有 committed `TranslationState`；
- 顺序遍历章节 batch；
- 每批构造最新输入快照；
- 收集输出和整次测试 trace。

它不是生产 Orchestrator，也不负责断点恢复。

## 4. 当前工具说明

所有 Tool 定义放在 `Toolbox.definitions` 的同一个列表中，handler 放在同一个
`_handlers` 映射中。Tool 使用规则写在各自 description 中，不重复堆进 system
prompt。

### `save_draft(targets)`

- 校验并保存完整 batch 草稿；
- targets 数量必须与 sources 相同；
- 每项必须是非空字符串；
- 后一次有效草稿替换前一次；
- 校验失败时保留上一版有效草稿。

### `modify_draft(old_target, new_target)`

- 必须先通过 `save_draft` 建立完整有效草稿；
- 使用完整旧译文精确定位需要修改的段落，不要求 Agent 计算数组下标；
- `old_target` 在当前草稿中必须恰好匹配一项；
- 找不到或匹配多项时拒绝修改，避免更新错误段落；
- `old_target` 和 `new_target` 都必须是非空字符串；
- 只替换匹配段落，其他草稿内容保持不变；
- 校验失败时保留修改前的草稿；
- 修改后仍由 `submit_translation` 执行完整最终校验。

### `update_chapter_digest(chapter_digest)`

- 更新供后续翻译使用的章节记忆；
- 参数是完整替代版本，不是增量 patch；
- 应重新筛选和压缩，不应机械追加流水账；
- 最多 600 个字符；
- 没有重要变化时可以不调用；
- 只更新 `BatchWorkingState`。

### `add_glossary_terms(terms)`

- 动态新增需要后续保持一致的术语；
- 不要求先保存草稿；
- 单次最多 10 项；
- 同一次提交中的 source 不得重复；
- 已有 source 不允许再次提交或覆盖；
- source 比较会统一 Unicode 兼容字符、引号、连字符、软连字符、连续空白及
  括号相邻空白，并使用 `casefold()` 忽略大小写；
- 保留首次提交的 source 原始拼写；
- 构造后续 batch 输入时，以 RapidFuzz `partial_ratio` 筛出与原文匹配分数不低于
  80 的已有术语；完整术语表仍保存在跨 batch 状态中；
- 只更新 `BatchWorkingState`。

### `raise_question(content)`

- 当术语、语义或具体译法确实需要人工判断时调用；
- content 是 Agent 自主撰写、展示在终端中的完整问题说明；
- Tool 同步等待人类在终端回复；
- 人类回复作为 Tool message 追加到当前消息历史，随后 Loop 继续；
- 当前不持久化问题，也不实现退出后的暂停恢复或延后集中处理。

### `submit_translation()`

- 没有有效草稿时拒绝提交；
- 再次校验 batch 输出契约；
- 术语表作为 Agent 的翻译记忆和译法指导，不执行确定性字符串校验；
- 成功后返回 `TranslationBatchOutput`，由 Loop commit working state。

## 5. 其他

### 5.1 System prompt

System prompt 只说明：

- Agent 的基本翻译任务；
- `TranslationBatchInput` 各字段含义；
- 输出与 sources 等长、按下标对应。

不要在 system prompt 中重复 Tool description。

### 5.2 Trace

一次完整章节测试生成一个 JSON：

```text
[
  {"batch": 1, "status": "committed", "trace": [...]},
  {
    "batch": 2,
    "status": "failed",
    "trace": [...],
    "error": {"type": "RuntimeError", "message": "..."}
  },
  ...
  {"translation_state": {...}}
]
```

每个 batch 结束后立即更新同一个 trace 文件。成功 batch 标记为 `committed`；失败
batch 标记为 `failed`，保存异常类型和消息后重新抛出。即使触发轮数上限或其他最终
错误，也能看到此前所有 round。最后一项始终记录当时的 committed
`TranslationState`。

当前真实留档：

```text
traces/v0.json   动态章节记忆
traces/v1.json   动态章节记忆 + 动态术语
traces/v1.2.json 当前轻量术语方案
traces/v1.3.json 加入 raise_question；本次运行未调用
traces/v1.3.1.json 模型输入中的 source 增加显式编号
traces/agent-comparison.json 带耗时与 usage 的 Agent Loop 对比运行
traces/pipeline-baseline.json 正式 translate + polish + glossary 组件基线
```

对比报告：

```text
AGENT_PIPELINE_COMPARISON.md
```

### 5.3 已验证结果

- chapter digest 能在固定预算内重写和压缩；
- Agent 可以选择是否更新 digest；
- 术语 Tool 只在部分 batch 调用；
- 新术语进入后续 batch 输入；
- 新术语能作为翻译记忆引导后续 batch；
- 未提交的 batch 状态现在不会直接修改全局状态。
- v1.3.1 将 source 以 `segment_number` 编号后，13 个 batch 的首次
  `save_draft` 全部通过数量校验，且未复现 v1.2 Batch 12 的段落错位；该结果仍是
  单次真实 API 实验，不代表已经确定性保证语义对齐。
- 已用同一 fixture 和 `deepseek-v4-flash` 完成一次 Agent Loop 与固定
  translate → polish → glossary 组件的探索性对比；两侧均提交 13 个 batch、97 个
  segment。Agent Loop 使用 29 次调用、359,895 Token、1,088.467 秒，最终 35 个
  术语；固定 Pipeline 使用 39 次调用、367,566 Token、2,143.518 秒，最终 257 个
  术语。Pipeline 运行的前三批曾与一个意外重复启动的同配置进程重叠，因此本次
  wall time 与缓存命中率只作探索性参考，单个完整 trace 的 Token 与输出仍有效。

这些结果验证的是动态基础能力和状态交互，不代表总体翻译质量已经得到系统性提升。

### 5.4 当前检查

```bash
cd loop-lab
uv sync --dev
uv run pytest -q
uv run ruff check .
```

当前离线结果：33 passed，Ruff 通过。

真实 API：

```bash
uv run python run_fixture.py \
  --model deepseek/deepseek-v4-flash \
  --api-base https://api.deepseek.com \
  --trace-path traces/new-run.json
```

单元测试不得访问网络或付费 API。

### 5.5 下一步

当前已完成第一轮固定 Pipeline 对比。下一步先人工查看逐 segment 对照和术语噪声，
判断是否出现值得进一步修改 Loop 的稳定问题；在此之前不增加新的 Tool 或流程抽象。

### 5.6 新 session 开始方式

先阅读：

```text
loop-lab/PLAN.md
loop-lab/state.py
loop-lab/tools.py
loop-lab/loop.py
loop-lab/run_fixture.py
```

需要查看真实行为时再读取 `traces/v0.json` 和 `traces/v1.json`。不要重复实现已经完成
的 Loop、动态 digest、动态术语、事务 working state 或 trace 聚合。
