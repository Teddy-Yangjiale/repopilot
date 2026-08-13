# RepoPilot

RepoPilot 是一个面向大型代码仓库的**证据驱动维护 Agent**。它接收一个仓库问题，搜索真实源码，生成带引用的调查结论和验证计划，并拒绝没有证据支持的结论。

当前状态：只读闭环（检索 → 引用 → 计划 → 验证 → 报告）已跑通；可选 DeepSeek 查询扩展；检索在 60 个真实 OpenCV issue 上以「合并 PR 改动文件」为答案评测（Hit@10 0.283 → 0.750，三段迭代，全部数字可复现）：

```text
Question -> Investigator -> Planner -> Verifier -> Markdown Report
               ^    |            |          |
  Deterministic + optional LLM    |          |
                Evidence      Plan   Citation Gate
                  |             |    (存在性 + 行号回读)
                    \________ SQLite Checkpoint ________/
```

## 为什么先做只读版本

自动修改代码的风险远高于代码搜索。第一阶段先验证三件事：能否找到正确文件、能否形成可追溯结论、能否在中断后恢复。等这些指标稳定，再增加补丁生成、编译和 Benchmark 工具。

## 立即运行

```bash
cd /home/teddy/repopilot
./scripts/setup.sh

# 分析任意本地 Git 仓库（--repo 接受任何仓库，不限于特定语言或项目）
.venv/bin/repopilot investigate \
  --repo /home/teddy/repos/fastapi \
  --question "How does FastAPI build the OpenAPI schema from dependencies?"
# 关键词会自动按判别力提取；也可显式指定（优先级最高）：
.venv/bin/repopilot investigate \
  --repo /home/teddy/hello-agents-lab/references/hello-agents-framework \
  --question "How does ReActAgent execute tools and stop?" \
  --keyword ReActAgent --keyword invoke_with_tools --keyword Finish

# 查看任务列表
.venv/bin/repopilot tasks

# 从 Checkpoint 恢复
.venv/bin/repopilot resume <task-id>

# 启动 API
make api
```

如果不传 `--keyword`，系统会按判别力自动提取关键词（符号形状 + 标题保底 + 宏过滤 + 符号族去重），并在排序时对 vendored 依赖与文档/变更日志类文件做通用降权——这两类几乎从不是代码修复的目标位置，规则是通用约定，不针对任何单一仓库调参。

### 可选：使用 DeepSeek 扩展查询

基础流程不需要任何 API Key。只有显式传入 `--use-llm` 时，RepoPilot 才会调用 OpenAI 兼容的 DeepSeek API——客户端用标准库手写（`llm/deepseek.py`，零 SDK 依赖，协议透明）：

```bash
./scripts/setup.sh --llm
cp .env.example .env
# 编辑 .env，只填写你自己的 LLM_API_KEY；不要提交这个文件

.venv/bin/repopilot investigate \
  --repo /home/teddy/hello-agents-lab/references/hello-agents-framework \
  --question "How does ReActAgent execute tools and stop?" \
  --use-llm
```

混合策略会先生成确定性关键词，再合并模型给出的符号候选。网络或模型输出异常时自动退回确定性基线，并把 `hybrid_fallback` 和错误摘要写进任务状态；缺少 API Key 或依赖则直接给出配置错误，避免用户误以为模型已生效。显式 `--keyword` 的优先级最高，不会额外产生模型费用。

## 项目结构

```text
src/repopilot/
  agents/             Investigator / Planner / Verifier
  tools/              受控只读工具
  api.py              FastAPI 接口
  cli.py              命令行入口
  config.py           配置与路径校验
  models.py           Agent 间的类型化协议
  query_expansion.py  确定性与 LLM 混合查询扩展
  llm/                DeepSeek 边界适配器（OpenAI 兼容，标准库实现）
  orchestrator.py     状态机与 Checkpoint 边界
  store.py            SQLite 持久化
  report.py           可复现 Markdown 报告
tests/                 单元测试、集成测试和 API 测试
docs/INTERVIEW_GUIDE.md 逐文件面试讲解
```

## API

```bash
curl -X POST http://127.0.0.1:8000/v1/tasks/investigate \
  -H 'Content-Type: application/json' \
  -d '{
    "repo_path": "/home/teddy/hello-agents-lab/references/hello-agents-framework",
    "question": "How does the ReAct loop work?",
    "keywords": ["ReActAgent", "invoke_with_tools", "Finish"],
    "use_llm": false
  }'
```

## 检索评测（阶段 A）

RepoPilot 的每一次检索改动都必须先在一把公开的尺子上报数字。任务定义是：**给定一个真实 GitHub issue，能否指出这次修复实际改动的文件？** 标准答案来自关闭该 issue 的已合并 PR —— 不是人工标注，而是维护者用一次真实代码评审背书过的。

```bash
# 构建数据集（走你已有的 gh auth 会话，Token 不进代码）
.venv/bin/repopilot dataset-build --clone /home/teddy/opencv \
  --out datasets/opencv-issues.jsonl --limit 60

# 跑评测
.venv/bin/repopilot eval --dataset datasets/opencv-issues.jsonl --repo /home/teddy/opencv
```

**当前结果**（60 个 OpenCV case，`deterministic` 策略，不调用任何模型）：

