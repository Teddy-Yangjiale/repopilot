# RepoPilot 面试讲解手册

这份文档解释脚手架中的每个设计为什么存在。面试时不要背代码，要用“问题—取舍—实现—验证”四步表达。

## 1. 总体设计

### 为什么不是直接做一个大 Prompt

大 Prompt 无法清楚判断失败发生在召回、规划还是验证阶段，也很难做阶段级重试。RepoPilot 使用显式状态机：

1. Investigator 收集代码证据。
2. Planner 根据证据安排下一步调查。
3. Verifier 检查每条结论的引用。
4. Orchestrator 在阶段边界写入 SQLite。

这样能独立评测每一阶段，并从最后一个 Checkpoint 恢复。

### 为什么第一版不调用 LLM

Phase 1 先证明工具、安全边界、状态协议和持久化正确。LLM 是概率组件，如果基础层还不可验证，引入模型会让问题难以归因。Phase 2 让 DeepSeek 负责查询扩展；v0.18 加入 Tool Calling 动作选择和 JSON Output finalizer，但执行权、预算、checkpoint 和引用门禁仍由确定性运行时控制。已有 10-case 小基准，但不能把“定位命中”说成“自动修复成功”。

### 为什么采用 Hybrid，而不是完全替换规则

确定性提取器成本为零、结果可复现，但不理解同义词和仓库命名；LLM 能补充 `tool call`、`invoke_with_tools` 这类跨表达候选，但会超时、输出错误 JSON，也会产生费用。RepoPilot 总是保留规则关键词，再合并最多 6 个模型候选，并在模型调用失败时退回规则结果。这是 Agent 工程里的“概率增强、确定性兜底”。

面试时可以把失败分为两类：缺少 Key/依赖属于配置错误，必须显式失败；提供方超时或格式异常属于运行时错误，可以降级，并把原因写入 `QueryExpansionTrace`。两者不能都静默吞掉。

## 1.5 现状速览（v0.19.0，面试前必看）

- **阶段 A/B/C**：检索定位在 60 个真实 OpenCV issue 上迭代，Hit@10 0.283 → 0.583 → 0.750，Recall@10 0.183 → 0.472 → 0.647，MRR 0.170 → 0.390 → 0.487。每步改动都在评测集上报数字。
- **阶段 D（已回退）**：BM25 长度归一对代码仓库方向性错误（0.750 → 0.283），保留实验开关——教科书方法被真实数据证伪，这是加分叙事。
- **阶段 E**：Verifier 回读文件确认关键词出现在引用行号，一上线就抓出两个数据流 bug（去重键缺 keyword、回读缓存键缺行范围）。
- **仓库无关**：在 golang/go（sync.Pool→pool_test.go）、facebook/react（fiber→ReactFiberWorkLoop.js）、fastapi（OpenAPI→routing.py）上实测通过；通用 docs/changelog 降权不伤害 OpenCV 数字。
- **Agent Runtime**：Plan–Act–Observe 循环、Tool Calling 动作选择、JSON Output finalizer、逐条 Claim→Evidence、四个只读工具、逐步 SQLite checkpoint、预算/引用门禁与 trajectory 报告。
- **Context Engineering**：决策/最终化分阶段上下文、7000/9000 字符预算、Evidence 来源优先级与去重、ContextTrace 可观测丢弃项；10 个真实 trajectory 重放中决策上下文 p95 从 11740 降至 6950 字符。
- **Agent 小基准**：10 个不直接出现修复路径的 OpenCV Issue，完成率 1.00，最终引用命中 merged-PR gold file 0.70；这是 HEAD 定位结果，不是修复成功率。
- 73 个测试与 Ruff 检查全绿；版本号由包内单一来源生成。

## 2. `models.py`：为什么先定义协议

`TaskState` 是 Agent 之间唯一共享的数据结构。使用 Pydantic 的理由：

