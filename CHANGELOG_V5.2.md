# V5.2 变更记录

- 冻结 V5.1 的 46 项回归行为。
- Dispatcher、Customer、Worker、Writer、Quality 拆分为独立代码模块。
- 四个 LLM Agent 统一使用代码外壳，保留各自 Prompt 和输出契约。
- Worker 保持纯代码执行，不接入 LLM。
- 新增业务资源 Provider 接口和 Mock Provider。
- `v5_application.py` 精简为状态、模块、权限和校验器装配文件。
- 新增 4 项模块化架构测试，总计 50 项测试。
- 模拟闭环继续输出 `TASK_COMPLETED`。

尚未包含：真实店铺 API、真实客服窗口发送、图片或视频上传。
