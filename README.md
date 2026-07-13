# Kernel Runtime V6.0

V6.0 直接以已验收的 V5.5 为基础，完成真实平台授权前能够安全完成的内部工程。默认使用 Fake LLM、脱敏 Mock 资源和 Mock Delivery，不产生 Token 费用、不读取真实店铺数据、不发送真实消息。

## 已实现

- 保留 V5.5 的 Runtime 状态机、模块隔离、History、SOP、Quality、审批、幂等、审计与异步并发服务。
- SQLite 持久任务队列，支持重启恢复、有限重试、死信、租约恢复和取消。
- Redis 多实例任务后端接口；SQLite 用于单实例和本地验收。
- 低敏感指标计数和 `/v1/metrics` 查询，不记录用户文本、身份或结果。
- 真实电商平台统一 `EcommerceGateway` 接口：订单、物流、商品、店铺政策、SOP、History。
- 图片、视频、文件统一引用协议，包含 URI、类型、大小和 SHA-256 校验。
- 邮件、电商客服窗口、Webhook 统一 Delivery 路由接口，默认全部为 Mock 或关闭。
- 68 项自动化测试和零 Token 脱敏并发压测。

## 本地验收

```bash
python -m pip install -e .
python -m compileall -q src tests load_tests
python -m unittest discover -s tests -v
python main.py
python load_tests/run_load.py --tasks 500 --concurrency 24
```

## 生产边界

- 真实店铺授权、真实用户数据、真实消息发送均未启用。
- 真实平台接入只需实现 `EcommerceGateway` 和相应 Channel Provider，不修改 Runtime 内核。
- 多实例部署应配置 Redis 任务后端，并将 Runtime 业务状态迁移到部署方批准的共享数据库。
- 媒体本体不进入 Runtime Store；Runtime 只保存受控引用和摘要。

最坏情况：外部平台接口、授权范围或业务字段与当前合同不一致，适配器会拒绝数据并进入失败或人工接管，不会静默外发。
