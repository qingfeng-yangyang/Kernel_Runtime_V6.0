# V6.0 更新说明

基线：已验收 V5.5。

## 新增

- 持久任务队列、重启恢复、有限重试、死信和低敏感运行指标。
- 电商平台 Gateway 合同与经过 Schema 校验的资源适配器。
- 图片、视频、文件引用协议和 Mock 媒体存储。
- 邮件、电商客服窗口、Webhook 统一 Delivery 路由和 Mock Provider。
- V6.0 平台边界安全测试。

## 保持不变

- Runtime 不绑定订单、物流、SOP、History 或具体平台 SDK。
- Worker 仍是确定性代码；四个 Agent 保持独立封装。
- 真实 LLM、真实数据和真实发送默认关闭。

## 已知边界

- 未包含任何真实平台凭据、SDK 实现或真实发送授权。
- SQLite Runtime Store 不是多实例生产数据库；部署时需使用批准的共享数据库。