| 阶段 | Recall@10 | Hit@10 | MRR | 无泄漏 Hit@10 | 延迟 p50 |
|---|---:|---:|---:|---:|---:|
| 阶段 A 字面匹配基线 | 0.183 | 0.283 | 0.170 | 0.231 | 3.4 s |
| 阶段 B（IDF + 路径先验） | 0.472 | 0.583 | 0.390 | 0.423 | 2.8 s |
| **阶段 C（判别力选词 + git grep 后端）** | **0.664** | **0.767** | **0.487** | **0.654** | **0.66 s** |
| 阶段 C @ 修复前代码（base 快照，官方仓库） | 0.608 | 0.733 | 0.410 | 0.615 | 0.62 s |
| fastapi（37 case，判别力选词） | 0.414 | 0.568 | 0.271 | 0.621 | 0.23 s |

阶段 A 的基线低得很有规律：top-3 预测有 61% 落在 `3rdparty/` 下，而标准答案里占比是 0%。根因是字面匹配没有 IDF、没有路径先验。诊断把失败劈成两半：21/60 是排序问题（正确文件已在候选集，只是排名 > 10），22/60 是召回问题（从未被检索到）。

阶段 B 只改排序，**排序问题从 21 个降到 5 个，召回问题几乎没动（22 → 20）—— 与诊断预测一致**，`3rdparty/` 在 top-3 的占比降到 0.0%。四臂消融显示 IDF 是最大单项贡献，路径先验主要改善 top-1（Hit@1 0.150 → 0.300）。

阶段 C 改的是关键词抽取而非排序：抽取器从「取正文前 6 个 token」改为按判别力选词——堆栈里的符号（`icvCvt_BGRA2RGBA_16u_C4R`）现在会进入关键词，报告样板词（`System`/`Information`）不再挤占名额；编译宏（`-DOPENCV_*`）被剥离，同一符号族的兄弟 case（`int32x4_CPP_EMULATOR` 系列）只保留一个代表。**检索到的正确文件数（Hit@10 的命中池）从 35/60 升到 45/60**，正文未提及答案文件的严格子集上 Hit@10 从 0.423 提到 0.615（+45%）。延迟 p50 约 1.9s，与阶段 B 同量级——关键词抽取不改变逐文件扫描成本，延迟差异主要来自测量环境，不归功于本阶段。

诚实的下界：在「正文未提及答案文件」的最严格子集上，Hit@10 从 0.231（阶段 A）→ 0.423（阶段 B）→ 0.615（阶段 C）。完整消融表、归因和局限见 [docs/EVALUATION.md](docs/EVALUATION.md)。

**快照偏差已量化**：默认评测在仓库 HEAD 快照上跑（修复代码已在树里，乐观）。`--at-base` 模式在官方仓库上逐 case 检出 PR 的 base commit（修复前代码）评测——Hit@10 从 0.767 降到 0.733、MRR 0.487 → 0.410，这就是乐观偏差的实测幅度。跨仓库验证：fastapi 数据集（37 case）Hit@10 0.568，正文未提及答案文件的子集 0.621。

方法、过滤规则、三条已知偏差和完整失败模式分析见 [docs/EVALUATION.md](docs/EVALUATION.md)。

## 安全边界

- 仓库路径必须存在且是 Git 仓库。
- 第一阶段不提供 shell 执行、文件写入、网络访问或 Git 修改工具。
- 文件读取限制在仓库根目录内部，并限制最大字节数。
- 搜索优先用 `git grep`（git 索引、C 速度、天然只搜 tracked 文件），不可用时自动降级为纯 Python 逐行扫描；两者都用参数数组启动子进程、不经 shell。OpenCV 全库单关键词 p50 从 ~1.9s 降到 ~0.66s（-65%）。
- 报告明确区分 `verified`、`partial` 和 `rejected`。

## 验证

```bash
make lint
make test
make demo
```

## 下一阶段

阶段 A（评测集 + 基线）、阶段 B（IDF + 路径先验）和阶段 C（判别力选词）已完成，以下按优先级排列，每一项都必须报出相对基线的增量：

1. ~~**关键词抽取**~~ **已完成（阶段 C）**：按判别力选词（符号形状 + 标题保底 + 宏过滤 + 符号族去重），Hit@10 0.583 → 0.750，无泄漏子集 0.423 → 0.615。
2. ~~**文档长度归一（BM25 补完）**~~ **实测负收益，已回退**：BM25 长度归一假设「长度≈冗余度」，对代码仓库方向性错误（大文件=核心实现，实测 Hit@10 0.750 → 0.283）。代码与 `--length-norm` 实验开关保留，默认关闭；行数统计已进入搜索协议，留给更合适的归一形式。
3. ~~**让 Verifier 真正能拒绝**~~ **引用真实性回读已完成（阶段 E）**：验证器回读文件确认关键词出现在引用行号处，抓伪造行号；过程中暴露并修复了证据去重键与回读缓存两个数据流 bug。LLM 综合结论与幻觉拒绝率统计留待后续。
4. ~~**Tree-sitter 调用关系**~~ **caller-recall 实测负收益，已回退**：命中行的外围函数名二次检索会召回大量调用点/声明/测试噪声，把正确文件挤出 top（MRR 0.487 → 0.368、延迟 3 倍）。tree-sitter 基础设施（`symbols.py` + `--refine-symbols` 开关）保留。正确方向是「定义 vs 使用」加权：问题符号的定义命中才高权，调用点命中不额外加分。
5. ~~**按 `EvalCase.base_sha` 逐 case 检出父提交**~~ **已完成**：`--at-base` 模式用临时 worktree 在官方仓库的修复前代码上评测，快照偏差实测为 Hit@10 0.767 → 0.733。
6. GitHub Issue/PR/Review 作为新证据源；`git blame` 回答「这行为什么长这样」。
