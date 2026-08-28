# Wenyi 开发指南

本文档定义 Wenyi 的基本架构、模块边界、目录职责和开发约定。它描述的是项目当前已经确定的抽象边界；具体任务和功能会持续增加，但新增功能应当遵循这些边界接入。

## 0. 项目概要与基本设计方案

Wenyi 是一个面向长文本的翻译工作流。项目把原始文件解析、State 持久化、LLM 任务执行和最终文件导出拆成独立阶段。

整体流程如下：

```text
原始文件
   │
   ▼
ingest：解析、切分、创建 State
   │
   ▼
State：保存原文、译文、进度和运行信息
   │
   │
   ├── prepare / translate / review：具体任务
   │
   ▼
export：将 State 回填为最终文件
```

具体任务和通用执行机制分离。

- `runner` 负责通用的 LLM 执行模式，例如 Single Call 和 Agent Loop，并提供从 State 读取 batch 等外部输入的支持。
- `translation`、`review` 等任务模块负责任务本身是什么；`consistency` 是翻译和后续任务共享的基础能力。
- `llm` 只负责统一的模型调用和 Provider 适配。

顶层流程由 `Orchestrator` 控制，CLI 只负责解析命令行参数并调用它。典型命令如下：

```bash
uv run python -m wenyi ingest book.epub
uv run python -m wenyi translate Barn-burning
uv run python -m wenyi export Barn-burning --format epub
```

配置中的 `paths.state_dir` 是所有书籍 State 的总目录。命令行中的 `Barn-burning` 是总目录下的具体书籍目录名，二者组合后才得到本次运行的 State 路径：

```text
state_dir / state_name
```

## 1. 各模块职责与边界

### 1.1 顶层流程：`orchestrator`、`cli`、`config`

#### `wenyi/cli.py`

CLI 是命令行适配层，职责是：

- 解析命令、参数和配置文件路径；
- 区分原始文件路径和具体 State 目录名；
- 调用 `Orchestrator` 的公开方法；
- 输出简单的路径或错误信息。

CLI 不负责：

- 读取章节和 Segment；
- 构造任务 Prompt；
- 直接调用 LLM；
- 直接读写 State 文件。

#### `wenyi/orchestrator.py`

`Orchestrator` 是应用级流程编排入口，负责把各层连接起来：

- 调用 ingest 创建 State；
- 根据具体 State 目录名定位一本书；
- 遍历章节和 batch；
- 创建具体任务的 workflow；
- 调用 StateStore 提交任务结果；
- 调用 export 生成最终文件。

它可以知道流程顺序、章节编号、batch 的外部位置和 State 路径，但不实现具体任务的 Prompt、Tool 或 LLM 协议。

#### `wenyi/config.py`

配置模块负责：

- 从 YAML 读取项目配置；
- 校验配置字段；
- 提供语言、LLM、翻译、Runner、路径等配置对象。

配置对象可以被 Orchestrator 和具体 workflow 使用，但配置模块不应主动创建 Runner、读取 State 或发起网络请求。

### 1.2 `llm`：模型调用基础设施

`llm` 是 Provider 无关的模型调用层。它只处理“如何向模型发请求并得到统一响应”，不处理“当前正在翻译什么任务”。

当前层次如下：

```text
Runner / Task Workflow
        │
        ▼
LLMClient
        │
        ▼
OpenAICompletionClient + adapter
        │
        ▼
OpenAI-compatible API / other provider
```

#### `wenyi/llm/schema.py`

定义 Provider 无关的数据结构：

- `Message`
- `ToolCall`
- `FunctionCall`
- `LLMResponse`
- `TokenUsage`
- `LLMProvider`
- `ReasoningEffort`

这些模型描述一次 LLM 对话和响应的公共格式。它们不应包含翻译、术语或审校字段。

#### `wenyi/llm/llm_wrapper.py`

定义公开的 `LLMClient`：

- 保存模型、Provider、base URL、reasoning effort 和重试配置；
- 根据 Provider 创建对应的协议客户端和 adapter；
- 向 Runner 暴露统一的 `generate()` 接口；
- 将调用转发给协议客户端。

`LLMClient` 不应知道：

- 当前任务是 translation 还是 review；
- State 的目录结构；
- 具体 Tool 的业务含义；
- 如何校验任务输出。

#### `wenyi/llm/openai_completion.py`

