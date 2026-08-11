# Translation Loop × state 第一轮重构任务启动指南

更新时间：2026-08-10

## 1. 任务目标

本任务完成 Translation Loop 正式接入持久 `state/` 的第一步：

```text
准备 batch：
state/ → TranslationBatchInput + BatchWorkingState

提交 batch：
TranslationBatchOutput + 成功后的 BatchWorkingState → state/

记录运行：
成功/失败 + usage + batch 处理摘要 → 日志
```

Translation Loop 内部已经验证过的行为继续沿用，不在本任务中重新设计：

- batch 是 Loop 的执行边界；
- `TranslationBatchInput` 是当前 batch 的不可变输入快照；
- Tool 只操作 `BatchWorkingState`；
- `submit_translation` 成功后才允许更新持久业务状态；
- 任意失败都丢弃当前 `BatchWorkingState`，不得影响持久业务状态；
- `TranslationBatchOutput` 只包含与 sources 等长、按位置对应的 targets；
- chapter digest、术语及未来动态字段的业务规则沿用 MVP 已有设计。

正式架构不再保留跨 batch 的内存 `TranslationState`。每个 batch 都重新以持久 `state/`
为事实来源，创建自己的 `BatchWorkingState`。

## 2. 本任务不做什么

- 不修改 `trans_novel/` 正式流程；
- 不重新讨论 Translation Loop 的 Tool 规则；
- 不重新设计术语选择、去重或冲突业务；
- 不设计 Prepare Loop 或 Review Loop；
- 不设计通用插件、Hook、事件总线或通用 Agent 框架；
- 不考虑开发调试 trace；
- 不在真实 `state/Barn-Burning` 上直接写入；
- 离线测试不访问网络或付费 API；
- 本任务结束前不运行完整书籍翻译。

## 3. 场地选择

### 3.1 不创建新的顶层实验目录

继续使用 `loop-lab/`。这项工作是 Translation Loop MVP 的下一阶段，不需要另建
`backend-lab/` 或复制一套依赖和说明。当前仓库级约束也要求正式实现确认前只在
`loop-lab/` 中实验。

### 3.2 创建一个新的入口脚本

新增：

```text
loop-lab/run_state_fixture.py
```

旧的 `run_fixture.py` 使用手写 JSON fixture 和内存 `TranslationState`，应保留为 MVP
复现实验；不要把真实 state 逻辑塞进旧入口。

新脚本只负责命令行参数、调用 state bridge 和输出不含正文的运行摘要。读取、准备和
提交逻辑不应长期堆在入口脚本中。

### 3.3 同时预留可测试模块和测试文件

首轮文件布局：

```text
loop-lab/
├── state_bridge.py
├── run_state_fixture.py
└── tests/
    └── test_state_bridge.py
```

- `state_bridge.py`：真实 state 与 Loop 运行对象之间的转换和提交边界；
- `run_state_fixture.py`：人工运行真实 state 的薄入口；
- `test_state_bridge.py`：使用临时目录和合成数据做离线验证。

暂时不要再建子目录或 Python package。等 state bridge 确实拆出三个以上稳定职责后，再
根据真实代码决定是否移动。

## 4. 现有 loop-lab 内容如何处理

本轮不物理移动或删除任何旧文件。Git 历史、报告链接和复现命令都依赖当前路径；为了
“看起来整洁”整理文件会制造与重构无关的噪声。

### 4.1 冻结的 MVP 证据

以下内容原则上不再修改，只用于复现和查阅(已移入 archived/)：

```text
fixtures/
traces/
run_fixture.py
run_pipeline_fixture.py
compare_runs.py
EXPERIMENT_AGENT_VS_PIPELINE.md
AGENT_PIPELINE_COMPARISON.md
AGENT_LOOP_POTENTIAL_REPORT.md
TERM_EXPLORATION.md
V1.2_COMPARISON.md
```

只有发现影响既有实验结论的事实错误时才修改这些文件。

### 4.2 仍属于重构输入的 MVP 核心

以下文件不是归档垃圾，而是后续重构的行为基线：

```text
models.py
state.py
tools.py
loop.py
tests/test_loop.py
tests/test_tools.py
```

第一轮先不要直接改这些文件。先用 `state_bridge.py` 和 fake Loop 验证持久化边界；边界
稳定后，再单独执行“移除生产路径中的 `TranslationState`、让已有 Loop 使用新的
`BatchWorkingState`”任务。这样一旦桥接设计不成立，不会同时破坏已验证的 Loop。

`PLAN.md` 继续作为当前目标和进度入口，`TOOLS.md` 继续作为 MVP Tool 行为说明。

## 5. 真实测试 state 的已知情况

本轮手工集成样本使用：

```text
state/Barn-Burning
```

