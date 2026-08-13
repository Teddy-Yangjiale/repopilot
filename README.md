# 🔍 RepoPilot

<p align="center">
  <img src="https://img.shields.io/badge/version-0.19.0-blue" alt="version">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/tests-73%20passing-brightgreen" alt="tests">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="license">
  <img src="https://img.shields.io/badge/eval-362%20real%20cases-orange" alt="eval">
</p>

**RepoPilot 是一个证据驱动的代码仓库维护 Agent**：给定一个仓库问题，它搜索真实源码，产出**带行级引用的调查结论与验证计划**，并**拒绝没有证据支持的结论**。

> 不是"生成答案"，而是"调查并给出可验证的证据"——每一条结论都锚定真实的 `文件:行号` 引用，验证器会回读文件核对引用是否真实存在。

---

## ✨ 特性

- 🎯 **证据驱动**：结论必须锚定 `Evidence.id`（行级引用），无引用即拒绝
- 🔗 **引用真实性回读**：Verifier 回读文件，确认关键词确实出现在引用行号处
- ⚖️ **评测驱动迭代**：每次检索改动都在 362 个真实 GitHub issue（12 仓库、7 生态）上报告增量（Hit@10 0.283 → 0.767）
- 🌐 **仓库无关**：在 OpenCV（C++）、FastAPI（Python）、Go 标准库三个生态实测
- 🚀 **快**：`git grep` 后端，OpenCV 全库单关键词 0.66s（纯 Python 扫描的 1/3）
- 🧩 **零重依赖**：运行时核心仅 5 个库，LLM 客户端用标准库手写
- 🔁 **断点续跑**：SQLite checkpoint，进程中断后从阶段边界恢复
- 🛡️ **只读安全**：工具侧无 shell 执行、文件写入或任意网络访问，路径严格限制在仓库内

---

## 📖 目录

