# 最小 Agent Loop Tool 设计

## 文件职责

```text
models.py    稳定的业务输入输出
state.py     跨 batch 共享、可由 Agent 动态更新的内存状态
tools.py     Tool 定义、Tool 状态和调用分发
loop.py      模型调用、消息历史、限制和终止
```

## Toolbox

每次翻译创建一个 `Toolbox`：

```python
working_state = BatchWorkingState.from_committed(state)
toolbox = Toolbox(batch_input, working_state)
```

Toolbox 持有不可变的 `batch_input` 和当前 batch 的 `BatchWorkingState`。草稿、
章节记忆和新术语都只修改 working state；成功提交后由 Loop 将其写回跨 batch
共享的 `TranslationState`。这些状态不需要 Agent 提供，也不会出现在 Tool 参数中。

Agent 可以看到六个 Tool：

```text
save_draft(targets)
modify_draft(old_target, new_target)
update_chapter_digest(chapter_digest)
add_glossary_terms(terms)
raise_question(content)
submit_translation()
```

它用完整的新梗概替换内存 `TranslationState.chapter_digest`。每个 batch 开始时重新读取
该状态并构造新的 `TranslationBatchInput`，因此更新会影响后续 batch。梗概是供
后续翻译使用的工作记忆，而不是已读内容的完整摘要；每次更新必须重新筛选和压缩，
长度不得超过 600 个字符。

`add_glossary_terms` 每次最多写入 10 个术语，同一次提交中 source 不得重复，已有
source 不允许再次提交。术语完整保存在 `TranslationState.glossary_terms`；构造后续
batch 输入时，仅提供经 RapidFuzz `partial_ratio` 检索分数不低于 80 的术语，用于
引导 Agent 保持译法一致。source 的重复判断会统一 Unicode
兼容字符、引号、连字符、软连字符、连续空白及括号相邻空白，并忽略大小写，但保留
首次写入的原始拼写。提交时不对术语执行确定性字符串校验。

Loop 使用统一入口执行 Agent 的 Tool 请求：

```python
result = toolbox.execute(tool_name, arguments)
```

新增 Tool 时，在 Toolbox 中增加方法、定义和 handler 映射即可，不需要增加 Loop
持有的业务状态。

## save_draft

Agent 参数：

```python
targets: list[str]
```

行为：

1. 检查译文数量与原文相同；
2. 检查每项都是非空字符串；
3. 校验成功后替换当前草稿；
4. 允许重复调用；
5. 校验失败时保留上一版有效草稿。

## submit_translation

Agent 无需提供参数。

行为：

1. 没有草稿时拒绝提交；
2. 再次校验当前草稿；
3. 返回最终 `TranslationBatchOutput`。

`ToolResult.output` 不为空表示 Agent 已经提交最终译文，Loop 应立即返回该输出并
结束。

## raise_question

Agent 参数：

```python
content: str
```

Agent 在 content 中完整说明相关原文、翻译疑点和候选方案。Tool 将内容展示在终端，
同步等待人类输入，并把回复作为 Tool message 返回给 Agent。下一轮模型调用可以读取
该回复并继续翻译。

当前不保存待处理问题，也不实现延后 review 或退出后的暂停恢复。

## modify_draft

Agent 参数：

```python
old_target: str
new_target: str
```

行为：

1. 必须先用 `save_draft` 保存完整有效草稿；
2. 在当前草稿中精确查找完整的 `old_target`；
3. 仅在恰好匹配一段时将其替换为 `new_target`；
4. 找不到或匹配多段时拒绝修改，避免错误定位；
5. 两个参数都必须是非空字符串；
6. 修改失败时保留原草稿；
7. 修改后仍需调用 `submit_translation` 提交完整草稿。

这个 Tool 适合主动修正单段翻译，不需要重新输出完整 batch。它使用旧译文定位而不是
让 Agent 计算数组下标。

## 最小路径

```text
Agent 读取 TranslationBatchInput
        ↓
save_draft(targets)
        ↓
Agent 检查当前草稿
        ↓
需要修改？
  ├── 局部修改：modify_draft(old_target, new_target)
  ├── 整体修改：再次 save_draft(targets)
  └── 否：submit_translation()
                    ↓
          TranslationBatchOutput
```

当前不提供 `translate`、`polish`、`review_translation`、`lookup_glossary`
或 `extract_terms` Tool。
