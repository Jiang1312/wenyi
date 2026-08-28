# LLM 层设计指南

本文定义 Wenyi LLM 层的模块职责、调用流程、Provider adapter 约定和新增 Provider 的规则。

## 1. 调用边界

调用链固定为：

    Runner
      -> LLMClient
      -> OpenAICompletionClient
      -> Provider adapter
      -> OpenAI Chat Completions API
      -> Provider adapter
      -> LLMResponse

Runner 只依赖：

    client.generate(messages, tools) -> LLMResponse

Runner 负责 conversation、Tool Loop 和任务完成判断。LLM 层负责消息编码、工具编码、请求调用、重试和响应解析。

## 2. 目录和职责

    wenyi/llm/
      llm_wrapper.py          # 公开 LLMClient 和 Provider 路由
      openai_completion.py    # OpenAICompletionClient，公共协议实现
      adapters/
        __init__.py           # adapter 注册表
        openai.py             # 标准 Chat Completions 默认实现
        deepseek.py           # DeepSeek 方言覆盖
        glm.py                # GLM 方言覆盖
        hunyuan.py            # 混元方言覆盖

OpenAICompletionClient 保存 API client、模型、Provider、重试配置和 options。

adapters/*.py 是无状态函数模块，不保存 API key、SDK client 或 conversation。

adapters/openai.py 定义标准默认行为。其他 adapter 复用默认函数，只覆盖实际不同的阶段。

## 3. Provider 路由

Provider 值来自 Config.llm.provider：

    llm:
      provider: deepseek
      api_key: "..."
      base_url: https://api.deepseek.com
      model: deepseek-reasoner

TranslationWorkflow 将配置值直接传给 LLMClient。LLMClient 再把同一个值传给 OpenAICompletionClient。

adapter 使用模块字典注册：

    ADAPTERS = {
        "openai_compatible": openai,
        "deepseek": deepseek,
        "glm": glm,
        "hunyuan": hunyuan,
    }

## 4. 一次 API 调用

### 4.1 Wenyi 输入

Runner 传入 Wenyi 的 Message Pydantic 对象：

    Message(
        role="assistant",
        content="我需要调用工具",
        thinking="先检查当前状态",
        tool_calls=[...],
    )

Tool 调用参数在 Wenyi 对象中是 dict。

### 4.2 Message 编码

OpenAICompletionClient 对每条消息调用 adapter.encode_message()。

默认 assistant 消息转换为：

    {
        "role": "assistant",
        "content": "我需要调用工具",
        "reasoning_content": "先检查当前状态",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "save_draft",
                    "arguments": "{\"target\": \"译文\"}",
                },
            }
        ],
    }

system、user、tool 消息和 Tool Call 的公共结构由 adapters/openai.py 实现。

### 4.3 Tool 编码

adapter.encode_tool() 将 Wenyi 工具转换为标准 function tool：

    {
        "type": "function",
        "function": {
            "name": "save_draft",
            "description": "保存草稿",
            "parameters": {...},
        },
    }

### 4.4 请求参数

OpenAICompletionClient 先组装公共字段：

    {
        "model": self.model,
        "messages": api_messages,
        "tools": api_tools,
    }

然后合并 adapter.request_params() 返回的 Provider 参数。

DeepSeek 示例：

    {
        "reasoning_effort": "high",
        "extra_body": {
            "thinking": {"type": "enabled"}
        }
    }

### 4.5 API 调用和 retry

最终参数直接传给：

    self.client.chat.completions.create(**params)

retry 只包裹 API 调用函数：

    Message 编码       一次
    Tool 编码          一次
    请求组装           一次
    API 调用           按 RetryConfig 重试
    响应解析           成功响应后一次

现有 RetryConfig、指数退避和 retry_callback 保持不变。adapter 不参与 retry。

### 4.6 响应解析

SDK 返回 Chat Completion 对象。OpenAICompletionClient 将其交给 adapter.parse_response()。

标准 parser 读取：

    response.choices[0].message
    response.choices[0].finish_reason
    response.usage

公共 parser 负责 content、tool_calls、usage、finish_reason 和 LLMResponse 构造。

Tool arguments 在 SDK 响应中通常是 JSON 字符串，在 LLMResponse 中统一转换为 dict。

### 4.7 返回 Runner

最终返回：

    LLMResponse(
        content="译文",
        thinking="先检查当前状态",
        tool_calls=[...],
        finish_reason="tool_calls",
        usage=TokenUsage(...),
    )

Runner 将 response 转回 assistant Message。若存在 Tool Call，再追加 tool Message 并发起下一轮。

## 5. Adapter 函数约定

标准 adapter 模块提供四个阶段函数：

    def encode_message(message): ...
    def encode_tool(tool): ...
    def request_params(reasoning_effort, options, *, model=None): ...
    def parse_response(response): ...

默认实现位于 adapters/openai.py。Provider 模块可以直接复用：

    encode_message = openai.encode_message
    encode_tool = openai.encode_tool
    parse_response = openai.parse_response

Provider 只实现真正不同的函数。

普通字段和特殊字段的关系是：

    common 默认实现
        + Provider 的局部覆盖
        = 最终请求或响应

当只有一个响应字段不同，Provider 可以包装公共 parser，并只替换该字段的提取函数。

## 6. DeepSeek 规则

- 使用 Chat Completions 消息和 function Tool 结构。
- reasoning_effort 支持 low、high、max。
- Wenyi 的 medium 映射为 high。
- Wenyi 的 xhigh 映射为 high（DeepSeek 官方兼容规则）。
- Wenyi 的 max 映射为 max。
- none、minimal 发送 thinking.type = disabled。
- 其他推理档位发送 thinking.type = enabled。
- 响应思考内容读取 message.reasoning_content。
- 带 Tool Call 的后续请求回传完整 reasoning_content。

## 7. GLM 规则

- 使用 Chat Completions 消息和 function Tool 结构。
- GLM-5.3/GLM-5.3-FLASH 不支持关闭 thinking；none、minimal 应报配置错误。
- GLM-5.3/GLM-5.3-FLASH 的 low、high、max 原生传递。
- GLM-5.2 的 low、medium 映射为 high，high 映射为 high。
- GLM-5.2 的 xhigh、max 映射为 max；none、minimal 关闭 thinking。
- 启用思考时发送 thinking.type = enabled。
- 交错思考和保留式思考的后续请求保留 reasoning_content。
- 保留式思考使用 extra_body.thinking.clear_thinking = false。
- 当前 Runner 只支持 function Tool；MCP Tool 报告为不支持。

`reasoning_effort` 是抽象档位，不代表所有模型的同名值。GLM-5.3-FLASH
需要最深思考时使用 `max`，使用 `high` 只要求增强思考。若通过 OpenAI-compatible
网关访问 GLM，仍需将 `llm.provider` 设为 `glm`，以选择 GLM adapter；网关地址继续
放在 `llm.base_url`。

## 8. 混元规则

混元复用标准 Chat Completions 消息、Tool 和响应解析。

混元扩展参数通过 llm.options 传递：

    llm:
      provider: hunyuan
      options:
        extra_body:
          enable_enhancement: true
          citation: true

## 9. 新增 Provider

1. 在 adapters/ 增加以 Provider 命名的模块。
2. 先复用 adapters.openai 的默认函数。
3. 只覆盖官方文档明确不同的阶段。
4. 在 ADAPTERS 中注册 Provider 名称。
5. 增加请求参数、响应解析和多轮 Tool Call 测试。
6. 保持 Runner 的 generate() 和 LLMResponse 不变。

adapter 不创建 SDK client，不发起网络请求，不保存对话状态。

如果 Provider 使用的不是 Chat Completions 协议，再新增独立协议客户端；Runner 接口保持不变。

## 10. 测试

公共测试覆盖：

- system、user、assistant、tool 消息；
- Tool schema；
- assistant Tool Call；
- arguments JSON 解析；
- content、thinking、finish_reason 和 usage；
- retry 调用次数。

Provider 测试覆盖：

- reasoning 开关；
- reasoning_effort 映射；
- Provider 扩展参数；
- reasoning_content 多轮回传；
- Provider 特殊响应字段；
- 不支持 Tool 类型的错误。

所有测试使用 SDK mock，不发起真实网络请求。