- [快速开始](#-快速开始)
- [工作原理](#-工作原理)
- [Agent Runtime](#-agent-runtime)
- [评测结果](#-评测结果)
- [详细使用教程](#-详细使用教程)
- [项目结构](#-项目结构)
- [安全边界](#-安全边界)
- [开发与测试](#-开发与测试)
- [路线图](#-路线图)
- [License](#-license)

---

## 🚀 快速开始

### 环境要求

- Python ≥ 3.11
- Git
- （可选）`gh` CLI —— 仅构建评测数据集时需要

### 安装

```bash
git clone https://github.com/Teddy-Yangjiale/repopilot.git
cd repopilot
./scripts/setup.sh           # 创建隔离的 .venv 并安装开发依赖
.venv/bin/repopilot --help
```

**可选 extras**：

```bash
pip install -e ".[dev]"       # 开发：pytest + ruff
pip install -e ".[symbols]"   # tree-sitter 定义加权（--definition-bonus）
pip install -e ".[llm]"       # 标记 LLM 支持（零额外依赖，需在 .env 配 LLM_API_KEY）
```

### 30 秒跑通

```bash
# 分析任意本地 Git 仓库（自动按判别力提取关键词）
repopilot investigate \
  --repo /path/to/any/git/repo \
  --question "How does the HTTP server handle request routing?"

# 显式指定关键词（优先级最高，不触发 LLM）
repopilot investigate \
  --repo /path/to/repo \
  --question "How does X work?" \
  --keyword SymbolA --keyword symbol_b

# 查看任务列表 & 从 checkpoint 恢复
repopilot tasks
repopilot resume <task-id>
```

输出是一份 Markdown 报告（`.repopilot/reports/<task-id>.md`），包含：**Verified findings**（带行级引用）、**Investigation plan**（下一步只读检查）、**Evidence inventory**（完整证据表）。

---

## 🧠 工作原理

```
Question ──▶ Investigator ──▶ Planner ──▶ Verifier ──▶ Markdown Report
              │ 检索+排序      │ 生成计划      │ 引用门禁
              │ keywords       │ plan          │ verified/partial/rejected
              │ evidence       │               │ (存在性 + 行号回读)
              │ ranked_files   ▼               ▼
              └──────────── SQLite Checkpoint ────────────┘
```

**三阶段流水线**：

1. **Investigator（调查员）**——只收集证据，不做因果推断。按判别力选词（符号形状 + 标题保底 + 宏过滤 + 符号族去重）→ `git grep` 检索 → IDF + 路径先验 + 通用降权排序。
2. **Planner（规划者）**——把证据转成调查计划，明确"文本命中 ≠ 运行时执行"，不发明代码事实。
3. **Verifier（验证者）**——确定性引用门禁：结论引用的 `Evidence.id` 必须真实存在，**且回读文件确认关键词出现在引用行号处**（防伪造行号/过时 snippet）。

**防幻觉四层**：检索层只收集不做因果推断 → 结论必须锚定引用 → Verifier 回读验证真实性 → 置信度封顶 0.95 + 报告声明"只证明文本命中"。

---

## 🤖 Agent Runtime

v0.19 在原有确定性调查流水线之外，提供可恢复的 **Plan → Act → Observe** 运行时。DeepSeek 通过原生 Tool Calling 选择调查动作，最终化阶段使用 JSON Output 生成逐条 Claim→Evidence 绑定；执行权和引用校验始终留在本地确定性代码中。决策与最终化分别使用 7000/9000 字符的 Context Builder，每一步的动作、观察、引用、上下文取舍、延迟和 token 用量都会写入 SQLite trajectory。

```bash
# .env 中配置 DeepSeek 兼容接口后运行
.venv/bin/repopilot agent \
  --repo /path/to/repo \
  --question "How is checkpoint recovery implemented?" \
  --max-steps 8 \
  --context-chars 7000 \
  --finalizer-context-chars 9000

# 中断或失败后从最后一个已持久化步骤继续
.venv/bin/repopilot agent-resume <run-id>

# 在真实 Issue / merged PR gold files 上评测动态 Agent
.venv/bin/repopilot agent-eval \
  --dataset datasets/opencv-issues.jsonl \
  --repo /path/to/opencv \
  --clean-only --limit 10
```

运行时只开放四个能力明确的工具：`search_code`、`read_file`、`git_history`、`finish`。它不提供任意 shell、代码执行或文件写入；同时设置步数/时间预算、拒绝重复动作，并在 `finish` 时校验每条 Claim 的引用 ID 确实来自本次 trajectory。架构对比见 [`docs/AGENT_RUNTIME.md`](docs/AGENT_RUNTIME.md)，首个动态 Agent 基准见 [`docs/AGENT_EVALUATION.md`](docs/AGENT_EVALUATION.md)。

---

## 📊 评测结果

每一次检索改动都必须在一把**公开的尺子**上报告数字。任务定义：**给定一个真实 GitHub issue，能否指出这次修复实际改动的文件？** 标准答案来自关闭该 issue 的已合并 PR——**维护者用一次真实代码评审背书**，不是人工标注。

### 主结果（362 个真实 case，12 个仓库，deterministic 策略，不调任何模型）

| 数据集 | 语言 | case 数 | Recall@10 | Hit@10 | MRR | 无泄漏 Hit@10 |
|---|---|---:|---:|---:|---:|---:|
| Redis | C | 30 | 0.808 | **0.900** | 0.674 | 0.800 |
| Guava | Java | 25 | 0.787 | 0.840 | 0.669 | 0.765 |
| Tokio | Rust | 25 | 0.648 | 0.800 | 0.538 | 0.875 |
| Vue | JS | 30 | 0.595 | 0.800 | 0.533 | 0.826 |
| OpenCV | C++ | 60 | 0.664 | 0.767 | 0.487 | 0.654 |
| Flask | Python | 30 | 0.639 | 0.767 | 0.482 | 0.800 |
| Node | Node/JS | 25 | 0.553 | 0.760 | 0.531 | 0.778 |
| Clap | Rust | 25 | 0.413 | 0.600 | 0.263 | 0.632 |
| NumPy | Python | 25 | 0.413 | 0.600 | 0.358 | 0.385 |
| FastAPI | Python | 37 | 0.414 | 0.568 | 0.271 | 0.621 |
| React | JS/TS | 30 | 0.425 | 0.533 | — | 0.520 |
| Go 标准库 | Go | 20 | 0.296 | 0.400 | 0.200 | 0.429 |

### LLM 扩展（hybrid）实测

在 OpenCV 60 case 上对比 deterministic 与 `--use-llm`（DeepSeek 查询扩展）：

| 指标 | deterministic | hybrid | 差异 |
|---|---:|---:|---:|
| Hit@10 | 0.767 | **0.817** | +0.050 |
| MRR | 0.487 | **0.569** | +0.082 |
| Hit@1 | 0.367 | **0.450** | +0.083 |
| 无泄漏 Hit@10 | 0.654 | **0.692** | +0.038 |
| 延迟 p50 | 0.66 s | 3.3 s | +5x |

无泄漏子集同样提升，说明增量来自真实召回而非正文泄漏；代价是延迟与每 case 一次模型调用。

### OpenCV 三段迭代

| 阶段 | Recall@10 | Hit@10 | MRR | 无泄漏 Hit@10 |
|---|---:|---:|---:|---:|
| 阶段 A 字面匹配基线 | 0.183 | 0.283 | 0.170 | 0.231 |
| 阶段 B（IDF + 路径先验） | 0.472 | 0.583 | 0.390 | 0.423 |
| **阶段 C（判别力选词 + git grep）** | **0.664** | **0.767** | **0.487** | **0.654** |

### 诚实性声明（主动暴露，而非被追问）

- **无泄漏子集单独报**：正文直接贴出答案路径的 case 会抬高分数（真实输入，不算作弊），所以「正文未提及答案文件」的子集单独统计——那才是诚实下界。
- **快照偏差已量化**：默认在 HEAD 快照评测（修复代码已在树里，乐观）。`--at-base` 在修复前代码上重测：Hit@10 0.767 → 0.733、MRR 0.487 → 0.410。
- **两个负收益实验如实记录**：BM25 长度归一（0.750 → 0.283）、tree-sitter 调用者召回（MRR 0.487 → 0.368）都被真实数据证伪并回退。
- 完整消融表、失败模式分析、偏差声明见 [`docs/EVALUATION.md`](docs/EVALUATION.md)。

---

## 🛠️ 详细使用教程

### 1. `investigate` —— 创建并运行一次调查

```bash
repopilot investigate \
  --repo /path/to/repo \            # 必须，已存在的 Git 仓库目录
  --question "..." \                # 必须，≥3 字符的问题
  --keyword SymbolA \               # 可选，可重复；显式指定优先级最高
  --keyword symbol_b \
  --use-llm                         # 可选，启用 DeepSeek 查询扩展（默认关闭）
```

- **关键词提取**：不传 `--keyword` 时自动按判别力提取（堆栈符号、CamelCase/snake_case 标识符优先，样板词降权）。
- **`--use-llm`**：先生成确定性关键词，再合并模型候选；模型异常自动降级为 `hybrid_fallback`（写进报告），缺 Key 显式报配置错误。评测方法见 [docs/LLM_EVAL.md](docs/LLM_EVAL.md)。
- **输出**：终端打印 `task_id / stage / evidence 数 / 查询策略 / 报告路径`，报告写在 `.repopilot/reports/`。

### 2. `tasks` / `resume` —— 任务管理与断点恢复

```bash
repopilot tasks                    # 列出最近 20 个任务
repopilot tasks --limit 50         # 自定义数量
repopilot resume <task-id>         # 从最后 checkpoint 恢复（幂等）
```

### 3. `dataset-build` —— 从真实 issue 构建评测集

```bash
repopilot dataset-build \
  --clone /path/to/repo \          # 本地克隆（提供 tracked 文件列表）
  --repo opencv/opencv \           # GitHub slug
  --out datasets/opencv-issues.jsonl \
  --limit 60 \                     # 目标 case 数
  --max-changed-files 10           # PR 改动文件数上限（过滤大重构）
  --backend graphql                # graphql（默认，issue→PR）或 rest（merged PR→closes 引用，用于 react 等）
```

- 走 `gh` CLI 的 GraphQL（认证留在你的 `gh auth` 会话，Token 不进代码/数据集）。
- 六条过滤规则（PR 必须 merged、改动 ≤10 文件、只留源码扩展名、正文 ≥80 字符、同 PR 去重、gold 文件在当前快照存在），每条丢弃多少都会打印。

### 4. `eval` —— 跑检索评测（全部开关）

```bash
repopilot eval \
  --dataset datasets/opencv-issues.jsonl \
  --repo /path/to/repo \
  --limit 0                        # 0 = 全量；正数 = 只跑前 N 个 case
```

| 开关 | 默认 | 作用 |
|---|---|---|
| `--body-chars` | 600 | 喂给检索器的 issue 正文预算（0 = 只用标题） |
| `--use-llm` | false | 启用 LLM 查询扩展 |
| `--idf / --no-idf` | 开 | IDF 加权 |
| `--vendored-penalty` | 0.1 | vendored 目录降权系数（1.0 = 关闭） |
| `--length-norm / --no-length-norm` | 关 | BM25 长度归一（实验，实测负收益） |
| `--at-base / --at-head` | head | 在 PR 修复前代码上评测（消除快照偏差） |
| `--refine-symbols` | 关 | 函数名二次检索（实验，负收益） |
| `--definition-bonus` | 0.0 | tree-sitter 定义命中加权（0 关闭，建议 1.0~1.5） |

输出写 `.repopilot/eval/<dataset>-<strategy>-body<n>-<ranking>.{json,md}`，JSON 里包含完整配置 + 每 case 明细——**脱离配置的分数没有意义，所以两者存在一起**。

### 5. REST API

```bash
make api   # 启动于 127.0.0.1:8000
```

| 端点 | 说明 |
|---|---|
| `GET /health` | 健康检查 |
| `POST /v1/tasks/investigate` | 创建并运行调查 |
| `GET /v1/tasks/{id}` | 查询任务状态 |
| `POST /v1/tasks/{id}/resume` | 从 checkpoint 恢复 |

```bash
curl -X POST http://127.0.0.1:8000/v1/tasks/investigate \
  -H 'Content-Type: application/json' \
  -d '{
    "repo_path": "/path/to/repo",
    "question": "How does the ReAct loop work?",
    "keywords": ["ReActAgent", "Finish"],
    "use_llm": false
  }'
```

### 6. 可选能力

**DeepSeek 查询扩展**（零额外依赖，标准库手写客户端）：

```bash
./scripts/setup.sh --llm
cp .env.example .env
# 编辑 .env，填写 LLM_API_KEY（不要提交）
repopilot investigate --repo ... --question ... --use-llm
```

**tree-sitter 符号增强**（可选 extra）：

```bash
pip install -e ".[symbols]"      # 安装 tree-sitter + C++ grammar
# 定义命中加权（命中函数签名行 > 命中函数体），提升 MRR ~0.06，代价是延迟
repopilot eval --dataset ... --repo ... --definition-bonus 1.5
```

---

## 📁 项目结构

```text
src/repopilot/
  agents/             Investigator / Planner / Verifier 三阶段
  runtime/            Plan-Act-Observe 循环、工具注册、trajectory 与恢复
  tools/              受控只读工具（搜索/读取/Git/路径安全）
  symbols.py          tree-sitter 符号定位（函数/定义 vs 使用）
  api.py              FastAPI 接口
  cli.py              Typer 命令行入口
  config.py           配置与路径校验
  models.py           Agent 间类型化协议（TaskState/Evidence/...）
  query_expansion.py  确定性与 LLM 混合查询扩展
  ranking.py          IDF + 路径先验 + 通用降权排序
  llm/                DeepSeek 边界适配器（OpenAI 兼容，标准库实现）
  orchestrator.py     显式状态机 + Checkpoint
  store.py            SQLite 持久化（WAL）
  report.py           可复现 Markdown 报告
  eval/               评测：数据集挖掘/指标/runner
tests/                73 个测试（单元/集成/API/Agent Runtime/Evaluation）
docs/                 评测方法与面试讲解
```

---

## 🔒 安全边界

- 仓库路径必须存在且是 Git 仓库
- **只读工具环境**：模型客户端需要访问 DeepSeek API，但模型不能发起任意网络访问；工具不提供 shell、文件写入或 Git 修改能力
- 文件读取限制在仓库根目录内，限制最大字节数（默认 200KB）
- 搜索用 `git grep`（参数数组启动，不经 shell），不可用自动降级纯 Python 扫描
- 报告明确区分 `verified` / `partial` / `rejected`

---

## 🧪 开发与测试

```bash
make lint     # ruff
make test     # pytest（73 个用例，全绿）
make demo     # 端到端演示
```

测试会临时创建真实 Git 仓库（含二进制、untracked 产物等陷阱），不依赖开发机上的任何仓库，CI 可复现。

---

## 🗺️ 路线图

- [x] 阶段 A/B/C：检索评测闭环，Hit@10 0.283 → 0.767
- [x] 引用真实性回读（Verifier 第二道闸门）
- [x] 快照偏差量化（`--at-base` 修复前代码评测）
- [x] 跨仓库评测（OpenCV / FastAPI / Go）
- [x] 去 SDK 依赖（手写 OpenAI 兼容客户端）
- [x] react 数据集（REST 挖掘：GraphQL search 对该仓库返回 0，改用 merged PR 的 closes 引用）
- [ ] 定义加权性能优化（当前 ~7x 延迟）
- [x] LLM 查询扩展的增量评测（hybrid Hit@10 0.767→0.817、MRR 0.487→0.569，延迟 5x）
- [x] 原生 Tool Calling Agent Runtime（逐步 checkpoint、预算、重复动作与引用门禁）
- [x] 首个无路径泄漏 Agent 小基准（OpenCV 10 case，完成率 1.00，final gold-file hit 0.70）
- [ ] 扩展到 20–30 case，并增加 PR base snapshot 与语义支持度评测
- [ ] GitHub Issue/PR/Review 作为新证据源

---

## 📄 License

[MIT](LICENSE) © 2026 Teddy Yangjiale
