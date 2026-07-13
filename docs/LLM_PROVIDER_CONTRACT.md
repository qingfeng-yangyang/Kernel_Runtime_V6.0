# LLM Provider Contract

V4只实现Provider中立协议和Fake LLM，不连接真实模型。

## 四层超时

- connect：客户端等待Provider建立连接。
- first_response：连接后等待首个有效响应块。
- idle：收到首块后，两个进度事件之间的最大间隔。
- total：无论是否有进度，整个请求的绝对上限。

## 三层取消

- Runtime撤销当前Stage的执行授权。
- LLMClient设置取消事件并停止接收响应。
- Provider支持时执行`cancel(request_id)`请求服务端取消。

关闭客户端连接不能保证服务端一定停止推理；真实Provider必须明确其取消语义。

## 错误分类

- `ProviderAuthenticationFailure`：不重试。
- `ProviderRateLimitFailure`：可重试。
- `ProviderTemporaryFailure`：可重试。
- `ProviderContentRejected`：不重试。
- `TimeoutFailure`：按阶段策略决定。
- `ValidationFailure`：不信任返回值，不写Business Store。

## 可信数据边界

LLM模块只能收到：

- 当前Task业务输入。
- 当前Stage被授权读取的Business Store字段。
- Runtime生成的最小请求metadata。

身份、来源、Environment、Binding、Scope、Runtime Audit和其他Task数据不进入Prompt。
