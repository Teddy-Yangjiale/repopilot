# LLM 查询扩展评测

本文档说明如何评测「确定性检索」与「LLM 增强检索（hybrid）」的增量。当前所有发布的评测数字都来自 deterministic 策略（不调任何模型，零成本、可复现）；LLM 扩展的增量**尚未系统评测**，这是明确的待办项。

## 1. 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek Key
# LLM_API_KEY=sk-...
# LLM_MODEL_ID=deepseek-v4-flash
# LLM_BASE_URL=https://api.deepseek.com
# LLM_TIMEOUT=120
```

`--use-llm` 缺 Key 时会**在跑第一个 case 前快速失败**（exit code 2），不会浪费整轮评测。

## 2. 评测命令

```bash
# deterministic 基线（不调模型）
.venv/bin/repopilot eval \
  --dataset datasets/opencv-issues.jsonl \
  --repo /home/teddy/opencv

# hybrid（确定性关键词 + 模型候选合并）
.venv/bin/repopilot eval \
  --dataset datasets/opencv-issues.jsonl \
  --repo /home/teddy/opencv \
  --use-llm
```

两个 run 输出到不同的 `.json/.md`（文件名含 strategy：`deterministic` vs `hybrid`），可并排对比。

## 3. 对比维度

| 维度 | 怎么看 | 期望 |
|---|---|---|
| **Hit@10 / Recall@10 / MRR** | 两栏直接对比 | hybrid 应 ≥ deterministic（模型补充同义词/符号候选） |
| **无泄漏子集** | clean_hit@10 | 关注是否靠正文泄漏提升，还是真召回 |
| **延迟** | latency_p50_ms | hybrid 明显更高（每 case 一次模型调用） |
| **费用** | case 数 × 模型调用次数 | deterministic 是 0 |
| **降级率** | 报告里的 hybrid_fallback 计数 | 模型超时/坏 JSON 时自动降级，应可接受 |

## 4. 已知行为

- **策略标记**：报告 `Query strategy` 字段区分 `deterministic` / `hybrid` / `hybrid_fallback`。
- **两类错误**：配置错误（缺 Key/占位符/401）显式失败；运行时错误（超时/坏 JSON）降级为确定性基线并记录 warning。
- **显式 `--keyword` 优先**：传了 `--keyword` 就不会触发模型（零费用），这是评测 deterministic 的路径。

## 5. 实测结果（OpenCV 60 case，deepseek-v4-flash）

| 指标 | deterministic | hybrid | 差异 |
|---|---:|---:|---:|
| Hit@10 | 0.767 | 0.817 | +0.050 |
| MRR | 0.487 | 0.569 | +0.082 |
| Hit@1 | 0.367 | 0.450 | +0.083 |
| 无泄漏 Hit@10 | 0.654 | 0.692 | +0.038 |
| 延迟 p50 | 0.66 s | 3.3 s | +5x |

- 60 case 全部成功（errors=0），无 hybrid_fallback 降级。
- **增量来自真实召回**：无泄漏子集（正文未提及答案文件）同样 +0.038，不是靠正文泄漏。
- 代价：延迟 ~5 倍 + 每 case 一次模型调用（60 次，费用可忽略但不可复用为 0）。

## 6. 建议的评测设计

1. 先在**小样本**（`--limit 10`）上跑，确认 Key/网络/解析正常。
2. 再跑全量对比，记录 Hit@10 / MRR / 延迟 / 费用的四维增量。
3. 若 hybrid 增量不显著，说明确定性选词已经够好——这也是有效结论（证明不必为 LLM 付费用）。