`OpenAICompletionClient` 是所有 OpenAI Chat Completions-compatible Provider 共用的协议客户端，负责：

- 将公共 `Message` 转换为 Chat Completions 消息；
- 将 Tool 定义转换为 function tool；
- 组装模型、消息、工具和 Provider 参数；
- 发起 SDK/API 调用并执行统一重试；
- 解析公共响应结构为 `LLMResponse`。

#### `wenyi/llm/adapters/`

这里使用无状态函数模块描述 Provider 方言。`openai.py` 提供默认实现，`deepseek.py`、`glm.py` 和 `hunyuan.py` 只覆盖实际不同的消息、工具、请求参数或响应字段。

Adapter 不保存连接状态，不读取 State，也不反向导入具体任务模块。

#### `wenyi/llm/retry.py`

提供通用重试策略和重试配置。重试属于模型调用基础设施，不属于具体任务逻辑。任务模块不应自行复制一套 Provider 重试循环。

#### `wenyi/llm/base.py`

提供 LLM 客户端共享的基础接口和公共配置承载。OpenAI-compatible Provider 复用 `OpenAICompletionClient`，方言差异通过 `llm/adapters/` 的函数接入。

### 1.3 `runner`：通用任务执行机制

`runner` 解决的是：

> 已经有一个任务输入、消息和工具后，如何调用 LLM 完成这个任务。

它不解决：

> 这个任务具体要翻译什么、术语表是什么、审校标准是什么。

#### `wenyi/runner/task.py`

定义通用任务输入输出契约：

- `TaskInput`：Runner 所需的通用任务包装；
- `TaskOutput`：Runner 返回的通用结果、成功状态、错误信息和 usage；
- `TaskRunner`：Runner 的公共接口。

具体任务可以把自己的任务输入放入 `TaskInput.source`，但不应把章节索引、batch 起止位置等外部编排信息塞进任务模型。

#### `wenyi/runner/agent_loop.py`

实现通用 Agent Loop：

- 维护多轮 conversation；
- 调用 `LLMClient.generate()`；
- 将模型 Tool Call 分发给 ToolBox；
- 接收 `tool_factory`，在每次 Agent Loop 尝试开始时创建本次尝试使用的 ToolBox；
- 将 Tool 结果反馈给模型；
- 累计 token usage；
- 处理 Tool 错误、Provider 错误、轮数和 Tool 次数限制；
- 根据 `ToolResult.output` 判断任务是否完成。

`AgentLoopRunner` 可以接收一个可选的 `trace_writer`，用于接收并写入已经组织好的
Agent 执行记录。Runner 不依赖 State 或具体日志存储实现。

`AgentLoopRunner.run()` 的 `tool_factory` 必须是一个无参数可调用对象，返回一个新的
`ToolBox`。Runner 不接受已经创建好的 ToolBox。Agent Loop 级别的重试会重新开始
conversation，并通过 factory 创建新的 ToolBox，避免上一次尝试留下的草稿等可变状态
影响下一次尝试。具体任务只负责提供 factory，例如：

```python
tool_factory=lambda: TranslationToolBox(task_input)
```

ToolBox 的业务逻辑仍然由具体任务实现；factory 只负责控制 ToolBox 的创建时机和生命周期。

AgentLoopRunner 不应出现以下内容：

- `save_draft`、`submit_translation` 等具体工具名称；
- 术语、章节概要或审校规则；
- 翻译结果如何写回 State；
- 某个任务特有的 Prompt。

#### `wenyi/runner/single_call.py`

提供 Single Call Runner 的公共位置和接口。它与 AgentLoopRunner 共享 `TaskRunner` / `TaskOutput` 契约，具体执行策略可以不同，但不应改变任务模块的输入输出边界。

#### `wenyi/runner/tools.py`

定义通用 Tool 协议：

- `ToolBox.definitions`：提供给模型的 Tool schema；
- `ToolBox.execute()`：执行一次 Tool 调用；
- `ToolResult`：返回给 Runner 的消息和可选最终输出。

通用 Runner 只识别 Tool 调用结果的结构，不识别工具名称和业务含义。

#### `wenyi/runner/state_reader.py`

负责从 State 读取外部编排所需的信息：

- 读取章节；
- 按字符预算组织 batch；
- 按已完成/未完成边界支持断点续跑；
- 返回 manifest 和 batch 数据。

它属于 Runner 的输入编排支持，不属于具体 translation 任务。它不应构造 Prompt、调用 LLM 或保存译文。

