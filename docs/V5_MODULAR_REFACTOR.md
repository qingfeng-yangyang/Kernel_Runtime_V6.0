# V5.2 电商模块化说明

本次修改只重构电商应用层，不修改 Runtime 内核语义。

## 目录职责

```text
ecommerce/
├── v5_application.py       # 只负责装配状态、模块、权限和校验器
├── v5_support.py           # LLM 外壳、Prompt 加载、超时及 Envelope 公共能力
├── v5_modules/
│   ├── dispatcher.py       # Dispatcher 独立模块
│   ├── customer.py         # Customer 两阶段独立模块
│   ├── worker.py           # 纯代码 Worker
│   ├── writer.py           # Writer 独立模块
│   └── quality.py          # Quality 独立模块
└── providers/
    ├── base.py             # 业务资源统一接口
    └── mock.py             # 独立测试资源实现
```

## 关键边界

- Runtime 只调度模块并校验结果，不包含电商业务实现。
- 四个 LLM 模块分别由代码外壳封装，Prompt 和动态上下文仍分离。
- Worker 不调用 LLM，只按 Plan 读取已授权业务资源。
- Worker 默认使用 Runtime 的资源访问器，也允许注入新的业务资源提供器。
- 真实店铺接入时新增 Provider，不修改 Runtime 状态机。
- 原有 `build_v5_fake_llm_application()`、`seed_v5_resources()` 和 `_package()` 入口保持兼容。