注意大小写，不使用 `state/Sun_steel`。

已确认的结构：

- `manifest.json` 已初始化；
- 11 个章节全部为 `pending`；
- 341 个 segment，其中 330 个正文 segment；
- 所有 target 为空，适合从第一个 batch 开始；
- `analysis.json` 已存在，包含体裁、语气、叙事、节奏、语域、对话风格、修辞、角色和
  初始术语；其 `style_guide` 字段本身为空，不能只读取这一项来构造 style；
- 没有 `book_synopsis`；
- 章节 meta 中没有 `source_digest`；
- `context.json` 的 `recent_targets` 为空；
- `glossary.db` 中有 21 项术语，没有未解决冲突；
- `events.jsonl` 目前只有初始化、语言检测、analysis 保存和跳过全书理解记录；
- `usage.json` 已记录准备阶段的 3 次调用；
- 整个 `state/` 被 `.gitignore` 忽略，不会作为测试 fixture 提交。

这些缺失字段是本轮的有效测试条件。bridge 应把尚未生成的 synopsis、digest 和 context
解释为空输入，不应自行调用模型补齐，也不应因字段缺失失败。

## 6. 安全规则：真实 state 只读

`state/Barn-Burning` 是本轮的真实结构样本和原文来源，不是可随意覆盖的测试目录。

### 手工读取

只读模式可以直接指向真实目录：

```bash
cd loop-lab
uv run python run_state_fixture.py \
  --state-dir ../state/Barn-Burning \
  --chapter 0 \
  --batch 0 \
  --dry-run
```

### 手工写入实验

先复制整个目录，包括 SQLite 主文件、WAL 和 SHM；复制时不得有另一个 Wenyi 进程正在
使用该 state：

```bash
bridge_tmp_dir="$(mktemp -d)"
cp -R ../state/Barn-Burning "$bridge_tmp_dir/Barn-Burning"
uv run python run_state_fixture.py \
  --state-dir "$bridge_tmp_dir/Barn-Burning" \
  --chapter 0 \
  --batch 0
```

新脚本默认必须是只读模式。任何可能写入的运行都应要求调用方显式提供临时 state 路径；
不要设计一个容易误写真实目录的 `--write` 开关。

自动化测试不得依赖 `state/Barn-Burning` 存在。测试应在 `tmp_path` 中创建最小合成 state，
避免 CI 依赖本地书籍和被 Git 忽略的数据。

## 7. 开始前需要了解的代码

按以下顺序阅读，读到能解释每一项职责为止：

1. `loop-lab/models.py`
   - `TranslationBatchInput`
   - `TranslationBatchOutput`
   - 输出契约校验
2. `loop-lab/state.py`
   - MVP 中 `TranslationState` 为什么存在
   - `BatchWorkingState` 如何隔离未提交变化
3. `loop-lab/tools.py`
   - 哪些 Tool 读取 batch input
   - 哪些 Tool 修改 working state
   - `submit_translation` 的终止条件
4. `loop-lab/loop.py`
   - working state 的创建和提交位置
   - 成功与失败的边界
5. `trans_novel/pipeline/runstore.py`
   - state 目录路径
   - JSON 原子写入
   - 书级锁
   - manifest、chapter、context、analysis、usage 和 event 操作
6. `trans_novel/ingest/models.py`
   - `Chapter`、`Segment` 及 source/target 回填位置
7. `trans_novel/pipeline/context.py`
   - `RollingContext` 的恢复、渲染和更新
8. `trans_novel/glossary/store.py`
   - 只读术语加载
   - term upsert 与冲突语义
9. `trans_novel/agents/analyzer.py::style_brief`
   - 正式流程如何把完整 analysis 转成翻译 style
10. `trans_novel/ingest/segmenter.py::chapter_batches`
    - 正式 Segment 如何组成 batch

`RunStore` 和 `GlossaryStore` 在本任务中是读取当前 state schema 的现成工具，不代表它们
已经被选定为最终 Agent 后端接口。新脚本通过 `state_bridge.py` 隔离这些正式实现，避免
Loop 直接依赖文件路径或 SQLite。

## 8. 实施顺序

### 第 0 步：建立干净基线

在 `loop-lab/` 执行：

```bash
uv sync --dev
uv run pytest -q
uv run ruff check .
```

记录测试数量。当前工作树已经包含 `AGENTS.md` 和 `PLAN.md` 的用户确认修改，不要覆盖或
回退它们。

### 第 1 步：创建新脚本骨架

创建 `run_state_fixture.py`，只实现：

- `--state-dir`：state 目录；
- `--chapter`：章索引，默认 0；
- `--batch`：章内 batch 索引，默认 0；
- `--max-chars-per-batch`：默认使用当前正式配置默认值 1800；
- `--context-segments`：默认使用当前正式配置默认值 6；
- `--dry-run`：只准备输入并输出摘要，不调用模型、不写 state。

