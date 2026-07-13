# V5 Final Internal Boundaries

## Runtime负责

- Task、Stage、Attempt、Binding、Scope和执行授权。
- Resource请求权限、Provider调用、必需/可选资源语义。
- Store、Log、Audit、事务和状态推进。
- JSON Envelope、Schema、Evidence、Secret、敏感信息和越权检查。
- 超时、取消、重试、Quality恢复、Human Handoff和Delivery裁决。

## 电商应用负责

- Prompt Package、Pipeline、业务Schema和业务Quality规则。
- Customer两阶段策略、确定性Worker和Message Context。
- 声明需要哪些外部resource_id，不包含真实API实现。

## 外部Provider负责

- History、SOP、订单、物流、商品、政策和真实发送。
- 将平台原始结构转换成电商应用内部Schema。
- Runtime只通过ResourceProviderAdapter调用，真实Provider默认关闭。

## LLM负责

LLM行为由各自Base Prompt约束。Runtime不在内核中写入业务思考职责，只强制输入范围、输出Schema和安全边界。
