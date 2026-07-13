# Kernel Runtime V5.5.0

## 新增

- 异步任务服务：排队、并发上限、任务查询与取消。
- 同一会话互斥执行，不同会话并行执行。
- 幂等提交，防止重复请求产生重复任务。
- Worker 租约、心跳与过期任务重新排队。
- Redis 分布式任务后端，以及不依赖外部服务的内存后端。
- FastAPI 预生产入口与健康检查。
- 电商资源白名单、结构校验、超时、重试、并发限制与脱敏回放 Provider。
- Docker Compose 预生产运行方式。
- 零 Token、脱敏、并发负载测试。

## 修复

- Runtime 增加 create/run 分离和外部取消传播。
- 取消后的迟到结果不再覆盖取消状态。
- 重复提交能够明确标记 duplicate。

## 已知边界

- V5.5 不连接真实店铺、不读取真实用户数据、不发送真实消息。
- SQLite 适用于单 Runtime 实例；多实例共享 Runtime Store 需要下一阶段 PostgreSQL Repository。
- Redis、Docker 和 HTTP API 已提供配置，但本地基础测试不要求安装这些可选依赖。
- 默认使用 Fake LLM，真实 Ark 调用仍需显式开关和 Secret。

## 下一版本方向

- 以 V5.5 验收结果为新基线，再决定 PostgreSQL、多实例故障恢复、指标告警和真实店铺只读沙箱的版本节点。