脚本应复用 `run_pipeline_fixture.py` 已有的项目根目录导入方式。输出只能包含：

- state 路径；
- 书名、语言；
- chapter 和 batch 索引；
- source 数量与字符数；
- 相关术语数量；
- style、context、synopsis、digest 是否为空；
- state 中已有的累计 usage 调用数。

默认不要打印原文、译文、完整术语或 analysis 内容。

完成本步时，脚本尚不需要导入或调用真实 `agent_loop`。

### 第 2 步：实现只读 state → Loop 准备路径

在 `state_bridge.py` 中实现以下行为，不先追求最终类名：

1. 使用 `RunStore(create=False)` 读取并校验 manifest；
2. 读取指定 Chapter，并用公开的 `chapter_batches()` 形成 batch；
3. batch 不存在、章节不存在或 batch 已有混合完成状态时显式报错，不静默选别的内容；
4. 从 analysis 构造与正式流程一致的 style brief，不能只读空的 `style_guide`；
5. 从 `context.json` 恢复 `RollingContext`，按参数渲染最近译文；
6. 缺失的 `book_synopsis` 和 chapter digest 使用空字符串；
7. 从 `glossary.db` 读取术语，并沿用 MVP 已确定的规则筛选当前 batch 相关项；
8. 把正式 `GlossaryTerm` 转成 `GlossaryTermInput`；
9. 构造 `TranslationBatchInput`；
10. 用持久 state 中当前已提交的信息初始化新的 `BatchWorkingState`。

本步的结果是一次完整的“准备 batch”，但仍不调用模型、不写 state。

### 第 3 步：明确新的 BatchWorkingState

不要把 MVP 的 `TranslationState` 带入新 bridge。新的 working state 至少需要表达：

- 当前有效译文草稿；
- 本 batch 内对 chapter digest 的工作版本；
- 本 batch 内新增术语的工作结果；
- 后续新增 Tool 所需、但尚未提交的动态状态。

业务规则沿用 MVP；本任务只改变状态的来源和去向：

```text
旧：TranslationState → deepcopy → BatchWorkingState → TranslationState

新：持久 state → BatchWorkingState → 持久 state
```

第一轮可以把实验性 working state 放在 `state_bridge.py`，不要立即修改旧 `state.py`。
bridge 验证通过后，再决定把它移回 `state.py` 还是进入正式包。

### 第 4 步：使用 fake Loop 验证成功路径

在连接真实 Agent Loop 前，提供一个离线 fake：

- 接收准备好的 `TranslationBatchInput` 和 `BatchWorkingState`；
- 生成与 sources 等长的确定性 targets；
- 可选地更新 digest；
- 可选地增加一个不与现有术语冲突的术语；
- 返回 `TranslationBatchOutput`。

成功后由 bridge 负责把以下内容写入临时 state：

- targets 回填到原 Chapter 中正确的 Segment；
- working digest 写入最终选定的持久位置；
- 新增术语按现有 `GlossaryStore` 语义写入；
- 更新 RollingContext；
- 记录 batch 成功事件和处理摘要；
- 合并本 batch usage；fake usage 可以是固定样本。

“digest 写入哪里”是本任务中第一个必须形成明确结论的持久化设计问题。不得覆盖预扫生成
的 `source_digest`。在写代码前，把候选位置、读取方式和续跑方式写进测试名称或简短设计
注释；如果不同位置会影响兼容性，先停止并请求确认。

### 第 5 步：验证失败路径

fake Loop 分别在以下位置抛出异常：

- 创建草稿前；
- 修改 working digest 后；
- 新增 working 术语后；
- 返回最终 output 前。

每种失败都必须满足：

- Chapter targets 未变化；
- 持久 digest 未变化；
- glossary.db 未变化；
- context.json 未变化；
- manifest 进度未被标记完成；
- 写入失败事件和实际产生的 usage；
- 再次准备同一 batch 得到与失败前一致的业务输入。

这里的“不影响 state”特指业务状态。失败日志和已发生的模型 usage 必须保留。

### 第 6 步：验证重新读取

成功提交 fake batch 后，关闭所有 state 对象并重新打开临时目录，不复用内存缓存。确认：

- 已保存的 targets 可以从 Chapter 重新读出；
- 下一 batch 的输入使用最新 context、digest 和术语；
- 已完成 batch 不会被当作全新待译内容覆盖；
- events 和 usage 与一次成功运行相符。

这一步证明跨 batch 信息确实由持久 state 传递，而不是由另一个隐藏的内存
`TranslationState` 传递。

### 第 7 步：再连接已有 Agent Loop

