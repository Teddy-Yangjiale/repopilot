# RepoPilot 简历项目能力矩阵与推进计划

## 1. 项目目标

RepoPilot 的目标不是做一个功能堆叠的通用 Agent 框架，而是做一个面试时能在 3 分钟内讲清楚、追问时能落到真实代码与评测数据的垂直 Agent：

> 输入真实代码仓库和维护问题，Agent 在受限工具与预算内自主搜索、阅读和查看历史，输出带行级证据的调查结论；运行过程可恢复、可审计、可评测。

这个目标刻意保留三条边界：当前只读、不执行任意 shell、不宣称自动修复成功率。边界本身也是安全设计，而不是缺少一个“写文件工具”。

## 2. 大厂 Agent 岗常见能力与当前证据

| 能力 | 当前实现 | 面试时可展示的证据 | 当前判断 |
|---|---|---|---|
| Agent 循环 | Plan–Act–Observe；模型根据 Observation 动态选下一步 | `runtime/engine.py`、完整 trajectory | 强 |
| Tool Calling | search/read/git history/finish 四个语义明确的只读工具；Pydantic 参数校验 | `runtime/tooling.py`、越权与错误测试 | 强 |
| Context Engineering | 决策与最终化使用不同上下文；显式字符预算；按新近性、来源和去重选择；记录丢弃项 | `runtime/context.py`、ContextTrace、离线重放 | 强 |
| 状态与恢复 | 每个 Action/Observation 后写 SQLite checkpoint；按 run ID 恢复 | `runtime/store.py`、恢复测试 | 强 |
| Guardrails | 路径约束、只读执行权、重复动作、步数/时间预算、Evidence ID 门禁 | `runtime/engine.py`、`runtime/tooling.py` | 强 |
| Observability | action、observation、证据、延迟、token、上下文选择都进入报告 | `runtime/report.py` | 强 |
| Evaluation | 真实 issue + merged PR gold files；clean-only；HEAD/base 模式；Agent 指标 | `eval/agent_runner.py`、评测文档 | 中强，样本仍小 |
| Human-in-the-loop | 尚未实现审批后写入或执行测试 | 无 | 下一阶段 |
| Multi-Agent | 未实现，也不是当前问题所必需 | 四个工具尚无职责过载 | 暂不做 |

结论：项目已经可以证明“熟悉 Agent 开发”，因为展示的不只是模型调用，而是循环、工具协议、动态上下文、持久状态、安全边界和评测闭环。当前最需要补强的不是再套一层多 Agent，而是扩大行为评测并加入受控的人机协作执行闭环。

## 3. v0.19 Context Engineering 里程碑

旧版把最近 6 步、每步最多 2500 字符机械塞回模型。它有隐式上限，但不能回答三个面试追问：为什么保留这些信息、超预算时丢了什么、决策和生成答案是否需要同一种上下文。

v0.19 新增：

1. `ContextBuilder.build_decision`：在 7000 字符内保留问题、最近有效轨迹和紧凑证据目录，为最新 observation 预留空间。
2. `ContextBuilder.build_finalizer`：在 9000 字符内优先保留实际读取产生的证据，按文件与行范围去重，并裁剪 snippet。
3. `ContextTrace`：每次模型调用记录实际字符、预算、保留的步骤/证据、丢弃数量和截断数量。
4. CLI 与评测：预算可配置；评测报告聚合上下文均值、p95 和丢弃项。
5. 边界测试：超长问题、超长路径/关键字/snippet 仍不能突破预算。

### 离线 trajectory 重放结果

重放 v0.18 保存的 10 个真实 OpenCV clean-case 运行，共 59 次决策上下文和 9 次最终化上下文：

| 指标 | v0.18 机械拼接 | v0.19 Context Builder | 变化 |
|---|---:|---:|---:|
| 决策上下文平均字符 | 5469.3 | 4839.3 | -11.5% |
| 决策上下文 p95 | 11740 | 6950 | -40.8% |
| 决策上下文最大值 | 无显式总预算 | 6970 | 受 7000 预算约束 |
| 最终化上下文平均字符 | 9994.7 | 8015.1 | -19.8% |
| 最终化上下文最大值 | 无显式总预算 | 8985 | 受 9000 预算约束 |

这组重放只证明上下文选择与预算约束，不证明模型回答质量不变。当前环境没有 DeepSeek Key，因此行为 A/B 必须在配置 Key 后重跑，不能把离线压缩率写成任务成功率提升。

## 4. 后续实施顺序

### P0：行为评测扩容

- 配置 DeepSeek Key 后，用同一 10-case 同时跑 v0.18 与 v0.19，比较完成率、final gold-file hit、token 和延迟。
- 扩展到 20–30 个 clean case，并优先使用 `--at-base` 降低修复后代码泄漏。
- 对 Claim–Evidence 增加语义支持度评测，区分“引用存在”与“引用真的支持结论”。

### P1：Human-in-the-loop 执行闭环

- Agent 先输出结构化 patch plan，不直接写入。
- 用户批准后，在隔离 worktree 中开放最小写工具。
- build/test 使用命令白名单、时间限制和输出截断；最终报告包含 diff 与测试证据。

这一步会把项目从“仓库调查 Agent”升级成“人类批准的维护 Agent”，也是比 Multi-Agent 更有面试价值的下一步。

### P2：只有出现真实瓶颈时再考虑 Multi-Agent

只有当单 Agent 的 prompt 同时承担定位、修改和验证而变得难以维护，或工具数量明显增加时，再拆成 investigator / patcher / verifier。拆分前必须先定义共享状态、交接 schema、终止条件和端到端评测，否则只会增加演示复杂度。

## 5. 简历可写与不可写

可以写：

- 自研 Plan–Act–Observe 运行时，接入 DeepSeek Tool Calling 与 JSON finalizer。
- 实现步骤级 SQLite checkpoint、恢复、预算、重复动作检测和只读工具沙箱。
- 建立 Claim→Evidence 行级引用门禁与真实 GitHub issue / merged PR 评测集。
- 实现阶段化 Context Builder；真实 trajectory 离线重放中决策上下文 p95 降低 40.8%。

暂时不能写：

- “生产级安全沙箱”——当前是受限只读工具，不是完整隔离执行环境。
- “自动修复成功率”——当前没有 patch/build/test 闭环。
- “Multi-Agent 协作系统”——尚未实现，也没有需求证据。
- “SWE-bench 达到某分数”——当前评测任务是文件定位与证据化调查，不是 resolved rate。

## 6. 60 秒讲法

RepoPilot 是一个证据驱动的代码仓库调查 Agent。我没有直接套通用框架，而是实现了 Plan–Act–Observe 循环：DeepSeek 用 Tool Calling 在搜索、读文件和查看历史之间动态选择，但真正的执行权、参数校验和路径边界都留在本地。每一步会把 observation、行级 evidence、延迟和 token 写入 SQLite，所以中断后能继续。最终回答单独经过 JSON finalizer，并由确定性代码校验证据 ID，避免模型伪造引用。后来我发现旧版上下文是机械拼接，于是增加了分阶段 Context Builder 和 ContextTrace；在 10 个真实 trajectory 的离线重放中，决策上下文 p95 从 11740 降到 6950 字符。项目目前明确保持只读，下一步是先扩大 at-base 行为评测，再做用户批准后的隔离 patch/test 闭环。