#### `wenyi/runner/input_schema.py`

定义 Runner 输入层所需的通用 schema。这里描述的是 Runner 的输入形状，不负责读取 State；读取 State 的逻辑属于 `state_reader.py`。

### 1.4 具体任务：`prepare`、`translation`、`review`

具体任务模块是业务层。它们使用通用 LLMClient 和 Runner，但不能把业务逻辑下沉到 Runner 或 Provider。

每个具体任务应当拥有自己的任务边界，通常包括：

```text
task input
prompt
task-specific tools
output validation
task workflow
```

任务 workflow 的职责是把任务输入转换为 Runner 能执行的形式，再把 Runner 的 `TaskOutput` 转换为任务可消费的结果。`TaskOutput.result` 保存任务结果，`TaskOutput.usage` 保存本次任务的累计模型用量。它不负责遍历全书 State，也不负责决定 batch 的章节位置。

#### `translation`

翻译任务负责：

- 定义一个 batch 的翻译输入；
- 保存 source list、source language 和 target language；
- 读取并展示当前 batch 相关的 consistency 译法；
- 构造翻译 Prompt；
- 定义 `save_draft`、`record_consistency`、`submit_translation` 等翻译工具；
- 校验译文 list 是否与 source list 等长且没有空元素；
- 将通用 Runner 结果转换为译文 list。

翻译任务不负责：

- 从 State 读取章节；
- 决定 `chapter_index`、`start_index`；
- 直接调用 LLMClient；
- 直接向 State 写入 target。

当前翻译任务的内部关系是：

```text
TranslationTaskInput
        │
        ├── build_messages()
        ├── TranslationToolBox
        └── TranslationWorkflow
                    │
                    ▼
              AgentLoopRunner
```

#### `consistency`

`consistency` 不是独立的 LLM 任务，而是由 Orchestrator 和 StateStore 使用的共享基础能力：

- `match(..., mode="exact")` 找出当前 batch 中已有记录的全部出现位置；
- `match(..., mode="vague")` 找出需要提供给模型的相关记录并去重；
- `write()` 写入新的 source-target 记录；
- `update()` 为已有完全一致记录追加出现位置。

它不负责术语判断、知识记录或 review，也不直接写入 State。

#### `review`

待设计

### 1.5 `state`：持久化和断点续跑

#### `wenyi/state/store.py`

`StateStore` 是 State 的唯一主要读写入口，负责：

- 创建 State 目录；
- 读写 manifest 和 chapter 文件；
- 写入原子 JSON；
- 提供 State 锁；
- 提交一个 batch 的译文；
- 更新章节进度和生命周期事件；
- 保存源文件 hash 和 PDF 等输入缓存目录。

StateStore 不负责调用 LLM，也不负责构造任务 Prompt。

#### State 目录结构

```text
state/
└── <state-name>/
    ├── manifest.json
    ├── chapters/
    │   ├── ch0.json
    │   └── ch1.json
    ├── consistency.json
    ├── source/
    └── logs/
        ├── events.jsonl
        └── traces.jsonl
```

`chapter` 文件保存可对齐的 Segment。`manifest.json` 保存书级信息、章节进度、语言和源文件信息。具体任务的临时 draft 不应直接写入这些文件；任务完成后由 Orchestrator 调用 `commit_batch()` 持久化。

State 级日志统一保存在 `logs/`：

- `events.jsonl`：记录 ingest、translate、export 等阶段的生命周期事件；`batch_committed` 可包含成功的 consistency write/update 摘要；
- `traces.jsonl`：记录 Agent Loop 中的模型响应、用户消息、Tool 调用和 Tool 结果。

`store.log_event(event, **data)` 的扩展字段统一写入 `data` 对象。与 Agent Loop 关联的流程事件在 `data.trace_id` 中记录对应的 trace ID。Trace 本身则将 `trace_id`、`seq`、`round` 和 `kind` 作为顶层字段，用于重建一次任务的执行顺序。

`events.jsonl` 和 `traces.jsonl` 的职责不同：前者记录 ingest、translate、export 等流程级生命周期事件；后者记录一次 Agent Loop 内部的逐步执行过程。一个 batch 的失败应记录为流程事件，具体失败发生在哪一轮则通过对应的 trace 追踪。

Trace 的 `kind` 使用 Agent Loop 和消息协议中的直接术语，不使用任务自造的描述性名称。当前约定包括：

