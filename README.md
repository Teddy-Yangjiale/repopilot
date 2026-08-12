# RepoPilot

RepoPilot 是一个面向大型代码仓库的**证据驱动维护 Agent**。它接收一个仓库问题，搜索真实源码，生成带引用的调查结论和验证计划，并拒绝没有证据支持的结论。

当前是 Phase 1 脚手架，目标是建立可靠的最小闭环：

```text
Question -> Investigator -> Planner -> Verifier -> Markdown Report
                    |            |          |
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

## 项目结构

```text
src/repopilot/
  agents/             Investigator / Planner / Verifier
  tools/              受控只读工具
  api.py              FastAPI 接口
  cli.py              命令行入口
  config.py           配置与路径校验
  models.py           Agent 间的类型化协议
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
    "keywords": ["ReActAgent", "invoke_with_tools", "Finish"]
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

1. DeepSeek + HelloAgents 负责关键词扩展、假设生成和 Function Calling。
2. GitHub API/MCP 接入 Issue、PR、Review 和 CI 证据。
3. Tree-sitter 建立 C++ 符号与调用关系。
4. 在隔离 worktree 中增加白名单编译、测试和 Benchmark 工具。
5. 使用历史 OpenCV Issue/PR 构建 30～50 条评测集。
