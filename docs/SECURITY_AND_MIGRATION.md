# Security and Migration Baseline

## 已迁移的旧版能力

- Identity校验与失败后不创建Task。
- Task、Stage、Attempt、可信Environment和身份绑定。
- Runtime独占状态推进及数据库写入。
- 应用Schema、阶段读写权限和资源权限。
- 模块失败、超时、一次重试、失败阶段和人工接管。
- 任务关闭或执行授权撤销后拒绝迟到结果。
- Runtime状态、Business Store、Runtime Audit、Business Log分离。
- 外部SOP和业务资源通过应用接口注册。

## Mock安全体系

- Secret-like字段禁止写入业务Store和Log。
- 邮箱、手机号及应用敏感字段统一脱敏函数。
- 模块执行授权绑定Task、Attempt、Stage和Module。
- Delivery只能使用可信身份绑定的收件人。
- Delivery必须审批后发送。
- Delivery使用内容摘要构成幂等键。
- Provider超时进入UNCERTAIN，禁止自动盲目重发。
- GitHub Actions仅运行Mock Email，不持有真实邮箱凭证。

## 真实环境接入后仍需验证

- OAuth最小权限、Token刷新和撤销。
- 真实LLM的网络取消、首字节/无进展/总时长超时。
- 数据库静态加密、备份、恢复和访问控制。
- 真实Provider的幂等语义、限流和错误码。
- 用户授权、数据保留期限、删除请求和隐私合规。
