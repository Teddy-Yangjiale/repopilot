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

1. 在查询扩展基线上评测 deterministic 与 hybrid 的 Top-K 文件召回率。
2. GitHub API/MCP 接入 Issue、PR、Review 和 CI 证据。
3. Tree-sitter 建立 C++ 符号与调用关系。
4. 在隔离 worktree 中增加白名单编译、测试和 Benchmark 工具。
5. 使用历史 OpenCV Issue/PR 构建 30～50 条评测集。