只有前六步离线通过后，才开始调整已有 `loop.py`、`tools.py` 和 `state.py`：

- `agent_loop` 接收已经准备好的 `BatchWorkingState`；
- Loop 不再创建或提交 `TranslationState`；
- Tool 继续只修改 working state；
- `submit_translation` 仍只产生 `TranslationBatchOutput`；
- Loop 成功返回后，由 state bridge 完成持久提交；
- Loop 异常时，bridge 只记录失败和 usage。

先用 fake LLM 跑这一连接，最后才允许在复制的 `Barn-Burning` state 上运行一个真实 batch。
真实 API 运行不是离线测试的一部分，不应在没有明确 API Key 和费用确认时自动执行。

## 9. 自动化测试清单

`tests/test_state_bridge.py` 至少覆盖：

### 读取和准备

- 合法 state 能构造第一批 `TranslationBatchInput`；
- sources 来自正确 Chapter 和 Segment；
- 完整 analysis 能生成非空 style，即使 `style_guide` 为空；
- 缺少 synopsis、digest 或 context 时使用空值；
- glossary 转换保留 source、target、reading、type、gender、aliases 和 note；
- 无效 chapter/batch 显式失败；
- dry-run 不修改任何文件。

### 成功提交

- targets 精确回填到原 Segment，不覆盖 batch 外内容；
- target 数量不匹配时拒绝提交；
- digest 和术语工作变化只在成功后持久化；
- context 在成功后包含最新 targets；
- 成功事件和 usage 只记录一次；
- 关闭后重新读取仍能看到全部成功结果。

### 失败隔离

- working state 的每一种中途变化都不会污染持久业务状态；
- 失败事件与已发生 usage 会被记录；
- 失败后可以从同一 batch 重新开始。

### 兼容性

- 已有 target 的 Segment 不被意外覆盖；
- 旧 state 缺少新增字段时仍可读取；
- 未识别的新字段不会因保存 Chapter 而丢失；
- SQLite 连接在成功和失败后都正确关闭。

不要把真实书籍文本复制进测试断言或提交到仓库。

## 10. 验证命令

每个小阶段后运行：

```bash
cd loop-lab
uv run pytest -q
uv run ruff check .
```

只运行 bridge 测试：

```bash
uv run pytest -q tests/test_state_bridge.py
```

真实 state 只读检查：

```bash
uv run python run_state_fixture.py \
  --state-dir ../state/Barn-Burning \
  --chapter 0 \
  --batch 0 \
  --dry-run
```

写入实验必须使用临时副本，并在运行前后比较 Chapter、context、glossary、events 和 usage；
不要依赖 `git status` 检查 state 变化，因为整个 `state/` 已被 Git 忽略。

## 11. 完成标准

满足以下条件，第一步才算完成：

- [ ] `run_state_fixture.py --dry-run` 能从 `state/Barn-Burning` 构造第一批输入和 working
      state，且不修改任何文件；
- [ ] 自动化测试使用合成临时 state，不依赖真实书籍；
- [ ] fake 成功运行能把 output 和 working state 变化写入临时 state；
- [ ] fake 失败运行只留下失败日志和 usage，业务状态完全不变；
- [ ] 关闭进程内对象后，下一批能完全从持久 state 恢复最新信息；
- [ ] 生产路径不再需要跨 batch 内存 `TranslationState`；
- [ ] 已有 MVP Tool 业务规则没有被重新设计或削弱；
- [ ] 未修改 `trans_novel/` 正式流程；
- [ ] `loop-lab` 全量 pytest 和 Ruff 通过；
- [ ] 人工检查一次复制后的 `Barn-Burning` state，确认写入位置与日志可理解。

## 12. 必须停下来确认的情况

出现以下任一情况，不要自行扩大设计：

- 必须修改 `trans_novel/` 才能继续；
- 需要改变现有 Tool 参数或术语规则；
- 需要覆盖或重新解释 `source_digest`；
- 无法在多个持久文件之间保证失败隔离或可靠恢复；
- 需要引入通用事务、事件总线、插件框架或新的数据库；
- 需要决定旧 state 的不可逆迁移；
- 真实 API 行为与 fake 契约不一致。

停止时应记录：当前证据、最小复现、候选方案和各自影响，然后请求设计确认。

## 13. 任务交接摘要

新开发者开始时只需记住：

1. 不重做 Translation Loop MVP；
2. 不把真实 state 当可破坏的 fixture；
3. 先建立 `state → input/working state → fake Loop → state` 的离线闭环；
4. 闭环通过后才调整已有 Agent Loop；
5. state 是跨 batch 的唯一事实来源，不再新增内存 `TranslationState`；
6. 成功提交业务状态，失败只记录日志和 usage；
7. trace 不在本任务范围内。