```text
agent_start       Agent 开始执行
model_response    模型返回一次响应
user_message      运行时追加的一条 user message
tool_call         模型发起一次 Tool 调用
tool_result       Tool 返回一次结果
model_error       模型调用发生错误
agent_end         Agent 成功结束
agent_error       Agent 执行失败
```

其中 `user_message` 的 `data.source` 可以标记为 `runtime`，表示这条消息由执行器追加，而不是人工用户输入。`task_type` 表示具体任务类型，不能用它冒充顶层流程阶段。

### 1.6 `ingest`：输入文件解析

`wenyi/ingest/` 负责将 EPUB、TXT、Markdown、HTML、FB2、PDF 等输入解析为统一的 `Document → Chapter → Segment` 结构。

它可以负责：

- 文件格式识别；
- EPUB 结构、目录、内联元素和资源解析；
- PDF 转 HTML 和缓存；
- 章节拆分；
- 超长 Segment 拆分；
- 创建 State 所需的初始文档数据。

它不负责：

- LLM 预理解；
- 翻译；
- 术语或审校；
- 将模型结果写回 State。

### 1.7 `export`：结果回填

`wenyi/export/` 负责将 State 中的章节和 Segment 回填为最终文件。

它可以负责：

- TXT、Markdown、HTML、EPUB、PDF 输出；
- 章节和段落重建；
- EPUB 目录、资源、内联元素和元数据回填；
- 双语输出和说明页。

它不负责重新调用 LLM，也不负责修改任务状态。导出时应把 State 视为输入快照。

## 2. 目录结构、脚本职责与开发规范

### 2.1 当前目录结构

```text
wenyi/
├── __main__.py                 # python -m wenyi 的入口
├── cli.py                      # CLI 参数解析和命令分发
├── config.py                   # YAML 配置模型和加载
├── orchestrator.py             # 应用级流程编排
│
├── schema/
│   ├── __init__.py
│   └── document.py             # Document / Chapter / Segment
│
├── state/
│   ├── __init__.py
│   ├── store.py                # StateStore 和 State 持久化
│   └── legacy_reader.py        # 旧 State 的读取兼容
│
├── ingest/
│   ├── __init__.py             # ingest 对外入口
│   ├── loader.py               # ingest 公共函数转发
│   ├── segmenter.py            # 文件分发、长段拆分、batch 辅助
│   ├── text_reader.py          # TXT / Markdown
│   ├── html_reader.py          # HTML / XHTML
│   ├── epub_reader.py          # EPUB 正文、内联结构和资源
│   ├── epub_chapters.py        # EPUB 章节切分策略
│   ├── epub_toc.py             # EPUB 目录解析
│   ├── fb2_reader.py           # FB2
│   ├── pdf_reader.py           # PDF 转换缓存和读取
│   ├── pdf_to_html.py          # MinerU PDF 转 HTML
│   ├── models.py               # ingest 模型兼容入口
│   └── errors.py               # ingest 专用异常
│
├── llm/
│   ├── __init__.py             # LLM 公共接口导出
│   ├── schema.py               # Message / LLMResponse / TokenUsage
│   ├── base.py                 # LLM 客户端基础接口
│   ├── llm_wrapper.py          # LLMClient
│   ├── openai_completion.py    # OpenAICompletionClient
│   ├── retry.py                # 通用重试
│   └── adapters/
│       ├── __init__.py         # adapter 注册
│       ├── openai.py             # 标准 Chat Completions 行为
│       ├── deepseek.py         # DeepSeek 方言
│       ├── glm.py              # GLM 方言
│       └── hunyuan.py           # 混元方言
│
├── runner/
│   ├── __init__.py             # Runner 公共接口导出
│   ├── task.py                 # TaskInput / TaskOutput / TaskRunner
│   ├── input_schema.py         # Runner 输入 schema
│   ├── state_reader.py         # State 信息读取和 batch 组织
│   ├── tools.py                # 通用 ToolBox / ToolResult
│   ├── agent_loop.py           # 通用 Agent Loop
│   └── single_call.py          # Single Call Runner 位置和接口
│
├── consistency.py              # 一致性匹配、写入和位置更新
│
├── translation/
│   ├── __init__.py
│   ├── task.py                 # 翻译任务输入和结果校验
│   ├── prompt.py               # 翻译 Prompt
│   ├── tools.py                # 翻译专用工具
│   └── workflow.py             # 翻译任务到 Runner 的连接
│
└── export/
    ├── __init__.py             # export 对外入口
    ├── writer.py               # export 公共 façade
    ├── writer_common.py        # 输出路径和通用回填辅助
    ├── text_writer.py          # TXT / Markdown
    ├── html_renderer.py        # HTML 片段渲染
    ├── html_resources.py       # HTML 资源处理
    ├── html_writer.py          # HTML 输出
    ├── epub_writer.py          # EPUB 回填和构建
    ├── pdf_writer.py           # PDF 输出
    └── about.py                # EPUB 说明页
```

