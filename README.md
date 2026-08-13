# RepoPilot

RepoPilot 是一个面向大型代码仓库的**证据驱动维护 Agent**。它接收一个仓库问题，搜索真实源码，生成带引用的调查结论和验证计划，并拒绝没有证据支持的结论。

当前已完成 Phase 1 只读闭环，并在 Phase 2 加入可选的 DeepSeek + HelloAgents 查询扩展：

```text
Question -> Investigator -> Planner -> Verifier -> Markdown Report
               ^    |            |          |
  Deterministic + optional LLM    |          |
                Evidence      Plan       Citation Gate
                    \________ SQLite Checkpoint ________/
```

## 为什么先做只读版本

自动修改代码的风险远高于代码搜索。第一阶段先验证三件事：能否找到正确文件、能否形成可追溯结论、能否在中断后恢复。等这些指标稳定，再增加补丁生成、编译和 Benchmark 工具。

## 立即运行

```bash
cd /home/teddy/repopilot
./scripts/setup.sh

# 分析任意本地 Git 仓库
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

如果不传 `--keyword`，系统会从问题中提取英文标识符和较长的中文词片段。为了演示稳定，面试时建议显式传入 2～5 个领域关键词。

### 可选：使用 DeepSeek 扩展查询

基础流程不需要任何 API Key。只有显式传入 `--use-llm` 时，RepoPilot 才会通过 HelloAgents 调用 OpenAI 兼容的 DeepSeek API：

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
  llm/                HelloAgents / DeepSeek 边界适配器
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

| 排序配置 | Recall@10 | Hit@10 | MRR | 延迟 p50 |
|---|---:|---:|---:|---:|
| 阶段 A 字面匹配基线 | 0.183 | 0.283 | 0.170 | 3.4 s |
| **阶段 B（IDF + 路径先验）** | **0.472** | **0.583** | **0.390** | **2.8 s** |

阶段 A 的基线低得很有规律：top-3 预测有 61% 落在 `3rdparty/` 下，而标准答案里占比是 0%。根因是字面匹配没有 IDF、没有路径先验。诊断把失败劈成两半：21/60 是排序问题（正确文件已在候选集，只是排名 > 10），22/60 是召回问题（从未被检索到）。

阶段 B 只改排序，**排序问题从 21 个降到 5 个，召回问题几乎没动（22 → 20）—— 与诊断预测一致**，`3rdparty/` 在 top-3 的占比降到 0.0%。四臂消融显示 IDF 是最大单项贡献，路径先验主要改善 top-1（Hit@1 0.150 → 0.300）。

诚实的下界：在「正文未提及答案文件」的最严格子集上，Hit@10 是 0.231 → 0.423。完整消融表、归因和两条局限见 [docs/EVALUATION.md](docs/EVALUATION.md)。

方法、过滤规则、三条已知偏差和完整失败模式分析见 [docs/EVALUATION.md](docs/EVALUATION.md)。

## 安全边界

- 仓库路径必须存在且是 Git 仓库。
- 第一阶段不提供 shell 执行、文件写入、网络访问或 Git 修改工具。
- 文件读取限制在仓库根目录内部，并限制最大字节数。
- 搜索工具使用参数数组启动子进程，不经过 shell，减少命令注入风险。
- 报告明确区分 `verified`、`partial` 和 `rejected`。

## 验证

```bash
make lint
make test
make demo
```

## 下一阶段

阶段 A（评测集 + 基线）和阶段 B（IDF + 路径先验）已完成，以下按优先级排列，每一项都必须报出相对基线的增量：

1. **关键词抽取**：当前取正文前 6 个 token，够不到堆栈里的符号 —— 这是仅存的大头，20/60 个 case 的正确文件从未被检索到。改为按判别力选词。
2. **文档长度归一（BM25 补完）**：处理内嵌 googletest 这类目录名不符合通用 vendored 约定的大文件，不靠仓库特有的特例。
3. 让 Verifier 真正能拒绝：引入 LLM 综合结论，验证器回读文件核对引用行号，报告幻觉拒绝率。
4. Tree-sitter 建立 C++ 符号与调用关系，把「文本命中」升级为「调用路径」。
5. 按 `EvalCase.base_sha` 逐 case 检出父提交，消除快照评测的乐观偏差。
6. GitHub Issue/PR/Review 作为新证据源；`git blame` 回答「这行为什么长这样」。