- 输入验证：行号、置信度和问题长度有明确约束。
- 序列化：可以直接保存到 SQLite、通过 API 返回。
- 可演进：未来新增 GitHub Evidence、Benchmark Result 时不需要改变 Agent 调用方式。
- 可观测：每个阶段的状态可以直接比较和评测。

`Evidence` 不只保存文本，还保存文件、行号、关键词和来源。因为“检索到了内容”不等于“结论可追溯”。

## 3. `tools/`：为什么工具层与 Agent 分开

Agent 决定“做什么”，工具决定“怎么安全执行”。分离后可以：

- 对工具单独做单元测试。
- 用假工具测试 Agent，不访问真实文件系统。
- 后续把本地工具替换成 MCP，而不修改 Agent 逻辑。
- 给每个工具设置独立权限、超时和观测指标。

### `path_policy.py`

所有路径先 `resolve()`，再检查目标是否仍在仓库根目录内，防止 `../` 目录穿越。第一版要求 `.git` 存在，保证报告记录的 HEAD 可复现。

### `search_tools.py`

搜索优先用 `git grep -n -F -z`（git 索引、C 速度、天然只搜 tracked 文件），不可用时自动降级为纯 Python 逐行扫描——两者都用参数数组启动子进程、不经 shell。二进制（git grep 默认跳过；Python 模式前 8KB 含 NUL）与超大文件（>1MB）被跳过；所有命中先按命中数降序全量排序再截断生成证据，保证正确文件不会因为某个常见词先占满引用预算而被丢掉（阶段 B 的教训）。搜索超时约束全部子进程与降级扫描循环（deadline 安全网）。OpenCV 全库单关键词 p50 从 ~1.9s 降到 ~0.66s（-65%）。

返回值不是普通字符串，而是 `Evidence[]`，因为下游需要结构化引用和评测。

### `read_tools.py`

限制文件必须位于仓库内、限制最大字节数、限制行号范围。它解决三个问题：路径穿越、超大文件撑爆上下文、无边界读取。

### `git_tools.py`

报告记录 branch、HEAD 和 dirty 状态。否则同一个问题在不同源码版本上可能得到不同答案，却无法解释差异。

## 4. 三个 Agent 为什么这样拆

### Investigator

职责只包括关键词生成、搜索和去重，不做因果推断。这是为了降低“看到关键词就声称代码一定执行”的幻觉。

当前关键词提取保留确定性基线；使用 `--use-llm` 时，通过 `HybridQueryExpander` 合并模型候选。下一步应当在固定问题集上比较 Top-K 文件召回率，而不是直接宣称 LLM 更好。

### `query_expansion.py`

这里定义了模型无关的 `KeywordGenerator` Protocol，因此核心流程不依赖具体 LLM 客户端，测试也能注入 Fake Generator。模型输出先经过 JSON schema 检查、长度限制、换行拒绝和大小写去重，再进入只读搜索工具。即使没有 shell 权限，也要把模型输出视为不可信输入；这是为未来工具能力扩展提前建立的边界。

### `llm/deepseek.py`

适配器只获得“给一个问题，返回关键词”的窄权限，不获得仓库路径、文件读取或命令执行能力。它**用标准库 `urllib` 直接实现 OpenAI 兼容的 chat/completions 客户端**（POST `{base_url}/chat/completions`，temperature=0），不依赖任何 LLM SDK——协议透明、可测试、可审计。401 映射为配置错误（Key 无效），网络/JSON 异常抛给上层降级。

读取 API Key 延迟到 `--use-llm` 真正执行时，没有 Key 的用户仍能运行确定性版本。`.env` 被 Git 忽略，TaskState 只记录模型名、延迟和关键词，绝不保存 Key。

当前查询扩展不是 Function Calling：模型只返回 JSON，工具循环仍由确定性 Orchestrator 控制。这样更容易测试和归因。等查询召回评测稳定后，再让模型从只读工具白名单里选工具，而不是一次扩大全部权限。