新增 `review` 或其它任务时，应采用与 `translation` 相同的任务包结构，而不是把任务逻辑添加到 `runner` 或 `llm` 中。共享的 consistency 能力保持在 `wenyi/consistency.py`，不创建独立任务包。

### 2.2 脚本和模块的编写规范

#### 模块职责必须写在文件开头

每个新脚本开头应使用模块 docstring 说明：

- 本文件负责什么；
- 本文件不负责什么；
- 它位于哪一层；
- 主要被哪些上层模块调用。

职责说明应当描述边界，不要只写“工具函数集合”之类的模糊描述。

#### 依赖方向保持单向

推荐的依赖方向是：

```text
cli
  ↓
orchestrator
  ↓
ingest / state / task workflow / export
  ↓
runner
  ↓
llm
```

具体任务可以依赖 `runner` 和 `llm` 的公共接口，但 `runner` 不应依赖具体任务。`llm` 不应依赖 `runner`、State 或任何业务任务。

#### 外部编排信息和任务输入分开

以下信息属于 Orchestrator 或 State 层：

- `state_name`；
- `chapter_index`；
- `start_index`；
- batch 在章节中的覆盖范围；
- State 路径；
- commit 所需的 source digest。

以下信息属于具体任务输入：

- 当前任务真正处理的内容；
- 任务所需语言或规则；
- 任务专用上下文。

不要为了方便把章节索引和 State 路径塞入 `TranslationTaskInput` 或审校任务输入。

#### Tool 的业务逻辑放在任务模块

通用 Runner 只负责调用 Tool。Tool 的定义、参数、业务校验和临时状态应放在具体任务包内。

例如：

```text
runner/tools.py
    ToolBox / ToolResult 协议

    translation/tools.py
    save_draft / record_consistency / submit_translation
```

Tool 可以维护一次任务执行期间的临时状态，但不应绕过 Orchestrator 直接写入 State。

#### State 写入集中管理

任务执行成功后，由 Orchestrator 根据外部位置调用 StateStore 提交结果：

```text
Task Workflow 返回任务结果
    ↓
Orchestrator 补充 chapter/start 等外部信息
    ↓
StateStore.commit_batch()
```

这样可以保证任务模块可以独立测试，也可以让不同任务共享同一套 State 生命周期规则。

#### 新增任务优先新增完整垂直切片

新增 review 或其它 LLM 任务时，建议一次完成以下最小闭环：

```text
TaskInput
→ prompt
→ tools（如需要）
→ workflow
→ Runner
→ output validation
→ Orchestrator 接入
```

不要先修改通用 Runner 来适配一个尚未定义清楚的任务。

#### 测试和验证

每个模块至少应有与其边界对应的测试：

- ingest：输入文件到 Document 的结构测试；
- State：读写、锁、batch commit 和断点续跑测试；
- LLM：公共 schema、Provider 转换和重试测试；
- Runner：Tool 调用、错误反馈、终止条件和 usage 测试；
- 具体任务：Prompt、Tool 参数和输出校验测试；
- Orchestrator：跨模块的最小端到端测试；
- export：从 State 到目标文件的回填测试。

修改完成后至少运行：

```bash
uv run pytest -q
uv run ruff check wenyi tests
```

如果修改涉及文件格式处理，还应使用真实的小型 EPUB、TXT 或其它输入做一次手工 smoke test。

#### 保持公共接口简单

在没有实际调用方之前，不要为未来 Provider、Runner、任务类型或 Skill 预先加入多层抽象。优先保持：

- 一个清晰的公共入口；
- 一个明确的数据契约；
- 一个可以独立测试的 workflow；
- 一个可以观察的失败边界。

当新的功能确实需要扩展时，先更新本指南中的边界和数据流，再修改代码。
