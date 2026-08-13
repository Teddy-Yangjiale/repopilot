# RepoPilot Agent Runtime：架构对比与面试讲解

## 1. 这次升级解决什么问题

旧版 RepoPilot 的 Investigator、Planner、Verifier 是固定流水线：可靠、可评测，但模型不能根据上一轮观察动态选择下一步。v0.17 保留原有检索与引用门禁，新增一个独立的 Plan–Act–Observe 运行时，让项目同时具备“会自主调查”和“结果可验证”两种能力。

这不是把 LangChain 或 LangGraph 包一层。状态模型、工具协议、执行循环、预算控制、checkpoint 和轨迹报告都在仓库中直接实现，面试时可以沿真实调用链解释每个设计。

## 2. 与代表性代码 Agent 的对比

| 项目 | 核心优势 | RepoPilot 采用的思想 | RepoPilot 的差异化 |
|---|---|---|---|
| SWE-agent / mini-SWE-agent | 面向软件工程任务的 Agent–Computer Interface 与完整 trajectory | 用少量、语义清晰的工具限制动作空间 | 当前只读调查，不宣称自动修复 SWE-bench |
| OpenHands | Action → Runtime → Observation 的事件循环与隔离执行环境 | 把模型决策和本地执行权分离 | 工具集更小，重点是代码证据和引用真实性 |
| LangGraph | durable execution、checkpoint、human-in-the-loop | 每一步持久化完整状态，可按 run ID 恢复 | 不依赖图框架，循环和恢复语义可直接阅读 |
| Aider | repository map、token budget、architect/editor 分工 | 限制上下文、记录 token、按证据逐步缩小范围 | 以行级 Evidence 和 finish 引用门禁为核心 |

官方资料：

- SWE-agent：<https://github.com/princeton-nlp/SWE-agent/blob/main/docs/background/index.md>
- OpenHands architecture：<https://docs.openhands.dev/openhands/usage/architecture/runtime>
- LangGraph：<https://langchain-ai.github.io/langgraph/index.html>
- Aider repository map：<https://aider.chat/docs/repomap.html>

## 3. 一次运行的真实数据流

```text
Question + persisted AgentRun
            |
            v
DeepSeekToolPolicy -- native tool schema --> AgentDecision
            |                                  |
            |                          tool + validated arguments
            v                                  v
      bounded context                    ToolRegistry
                                               |
                              search/read/history/finish
                                               |
                                               v
                                      ToolObservation
                                               |
                       evidence merge + AgentStep + SQLite checkpoint
                                               |
                              completed / next step / budget exhausted
```

关键实现位置：

- `runtime/policy.py`：把当前状态和工具 schema 发给 DeepSeek，并解析原生 tool call。
- `runtime/engine.py`：有界 Plan–Act–Observe 循环；工具错误作为观察反馈给下一步。
- `runtime/tooling.py`：Pydantic 参数校验、白名单工具和本地执行权。
- `runtime/store.py`：每一步保存完整 `AgentRun`，使用 SQLite WAL。
- `runtime/report.py`：导出可审计 trajectory，而不保存模型隐藏思维链。

## 4. 为什么只有四个工具

- `search_code`：发现候选文件，并复用已评测的代码检索能力产生 Evidence。
- `read_file`：读取最多 301 行；路径必须在仓库内，焦点关键词必须真实出现。
- `git_history`：只读取指定路径的最近提交，使用参数数组启动 Git，不经过 shell。
- `finish`：提交答案及 Evidence ID；只要出现未知 ID，运行时就拒绝完成。

工具越宽泛，模型的选择空间和安全风险越大。第一版只覆盖“仓库调查”需要的最小闭环，不开放任意 shell、Python 执行、写文件或 Git 修改。

## 5. 可靠性设计及对应测试

| 风险 | 运行时约束 | 回归测试 |
|---|---|---|
| 模型重复调用同一工具 | 忽略 `reason` 后计算动作指纹并拒绝重复 | 重复搜索转为 `tool_error`，最终耗尽预算 |
| 模型伪造引用 | `finish` 只能引用本次已收集的 Evidence ID | 伪造 ID 无法完成运行 |
| 中途崩溃 | 每个 observation 后保存完整状态 | 恢复时保留已有搜索步骤，不重复执行 |
| 参数或路径越界 | Pydantic `extra=forbid` + 仓库根目录路径策略 | 非法参数/路径变为可见工具错误 |
| 无限循环或成本失控 | `max_steps` 与 wall-clock timeout 双预算 | 状态明确变为 `budget_exhausted` |
| 泄露隐藏思维链 | 只要求并存储不超过 300 字的行动理由 | 报告展示 concise reason，不展示 CoT |

## 6. 当前边界与下一阶段

v0.17 可以诚实宣称：它是一个只读、可恢复、证据驱动的仓库调查 Agent Runtime。它还不能宣称自动改代码、在容器中安全执行测试，或达到 SWE-bench 级别的修复成功率。

下一阶段应先建立 20–30 个真实问题的 Agent 评测集，报告完成率、引用有效率、平均步骤、token/延迟、恢复成功率和失败类型；数据稳定后，再新增隔离 worktree 中的 patch、build、test、diff 与 verifier 工具。

## 7. 60 秒面试讲法

> RepoPilot 最初是固定的代码检索和引用验证流水线，我把它升级成了一个可恢复的 Plan–Act–Observe Agent Runtime。模型使用 DeepSeek 原生 Tool Calling 决定搜索、读文件还是查看历史，但没有本地执行权，只能调用经过 Pydantic 校验的四个只读工具。每个 Action、Observation、行级 Evidence、延迟和 token 都会落到 SQLite，所以进程失败后可以从最后一步继续。为了控制幻觉和成本，我加入了重复动作检测、步数与时间预算，以及 finish 引用门禁；模型引用不存在的证据 ID 时，确定性运行时代码会拒绝完成。它和通用 Agent 框架相比的差异，是把真实仓库检索评测和可验证证据作为核心，而不是只展示一个能调用工具的 Demo。