### Planner

根据命中数对文件排序，并明确提醒“文本命中不等于运行时执行”。`verification_command` 目前只是报告建议，不会自动运行，因为 Phase 1 是只读调查闭环。

### Verifier

它不是另一个随意评价答案的 LLM，而是确定性门禁：结论引用的 Evidence ID 必须真实存在。这样能防止模型伪造路径或行号。

后续可以增加三层验证：

1. 引用存在性。
2. 引用是否语义支持结论。
3. 命令或测试是否支持运行时结论。

## 5. `orchestrator.py`：为什么显式状态机

每个阶段开始和结束都保存状态，因此进程在规划阶段崩溃后无需重新搜索。状态枚举还能直接统计每个阶段的失败率和耗时。

`resume()` 对已完成任务是幂等的：重复调用只重新生成同一报告，不重复执行调查。幂等性是 Agent Runtime 高频面试点。

## 6. `store.py`：为什么选择 SQLite

Phase 1 是单机、单用户场景，SQLite 提供事务、查询和零运维，比 JSON 文件更适合任务列表和并发演进。开启 WAL 是为了让未来 API 读任务时不阻塞写入。

如果扩展到多实例部署，再迁移 PostgreSQL；现在上分布式数据库属于过度设计。

## 7. CLI 与 API 为什么都要有

- CLI 适合开发、自动化和批量评测。
- FastAPI 适合接前端和演示实时任务。
- 两者都调用同一个 Orchestrator，不复制业务逻辑。

这是典型的 Ports and Adapters 思路：入口是 Adapter，核心用例保持独立。

## 8. 测试为什么这样写

测试会临时创建真实 Git 仓库，而不是假设开发机上存在某个仓库，因此在 CI 中可重复。

- 工具测试：搜索行号、路径越界、范围读取。
- 集成测试：完整状态流、持久化、报告生成。
- 幂等测试：完成任务重复恢复不改变状态。
- API 测试：HTTP 契约和核心流程集成。

## 9. 当前局限要主动说

好的面试表达不是夸大能力，而是清楚限定证据：

- 当前只能证明源码文本命中，不能证明运行时路径（需要调用图/动态执行）。
- 引用真实性已由 Verifier 回读保证（存在性 + 关键词出现在引用行），但尚未验证语义蕴含（引用是否真的支持结论）。
- 没有 GitHub Issue/PR 上下文（除评测集挖掘外）。
- 没有语义召回与 Reranker。
- 没有自动运行编译、测试或 Benchmark。
- 检索评测仍是快照偏差（未逐 case 检出 base_sha）。

## 10. DeepSeek 当前接入边界与下一阶段

DeepSeek 不直接替换整个流水线。当前只加入第一个位置：

1. 已完成：Investigator 根据问题生成检索关键词、同义词和符号候选。
2. 待评测后推进：Planner 根据 Evidence 生成原因假设和下一步只读工具调用。

工具结果、Evidence ID、Checkpoint 和确定性引用门禁继续由当前代码控制。这样既获得模型能力，又不牺牲可复现性。

## 11. 90 秒项目介绍模板

> RepoPilot 是我为大型开源仓库设计的证据驱动维护 Agent。它解决普通代码问答中引用不可追溯、长任务中断后重做，以及文本命中被误认为运行时事实的问题。系统把流程拆成证据调查、计划生成和引用核验三个阶段，通过类型化 TaskState 传递数据，并在每个阶段写入 SQLite Checkpoint。工具层默认只读，限制仓库边界、文件大小和执行超时，搜索命令不经过 Shell。查询层采用确定性基线加可选 DeepSeek 扩展，模型异常时可降级，策略、延迟和候选词都进入追踪状态。下一阶段会用历史 OpenCV Issue/PR 评测 Top-K 定位和引用准确率，再决定是否开放只读 Function Calling。
