# RepoPilot 动态 Agent 评测

## 1. 评测问题

仅证明模型“会调用工具”不足以支撑简历项目。动态 Agent 评测回答的是：给定维护者真实提交的 Issue，Agent 能否在有限步骤内结束调查，并让最终引用命中关闭该 Issue 的 merged PR 实际修改文件？

Gold files 自动来自 merged PR，不做人工标注。`--clean-only` 排除 Issue 正文已经直接写出任一 gold file 路径的样本，避免靠路径泄漏抬高成绩。

## 2. 复现命令

```bash
.venv/bin/repopilot agent-eval \
  --dataset datasets/opencv-issues.jsonl \
  --repo /home/teddy/opencv \
  --out .repopilot/agent-eval \
  --clean-only \
  --limit 10 \
  --max-steps 8 \
  --timeout-seconds 120 \
  --body-chars 1200 \
  --at-head
```

每个 case 保存完整 Action/Observation trajectory；整轮同时输出 JSON 和 Markdown。默认只运行 5 个付费模型 case，必须显式提高 `--limit`。

## 3. 2026-08-14 首个稳定小基准

- Dataset：OpenCV 真实 Issue，clean subset 前 10 个 case
- Snapshot：repository HEAD `f1e824b88ad8`
- Model：`deepseek-v4-flash`
- Budget：每 case 8 steps / 120 seconds
- Question body：前 1200 字符

| 指标 | 结果 |
|---|---:|
| 完成率 | 1.000 |
| 任意 Evidence 命中 gold file | 0.700 |
| 最终引用命中 gold file | 0.700 |
| Gold-file recall | 0.563 |
| Claim 引用覆盖 | 1.000 |
| 引用 ID 完整性 | 1.000 |
| Tool-error step rate | 0.059 |
| 平均步骤 | 6.8 |
| 平均 tokens | 23,816 |
| 延迟 p50 / p95 | 15.7 s / 22.2 s |
| 过期读取范围自动重定位 | 8 次 |

## 4. 失败驱动的迭代证据

第一次在 3 个路径泄漏 case 上运行时，底层 Evidence 3/3 命中 gold file，但 Agent 0/3 完成：模型持续阅读直到 8 步耗尽。加入末步停止约束后，相同 3 case 完成率变为 1.00。

随后在 5 个 clean case 上发现 `deepseek-v4-flash` 即使只收到 `finish` schema，也可能返回历史工具。运行时因此把“动作选择”和“最终化”拆开：调查阶段使用 Tool Calling，停止后使用 JSON Output 生成逐条 Claim→Evidence，再执行本地引用门禁。

Issue 的行号经常相对 HEAD 漂移。`read_file` 现在只允许读取本次搜索发现的路径；若 focus keyword 不在请求范围，则在同一受控文件中确定性重定位到最近真实命中，并在 Observation 记录 requested/effective range。10-case 稳定运行中共触发 8 次重定位。

## 5. 指标边界

- `completed_rate` 只证明运行时在预算内产生了通过结构门禁的答案。
- `final_hit_rate` 证明至少一个最终引用文件出现在 merged PR 的修改文件中，不证明 Agent 找全了修复范围。
- `claim_citation_coverage` 与 `citation_integrity` 证明每条 Claim 都绑定了本次真实收集的 Evidence ID，不证明引用在语义上充分支持整条 Claim。
- 当前结果在 HEAD 快照运行，修复代码可能已经存在，因此仍可能偏乐观。
- 这不是 patch/build/test 成功率，更不是 SWE-bench resolved rate。

## 6. 下一步

1. 扩展到 20–30 个 clean case，并报告不同失败类型的置信区间。
2. 使用 `--at-base` 在每个 PR 的 pre-merge commit 上复测，量化 HEAD snapshot 偏差。
3. 增加独立的 Claim–Evidence 语义支持度评测，避免把“引用存在”误写成“结论正确”。
4. 完成只读评测后，再开放隔离 worktree 内的 patch/build/test/diff 工具。

## 7. v0.19 上下文离线重放

Context Builder 首先在 v0.18 保存的同一批 10 个 clean-case trajectory 上离线重放。它重建每次模型调用前的 AgentRun 前缀，对比旧版机械拼接和新版分阶段选择；不重新调用模型。

| 指标 | v0.18 | v0.19 | 变化 |
|---|---:|---:|---:|
| 决策上下文平均字符 | 5469.3 | 4839.3 | -11.5% |
| 决策上下文 p95 | 11740 | 6950 | -40.8% |
| 决策上下文最大值 | 无总预算 | 6970 | ≤ 7000 |
| 最终化上下文平均字符 | 9994.7 | 8015.1 | -19.8% |
| 最终化上下文最大值 | 无总预算 | 8985 | ≤ 9000 |

样本包含 59 次决策调用和 9 次最终化调用。离线重放证明预算、选择和可观测性实现符合预期，但不能证明 final gold-file hit 或回答质量保持不变；后者必须在提供 DeepSeek Key 后做在线 A/B。

复现命令：

```bash
repopilot context-replay \
  --database .repopilot/agent-eval-v018-clean-n10/agent_eval.db
```
