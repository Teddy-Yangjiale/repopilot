# RepoPilot 面试准备手册（100 题模拟拷打）

> 使用方式：先读「项目定位」一分钟版，再按主题逐题自测——先自己答，再看答案。
> 答案都是要点式，面试时展开成"问题—取舍—实现—验证"四步。

## 项目定位（先背这一分钟）

**一句话**：RepoPilot 是一个**证据驱动的代码仓库维护 Agent**——给定一个仓库问题，它搜索真实源码，产出带行级引用的调查结论与验证计划，并**拒绝没有证据支持的结论**。

**三句话版本**（90 秒介绍）：
1. 我把流程拆成显式状态机（Investigator 收集证据 → Planner 生成计划 → Verifier 验证引用 → SQLite Checkpoint → Markdown 报告），任何阶段失败都可归因、可恢复。
2. 检索用确定性算法（判别力选词 + IDF + 路径先验 + 通用降权），LLM 只做可选的查询扩展并自动降级；我在 60 个真实 OpenCV issue 上建立了评测集，用合并 PR 改动文件当标准答案，Hit@10 从 0.283 迭代到 0.750。
3. 防幻觉是硬约束：每条结论必须锚定 `Evidence.id`，Verifier 会回读文件确认关键词确实出现在引用行号处——它上线第一天就抓出了两个真实的数据流 bug。

**为什么不说是"AI 代码搜索工具"**：定位是"Agent"——有流程（多阶段）、有状态（checkpoint）、有判断（拒绝无证据结论）、有验证（引用门禁）。搜索只是第一阶段的手段。

---

## 一、动机与定位（8 题）

**Q1. 为什么不做一个大 Prompt 的问答机器人？**
A: ①失败不可归因——召回错、规划错、验证错混在一起，无法定位；②长任务中断全丢，无法恢复；③无评测——"好用"无法量化。显式状态机让三件事可观测：每阶段单独评测、从 checkpoint 恢复、统计每阶段失败率。

**Q2. 为什么第一版是只读的，不直接做自动改代码？**
A: 自动修改的风险远高于搜索。先验证三件基础能力：能否找到正确文件、能否形成可追溯结论、能否在中断后恢复。这三件稳定了，补丁生成才有意义。阶段式推进也方便面试表达："我先把地基做对，再往上盖"。

**Q3. 你的项目解决什么问题？给一个真实场景。**
A: 大型仓库里"这 bug 在哪"比"怎么改"更难。OpenCV 一个 issue 里贴着堆栈和编译日志，维护者要人肉翻几千个文件。RepoPilot 把"文本命中"和"证据可追溯"分开——告诉你哪个文件、哪几行、为什么（命中了哪个关键词），并拒绝没有行级引用的结论。

**Q4. 为什么用评测集而不是拍脑袋说"效果很好"？**
A: 没有尺子，任何"换成 BM25 会更好""加 LLM 有用"都无法证伪。我把每次检索改动都绑定在一个可复现的评测上：60 个真实 issue，标准答案是维护者用真实代码评审背书过的合并 PR 改动文件。数字是说服面试官的唯一硬通货。

**Q5. 你的核心创新点是什么？**
A: 三个：①评测驱动迭代（每步改动报增量，阶段 D 的 BM25 负收益被真实数据证伪）；②确定性防幻觉闭环（Evidence.id 引用链 + Verifier 回读文件）；③概率增强、确定性兜底（LLM 只做查询扩展，失败降级为规则结果，策略/延迟/候选词全部入 trace）。

**Q6. 和 GitHub Copilot / ChatGPT 有什么区别？**
A: 那些是"生成答案"，我是"调查并给出可验证的证据"。Copilot 不告诉你引用行号对不对；RepoPilot 的结论如果没有真实行级证据就直接拒绝。定位是维护者的事前调查工具，不是写代码助手。

**Q7. 项目规模多大，你写了多少行？**
A: 诚实回答：核心 src 约 2500 行（25 个文件），测试 8 个文件 38 个用例，评测基础设施（数据集挖掘/指标/runner）在内。重点是设计密度——状态机、双闸门验证、可消融排序、评测闭环，不是行数。

**Q8. 这个项目为什么适合写进简历？**
A: ①有完整闭环：问题→检索→引用→计划→验证→报告→评测；②有量化结果：三段评测数字 + 诚实记录一次失败；③有工程严谨性：安全边界、超时全覆盖、可复现性、lint/test 门禁；④有 Agent 工程深度：幻觉防御、LLM 降级、checkpoint、证据协议。

---

## 二、总体架构与设计决策（9 题）

**Q9. 画出你的系统架构。**
A: 六层：入口（CLI/FastAPI）→ DI 容器（lru_cache 单例）→ 编排器（显式状态机）→ 领域层（TaskState + 三 Agent）→ 工具层（只读：搜索/读取/Git/路径安全）→ 基础设施（SQLite/报告/LLM 适配器/评测）。数据流：Question → Investigator（keywords/evidence/ranked_files/findings）→ Planner（plan）→ Verifier（verification）→ report.md。

**Q10. 为什么用显式状态机而不是隐式回调或大循环？**
A: 显式状态迁移让"现在在哪、下一步是什么"可观察：①断点续跑只需按 stage 判断从哪继续；②评测可统计每阶段耗时与失败率；③state 序列化后就是 checkpoint。隐式流程（如单循环 while）无法回答"任务跑到哪了"。

**Q11. 三个 Agent 为什么这样拆？边界在哪？**
A: Investigator 只收集证据、不做因果推断（降幻觉）；Planner 把证据转成调查计划、不发明代码事实；Verifier 做确定性引用门禁、不用 LLM 判断。边界原则：每个 Agent 写自己的 state 字段，互不越权，接口只有 TaskState。

**Q12. 状态机里数据是怎么传的？为什么用同一个可变对象？**
A: 所有 Agent 原地修改同一个 `TaskState`（Pydantic 模型）。优点：单一事实来源、checkpoint 直接序列化、阶段间无拷贝开销。代价：Agent 之间耦合在 TaskState 上——通过模型约束和字段职责注释缓解。

**Q13. CLI 和 API 为什么都要？不是重复吗？**
A: Ports & Adapters：CLI 服务开发/自动化/批量评测，FastAPI 服务前端/演示。两者都调同一个 `get_orchestrator()`，业务逻辑零复制。面试点：入口是 Adapter，核心用例保持独立，未来换 gRPC 也不动领域层。

**Q14. 为什么用 lru_cache 做单例？有什么坑？**
A: `@lru_cache(maxsize=1)` 保证进程内一个 orchestrator（加载一次 .env、建一次 SQLite 连接工厂）。坑：单例状态在测试间泄漏——测试用 `cache_clear()` + monkeypatch 替换（test_api.py 里有完整例子）。

**Q15. 如果任务中途进程被杀，会发生什么？**
A: 每阶段边界都 `store.save(state)`（SQLite）。进程死了，任务停在最后一个 checkpoint 的 stage；`resume(task_id)` 按 stage 从对应 Agent 继续，不重跑已完成阶段。已完成任务 resume 是幂等的（只重生成报告，测试保证）。

**Q16. 你的系统是同步的，为什么不异步？**
A: 当前是单机交互式工具，同步 + FastAPI 线程池够用。代价是长任务阻塞请求线程——如果做 SSE 实时流（README 下一阶段），需要把 orchestrator 改 async、搜索改协程。这是明确的已知取舍，不是盲点。

**Q17. 容器/依赖注入怎么做的？依赖了哪些外部库？**
A: `container.py` 手工组装（无 DI 框架）：Investigator 注入 CodeSearchTool + HybridQueryExpander，Verifier 注入 SafeFileReader，Orchestrator 注入三 Agent + GitInspector + TaskStore。外部依赖仅 6 个（fastapi/pydantic/dotenv/typer/uvicorn + 可选 hello-agents），零重量级框架——面试可展开"为什么不用 FastAPI DI 或依赖注入框架"（避免隐式魔法，显式可测）。

**Q18. 项目结构为什么 src-layout？**
A: src-layout 强制"从仓库外导入"（import repopilot 而非直接 import 目录），避免源码目录污染 sys.path、防止测试导入到本地而非安装版本；配合 editable install（pip install -e）开发即生效。面试可谈 setuptools find 配置。

---

## 三、数据模型与协议（7 题）

**Q19. TaskState 为什么用 Pydantic？**
A: ①输入验证（行号、置信度 0~1、问题长度）；②序列化（model_dump_json → SQLite / HTTP）；③可演进（加字段不改 Agent 调用方式）；④可观测（每阶段状态可直接比较）。

**Q20. Evidence 为什么保存 path/line_start/line_end/snippet/keyword 而不是只存文本？**
A: "检索到了内容"≠"结论可追溯"。行级引用（citation = `path:start-end`）让下游 Verifier 能回读验证、让报告能精确展示、让评测能统计。keyword 记录这条证据由哪个词触发——这是我修复过的一个 bug 的来源（去重键缺 keyword 导致证据错标）。

**Q21. TaskStage 有哪些值？为什么 FAILED 也要持久化？**
A: created/investigating/planning/verifying/completed/failed。FAILED 持久化让 resume 能区分"从未开始"和"失败过"——失败任务 resume 会清 error、回到 investigating 重试，且保留失败原因供审计。

**Q22. 置信度（confidence）怎么算的？为什么封顶 0.95？**
A: 启发式 `min(0.95, 0.55 + keyword_count * 0.1)`——命中关键词越多越可信，但永不宣称 100%（检索只能证明文本命中，不能证明运行时行为）。面试点：宁可低估，不可高估。

**Q23. QueryExpansionTrace 里记了什么？为什么？**
A: strategy（explicit/deterministic/hybrid/hybrid_fallback）、baseline_keywords、llm_keywords、model、latency_ms、warning。可审计：报告里能看出这次查询词是怎么来的、模型是否参与、是否降级。这是"可复现性"的设计体现。

**Q24. 模型字段变更怎么迁移？**
A: 当前无 schema 版本机制（已知局限）——CREATE TABLE IF NOT EXISTS 隐式演进。诚实回答：单表单版本可行；多版本需要 schema_version 表 + 迁移脚本，这是 store.py 的下一步。

**Q25. 为什么 RankedFile 要持久化？**
A: 注释原话："ranking *is* the retrieval answer"——排序结果本身就是检索的答案，评估、复现、调试都依赖它，不能只算不存。

---

## 四、检索与关键词抽取（10 题）

**Q26. 关键词是怎么自动提取的？**
A: 判别力选词（阶段 C）：①正则提取英文标识符/中文片段；②按符号形状评分（大写=类名 +3、下划线 +2、数字 +1、长词 +1、常见词 -5）；③标题词有小额保底（作者意图，但不能太大——实测 +8 保底让泛化标题词挤掉正文真符号，Hit@10 0.750→0.650）；④正文只挖"像符号"的 token（堆栈痕迹），模板词（System/Information）进不来；⑤剥离编译宏（-DOPENCV_*）、过滤 _Complex 类宏；⑥符号族去重（int32x4_CPP_EMULATOR 与 float64x2_CPP_EMULATOR 同族只留一个）。

**Q27. 阶段 C 之前的问题是什么？具体数字？**
A: 之前取"正则匹配的前 6 个 token"。OpenCV issue 模板正文开头是 `System Information / OpenCV version` 样板词，真正有价值的堆栈符号永远够不到。阶段 A/B 的失败结构：22/60 是召回问题（正确文件从未被检索到）。阶段 C 后召回问题降到 8 个。

**Q28. 混合策略（hybrid）是什么？**
A: 确定性提取是基线（零成本、可复现），可选 LLM（DeepSeek）补充同义词/符号候选：`merge_keywords(baseline, llm_keywords, limit=10)`。模型失败（超时/坏 JSON）自动降级为确定性结果并标记 `hybrid_fallback`。显式 --keyword 优先级最高。

**Q29. LLM 输出怎么处理才安全？**
A: 视为不可信数据：`sanitize_keywords` strip 引号/反引号、限长 2-80、拒绝含换行符的词；`parse_keyword_json` 容忍 Markdown 围栏、要求 keywords 是字符串数组。即使没有 shell 权限，也要把模型输出当输入消毒——为未来开放工具调用提前建立的边界。

**Q30. 为什么不用 Function Calling 让 LLM 直接调工具？**
A: 当前查询扩展不是 Function Calling：模型只返回 JSON，工具循环由确定性 Orchestrator 控制。理由：容易测试与归因（每个环节可单独验证）；等查询召回评测稳定后再让模型从只读工具白名单选工具，一次只扩一个能力。

**Q31. 搜索用什么实现？为什么不用 ripgrep？**
A: 当前是 `git ls-files -z` 枚举 tracked 文件 + 纯 Python 逐行字面子串匹配（README 早期写 ripgrep 是过时描述，已修正）。参数数组启动子进程、不经 shell。逐行扫描对 6 万文件的 OpenCV 实测 p50 ~1.9s；比 ripgrep 慢但零外部依赖、逻辑可测。下一步可以换 ripgrep（参数数组调用）做索引加速。

**Q32. 为什么只用 git 跟踪文件？**
A: 可复现性（tracked 文件是"某个 commit 上的仓库"，untracked 构建产物会污染结果——测试里专门验证过 build/ 目录被忽略）＋稳定顺序（git ls-files 排序确定，截断可复现）。

**Q33. 二进制/超大文件怎么处理？**
A: 前 8KB 含 NUL 判定为二进制跳过；>1MB 跳过（MAX_SEARCHABLE_FILE_BYTES）；读取用 utf-8 errors=replace 防解码崩溃。这些过滤同时保证 IDF 分母（corpus_files）只含"可搜索"文件，不虚高。

**Q34. 搜索超时怎么控制？**
A: 单次搜索 `timeout_seconds`（默认 10s）同时约束 `git ls-files` 子进程与 Python 扫描循环——我给扫描循环加了 deadline 检查（time.monotonic），超时停止扫描返回已收集结果。这是修复过的问题：之前超时只包住 git 命令，大仓库上扫描可能失控。

**Q35. evidence 去重怎么做？为什么键里有 keyword？**
A: 键 = (path, line_start, line_end, keyword)。**这是修过的 bug**：早期键没有 keyword，两个词命中同一区域时保留先到的，存活证据声称的 keyword 与实际内容不符——被 Verifier 回读闸门当场抓出。

---

## 五、排序与评分（10 题）

**Q36. 排序公式是什么？**
A: `score(path) = Σ_keywords [ IDF(k) × (1 + ln(hit_count)) ]`，然后：vendored 目录 ×0.1，docs/changelog 类 ×0.3。IDF = `ln(1 + N/(1+df))`（平滑避免负值），词频次线性 `1+ln(hits)`。平局按路径排序保证可复现。

**Q37. IDF 解决了什么？具体例子？**
A: 阶段 A 没有 IDF，`width`/`overflow` 这类通用词与 `icvCvt_BGRA2RGBA_16u_C4R` 这种唯一符号同等计分，导致命中一堆常见词的 500KB 变更日志排在只命中精确符号的源文件前面。IDF 让稀有符号权重数十倍于常见词——四臂消融里它是最大单项贡献（+0.167 Hit@10）。

**Q38. 路径先验（vendored 降权）为什么不认为是过拟合？**
A: `VENDORED_DIRECTORIES`（3rdparty/vendor/node_modules/deps/...）是**通用约定表**，不是按 OpenCV 调参。证据：阶段 B 后 `3rdparty/` 在 top-3 占比从 61% 降到 0%，而 OpenCV 特有的 `modules/ts/ts_gtest.h` 我没有加特例——因为按仓库特有目录调参就是在评测集上过拟合，正确解法是找可泛化的信号。

**Q39. docs/changelog 降权怎么来的？**
A: 泛化验证时发现 fastapi 的 `docs/release-notes.md` 排第 1——文档类文件对任何"代码修复定位"都是噪音。加了通用 `DOCUMENTATION_MARKERS`（docs/doc/manual/wiki + changelog/release-notes/history/news），惩罚 0.3（降权不隐藏——changelog 可能是合理的下一步阅读）。OpenCV 全量评测数字完全不变（gold 都是源码）。

**Q40. 为什么全池打分而不是只给截断后的证据打分？**
A: 早期搜索只返回截断的 30 条 Evidence，正确文件可能因为某个常见词先占满引用预算就被丢掉。现在同时返回全部命中文件的统计量（matches + corpus_files），先全量排序再截断——阶段 B 的 +0.117 Hit@10 就来自这个数据流改动。

**Q41. 长度归一（BM25）为什么回退了？**
A: BM25 长度归一假设"长度≈冗余度"（网页/新闻），但代码仓库**大文件=核心实现**：opencv 语料平均 430 行，正确实现文件（如 cap_ffmpeg_impl.hpp 3779 行）被降权 85%，小文档被 boost 冲到 top。实测 Hit@10 0.750→0.283。保留了代码与 --length-norm 实验开关——面试讲这个比讲成功更有说服力。

**Q42. 排序为什么是"检索的答案"而不是中间产物？**
A: 检索任务的输出就是"按相关性排序的文件列表"（评测也是这么定义的）。RankedFile 持久化让评估、复现、失败分析都基于同一份答案，而不是每次重算。

**Q43. 平局怎么处理？为什么？**
A: 排序键 `(-score, path)`——分数相同按路径字典序，保证跨机器/跨运行可复现。代价是平局时的结果可能与"语义上更好"的略有偏差，但可复现性优先。

**Q44. 排序可消融（ablation）怎么做的？**
A: InvestigatorAgent 暴露 use_idf / vendored_penalty / use_length_norm 参数，eval CLI 对应 --idf / --vendored-penalty / --length-norm 开关，每次评测的 ranking 字符串（如 "idf+prior"）写进 EvalRun。四臂消融表在 EVALUATION.md。

**Q45. 一个关键词匹配一个文件 500 行 vs 另一个文件 5 行，谁排前？**
A: 取决于 IDF（该词在全语料出现多少文件）和路径先验。同词同 IDF 时，`1+ln(500)≈7.2` vs `1+ln(5)≈2.6`——命中多的排前，但次线性（500 倍命中不是 500 倍分数）。大文件的长度影响由长度归一处理（默认关，因为实测负收益）。

---

## 六、工具层与安全（8 题）

**Q46. 工具层和 Agent 为什么要分开？**
A: Agent 决定"做什么"，工具决定"怎么安全执行"。收益：①工具可单独单元测试；②测试可用假工具替换（不碰真实文件系统）；③未来可把本地工具换成 MCP 而不改 Agent；④每个工具可独立设权限/超时/观测。

**Q47. 路径安全怎么防目录穿越？**
A: 所有路径先 `resolve()`（展开符号链接、归一化），再用 `candidate.relative_to(root)` 检查是否仍在仓库根内——`../`、绝对路径、指向仓库外的符号链接都会被 `PathPolicyError` 拦截。测试里有专门的越界用例。

**Q48. 为什么要求仓库必须有 .git？**
A: 报告要记录 branch/HEAD/dirty 保证可复现（同一问题在不同版本可能答案不同）；搜索依赖 git ls-files。这是"可复现性优先"的设计。

**Q49. 命令注入怎么防？**
A: 全程 `subprocess.run([...])` 参数数组、`shell=False`，关键词/路径永不经 shell 拼接。即使关键词是 `; rm -rf /` 也只是字面量被搜索。README 明确列了这条安全边界。

**Q50. 文件读取有哪些限制？**
A: SafeFileReader：路径必须仓库内、max_file_bytes 默认 200KB、行范围校验（line_start≥1 且 end≥start）、utf-8 replace 解码、输出带行号。搜索侧另有 1MB 上限 + 二进制嗅探。

**Q51. 报告里记录 Git 快照有什么意义？**
A: GitInspector 读 branch/HEAD/dirty 写进报告头。否则同一问题在不同源码版本上得到不同答案，却无法解释差异。面试点：可复现性不只是"数字稳定"，还包括"环境可追溯"。

**Q52. 工具层有统一的安全框架吗？**
A: 诚实回答：没有——Tool 基类只是最小协议（run + metadata），参数校验/超时/审计由各工具自己实现。好处是灵活，代价是安全策略分散（比如搜索超时曾经漏掉扫描循环）。这是一个已知的架构权衡，未来可以加统一执行层。

**Q53. 如果未来开放写文件/执行工具，现在的安全设计还够吗？**
A: 不够——当前只读边界下没有 TOCTOU 处理（resolve 检查与读取之间的竞态）、没有权限分级。开放写能力前必须：统一 sandbox、fd 级校验、工具白名单 + 审批流。这正是"先只读、评测稳定后再扩权"的原因。

---

## 七、编排、Checkpoint 与恢复（7 题）

**Q54. run() 的状态转换逻辑画一下。**
A: created/investigating →（investigator）→ planning →（planner）→ verifying →（verifier）→ completed。每阶段转换前后 `store.save()`。异常 → error 记录 + failed 落库 + 重抛。resume 对 failed 任务清 error 回 investigating。

**Q55. resume 幂等性怎么保证的？**
A: completed 任务 resume 不再跑 Agent，只重新生成报告（同样的 state + 同样的 git snapshot → 同样的报告）。测试 test_resume_completed_task_is_idempotent 断言两次 model_dump 完全相等。

**Q56. 为什么每阶段都存一次而不是最后存一次？**
A: 断点续跑的最小粒度是阶段：planning 阶段崩溃不需要重跑 investigating。代价是多次磁盘写（可接受，单机 SQLite）。这也是"显式状态机"优于大循环的直接体现。

**Q57. 报告生成是幂等的吗？**
A: 是——render_markdown(state, snapshot) 是纯函数，同输入同输出。write_report 覆盖写 `<task_id>.md`。

**Q58. 编排器为什么不自己调工具？**
A: 编排器只做状态转移和持久化，工具调用职责在 Agent——Agent 决定"下一步查什么"，编排器决定"阶段走到哪"。这样评测可以只跑 Investigator（eval 就是这么做的），不经过完整流水线。

**Q59. 任务失败后能继续吗？怎么继续？**
A: resume 把 failed 重置为 investigating 重跑整个流水线（不跳过阶段，因为失败原因可能在任何阶段）。更精细的恢复（只重试失败阶段）是后续可以做的。

**Q60. 并发跑多个任务安全吗？**
A: SQLite 支持多连接（WAL 模式读写不互斥），task_id 是 uuid 主键无冲突。但 orchestrator 是单例（lru_cache），多线程共享同一实例——Agent 无共享可变状态（每个 TaskState 独立），所以是线程安全的。API 层 FastAPI 线程池天然并发。

---

## 八、持久化：SQLite（5 题）

**Q61. 为什么选 SQLite 而不是 JSON 文件或 PostgreSQL？**
A: 单机单用户场景，SQLite 提供事务、查询、零运维；JSON 文件无事务/并发弱。多实例部署才需要 PostgreSQL——现在上分布式属于过度设计。面试可展开"什么时候该迁移"（多进程写、跨机器、容量）。

**Q62. WAL 模式解决了什么？**
A: 写不阻塞读（未来 API 读任务时不卡写）、崩溃恢复更好。一行 PRAGMA 的收益在面试里讲清楚：并发读写场景是 SQLite 的经典坑。

**Q63. state_json 整行存有什么好处和问题？**
A: 好处：序列化简单（Pydantic model_dump_json）、演进灵活（加字段不用改表）。问题：不能 SQL 查询字段内部、行变大。权衡：当前查询只需要 task_id/stage/updated_at（已单独建列），内部字段用 JSON 合理。

**Q64. 没有 schema 版本，升级会怎样？**
A: 新代码 model_validate_json 旧数据可能因字段不匹配报错。当前单表单版本没触发，但这是明确的已知风险——诚实说出来，下一步加 schema_version + 迁移。

**Q65. task 列表怎么分页/查询？**
A: store.list(limit) 按 updated_at DESC。目前只支持 limit，没有 offset/条件查询——够用，未来按 stage 过滤可以加 SQL 条件。

---

## 九、LLM 集成（8 题）

**Q66. 为什么用 HelloAgents 而不是直接调 OpenAI SDK？**
A: HelloAgents 是统一 LLM 接口（OpenAI/Anthropic/Gemini 适配器），连接 DeepSeek 的 OpenAI 兼容端点。适配器只获得"给问题返回关键词"的窄权限——不获得仓库路径、文件读取、命令执行能力。窄权限 = 低风险面。

**Q67. 模型调用失败怎么处理？两类错误分开吗？**
A: 分开：①配置错误（缺 API Key/未安装依赖）抛 LLMConfigurationError，CLI 显示"Configuration error"并 exit 2，不静默降级——否则用户以为模型生效了；②运行时错误（超时/坏 JSON）降级为确定性结果 + hybrid_fallback 标记 + warning 写入 trace。两类不能混。

**Q68. API Key 怎么管理？会泄漏吗？**
A: 从 .env 读（gitignore 排除），TaskState 只记录模型名/延迟/关键词，绝不存 Key。DeepSeekConfig.from_env 校验空值和占位符（"your-deepseek-api-key"）抛配置错误。

**Q69. 温度设多少？为什么？**
A: temperature=0.0——结构化任务（返回关键词 JSON）要确定性，不要发散。还显式关了 thinking（extra_body），减少延迟和意外输出。

**Q70. 为什么模型输出要先消毒才进搜索？**
A: 模型输出是不可信输入——即使没有 shell 权限，也要在边界消毒（长度、换行、引号）。这是为未来"模型调工具"提前建立的边界：任何模型输出进入系统前都要过校验层。

**Q71. LLM 扩展的效果评测了吗？**
A: 诚实回答：没有专门评测——hybrid 策略的增量需要在固定问题集上对比 Top-K 召回率，这是已知的未完成项。当前评测都是 deterministic（不调模型），保证数字可复现。面试主动说这一点比被问到好。

**Q72. 为什么要延迟导入 hello-agents？**
A: 未安装可选依赖（pip install -e ".[llm]"）的用户仍能跑确定性版本。导入和读 Key 都推迟到 --use-llm 真正执行时。这是"可选能力不影响核心可用性"的工程实践。

**Q73. LLM 调用是同步的，会不会卡住整个流程？**
A: 会——同步单次调用，无重试（失败靠上层降级）。超时由 LLM_TIMEOUT 控制（默认 120s）。对交互式工具可接受；大规模评测不会开 LLM。这是明确的取舍：简单可归因优先于吞吐。

---


## 十、评测方法论（10 题）

**Q74. 评测任务的定义是什么？为什么说标准答案"没人能争论"？**
A: 输入=真实 GitHub issue 标题+正文；输出=排序的文件路径列表；标准答案=关闭该 issue 的**已合并 PR** 改动的源文件。理由是：标准答案不是人工标注，是维护者用一次真实代码评审背书的——没有标注者主观性。

**Q75. 数据集怎么构建的？数据从哪来？**
A: `dataset-build` 通过 gh CLI 的 GraphQL（`closedByPullRequestsReferences`）拿 issue→PR 链接，走用户已有的 gh auth 会话——Token 不进代码/环境变量/数据集。六条过滤规则（PR 必须 merged、改动≤10 文件、只留源码扩展名、正文≥80 字符、同 PR 去重、gold 文件在当前快照存在），每条规则丢弃多少都打印——"不能被审计的数据集不能证明任何事"。

**Q76. Recall@k、Hit@k、MRR 分别回答什么问题？**
A: Recall@k=修复涉及文件有多大比例进前 k（惩罚找一半）；Hit@k=前 k 有没有一个对的（"给没给人真实线索"，二值）；MRR=第一个正确答案排多靠前（区分第 1 和第 9）。三指标分歧本身就是信息——一个 PR 改 2 文件只找到 1 个：Recall@5=0.5 但 Hit@5=1.0。

**Q77. 三个已知偏差是什么？为什么都要主动说？**
A: ①快照偏差（所有 case 在同一个 HEAD 评测，修复代码已在树里——乐观，正确做法是按 base_sha 逐 case 检出父提交）；②文本泄漏（崩溃报告直接贴出文件路径——真实输入但抬高分数，所以分"全部 case"和"未提及答案文件"两栏，后者才是诚实下界）；③幸存者偏差（gold 文件已删除的 case 被丢弃）。三条都指向：真实线上只会更差。

**Q78. 消融（ablation）怎么设计？**
A: 同一数据集/快照/关键词，只改一个排序信号。四臂：全池打分 → +路径先验 → +IDF → +两者。结果：IDF 是最大单项贡献（+0.167 Hit@10），路径先验主要改善 top-1（Hit@1 0.150→0.300）。

**Q79. 阶段 B 的"排序天花板"预测是什么？验证了吗？**
A: 诊断把失败劈成两半：21/60 排序问题（正确文件在候选集但排名>10）+ 22/60 召回问题（从未被检索到）。预测：纯排序改进的天花板 Hit@10=0.633（21 个全提进前 10）。实测 0.583，接近——同时召回问题几乎没动（22→20），验证了"排序救不了召回"。

**Q80. 为什么用 body_chars 控制喂多少正文？**
A: 喂多少正文本身是评测维度（OpenCV issue 正文常整段贴构建日志，越长噪音越多）。消融发现 body 0 字符和 600 字符结果完全一样——因为旧抽取器只取前 6 个 token，多喂的正文只贡献了样板词。这个实验直接催生了阶段 C。

**Q81. eval 为什么复用 Investigator 而不是跑完整流水线？**
A: 评测目标是检索定位（Top-K 文件），只需要 Investigator 的输出。复用同一个 Agent 保证评测的就是线上用的代码（无"评测专用路径"），这是可信度关键。

**Q82. 评测报告为什么把配置和数字放一起？**
A: 脱离配置的分数没有意义。EvalRun 记录数据集/仓库/snapshot_sha/strategy/body_chars/max_results/ranking 开关 + 每 case 明细，JSON 和 Markdown 一起输出。"分数+配置"是一个对象。

**Q83. 延迟怎么测的？p50/p95 为什么用 ceil 分位？**
A: 每 case 计时（perf_counter），聚合 p50/p95。percentile 用 nearest-rank + ceil 而不是 round——round 用银行家舍入会让 p50 在样本数变化时不一致（2 样本取大的、4 样本取小的），ceil 保证单调稳定。

**Q84. 一个 case 抛异常会中断整轮评测吗？**
A: 不会——run_case 捕获异常记入 CaseResult.error，错误 case 不进指标但单独计数报告（"errors"），一个不可回答的 case 不毁掉 50 个 case 的结果。

**Q85. 怎么复现你的评测数字？**
A: 数据集 + opencv 仓库固定 commit（f1e824b88a）+ `repopilot eval --dataset ... --repo ...`（默认 body600/idf+prior），输出 deterministic-body600-idf+prior.{json,md}。同一命令应该得到同样数字（排序无随机性，路径破平局）。

---

## 十一、测试与工程实践（7 题）

**Q86. 测试怎么保证可重复？**
A: conftest 的 sample_repo fixture 在 tmp_path 创建**真实 git 仓库**（含 __pycache__ 干扰、二进制、untracked 文件等陷阱），不依赖开发机上的任何仓库。CI 可重复。

**Q87. 测试覆盖了哪些"看不见的坑"？举 3 个。**
A: ①untracked 构建产物曾"silently dominated"搜索结果——测试验证 git 作用域；②截断中途曾按字母序返回文件——测试验证按命中数排序；③IDF 反例：罕见符号必须击败 CHANGELOG 常见词；④Verifier 缓存键回归（同文件两行区域独立判定）。

**Q88. 怎么测 LLM 相关代码？不调真模型。**
A: KeywordGenerator 是 Protocol，测试注入 FakeGenerator（可控结果/异常），验证三种路径：deterministic 不调 LLM、hybrid 合并消毒、运行时异常降级为 fallback。API Key 缺失场景用 pytest.raises(LLMConfigurationError)。

**Q89. lint 配置了哪些规则？**
A: ruff，select E/F/I/B/UP（错误/格式/导入/内置陷阱/升级），line-length 100。E501 是实际抓过的（新代码长行），B 类规则抓内置函数陷阱（如 open 未关）。

**Q90. 为什么 API 测试要 monkeypatch get_orchestrator？**
A: 测试用临时目录的 orchestrator（build_orchestrator(tmp_path)）替换单例，避免污染真实 .repopilot 状态库；cache_clear + 替换模块级引用。这同时验证了 DI 设计——替换点只有一个。

**Q91. 测试金字塔怎么排的？**
A: 底层：工具测试（路径安全/搜索/读取，不碰 Agent）；中间：状态机/查询扩展（Fake 注入）；上层：API/CLI 契约 + 端到端（真实 git 仓库完整流水线）。共 38 个测试，全绿 + ruff 全绿。

**Q92. 代码里你最自豪/最后悔的一段？**
A: 自豪：Verifier 回读闸门——上线第一天抓出两个真实 bug（去重键、缓存键），证明"验证器自己也要被验证"。后悔/教训：阶段 D 的 BM25 一开始没在评测集上小跑就全量实现了——现在任何排序改动先跑消融。面试讲教训比讲成就更有记忆点。

---

## 十二、简历数字拷打（6 题）

**Q93. 这些数字怎么来的？能现场复现吗？**
A: 可以——数据集（datasets/opencv-issues.jsonl，60 case）+ opencv 仓库固定 commit + 一条 eval 命令。Hit@10 0.750、Recall@10 0.647、MRR 0.487、无泄漏子集 Hit@10 0.615。备一台能跑 opencv 的机器，现场演示最有说服力。

**Q94. 0.750 是不是因为正文直接贴了答案路径（泄漏）？**
A: 部分 case 是（真实输入，不算作弊），所以分了"全部"和"未提及答案文件"两栏——无泄漏子集 Hit@10 0.615（阶段 A 是 0.231，+166%）。主动分开报，面试官问就是加分项。

**Q95. 为什么不用 LLM 做检索？**
A: ①确定性基线零成本、可复现、可评测归因；②LLM 检索（embedding/rerank）效果没评测过，不能拍脑袋说更好；③评测数字全部来自确定性策略，LLM 只是可选查询扩展且失败自动降级。先证明确定性到底，再谈模型。

**Q96. 一次失败的迭代怎么处理的？**
A: 阶段 D（BM25 长度归一）实测 Hit@10 从 0.750 崩到 0.283，根因是代码仓库长度分布与网页语料相反。我保留代码和实验开关、回退默认、把失败写进 EVALUATION.md——评测驱动原则意味着"改坏了要能发现、能回退、能解释"。

**Q97. 和现成的代码搜索（GitHub Code Search / Sourcegraph）比有什么意义？**
A: 它们是"全文检索"，我是"调查 Agent"：①按判别力选词（自动把问题变成好查询词）；②结构化证据（行号引用 + 回读验证）；③多阶段流程（调查→计划→验证→报告）。搜索只是第一阶段，产出是可追溯的调查结论。

**Q98. 如果面试官问"这个项目有多少是你写的？"**
A: 诚实回答：项目从我接手时已有 Phase 1 骨架（状态机/工具层/评测雏形），我完成了阶段 C（关键词抽取，四轮迭代+评测）、阶段 D（实现并证伪回退）、阶段 E（Verifier 回读+两个 bug 修复）、仓库泛化验证（3 仓库实测+docs 降权）、全套文档与面试材料。具体哪些 commit 是我的可查 git log。

---

## 十三、Agent 工程通用（5 题）

**Q99. 你怎么防幻觉？**
A: 四层：①检索层只收集证据不做因果推断（Agent 职责边界）；②结论必须锚定 Evidence.id（无引用即拒绝）；③Verifier 回读文件验证引用真实性（存在性 + 关键词在行）；④置信度封顶 0.95 + 报告明确"只证明文本命中，不证明运行时行为"。

**Q100. 证据驱动和 RAG 有什么区别？**
A: RAG 是"检索→拼进 prompt→生成"；证据驱动是"检索→结构化引用→确定性验证→结论分级"。我的 Verifier 是确定性集合运算+文件回读，不是又一个 LLM 打分——所以"验证通过"这个结论本身是可靠的、可解释的（reason 字符串直接说明判定依据）。

**Q101. Agent 的工具调用设计有什么原则？**
A: ①窄权限（LLM 只获得"返回关键词"的能力，不获得文件/命令）；②输入消毒（模型输出过校验层）；③失败降级但不静默（配置错误显式失败，运行时错误降级+记录）；④一次只扩一个能力（先查询扩展，评测稳定后再谈工具选择）。

**Q102. 你的 checkpoint 和 LangGraph 的 checkpoint 有什么区别？**
A: LangGraph 是通用图执行框架；我的 checkpoint 是针对本任务最小实现（阶段级 SQLite 落库）。选型权衡：自研 300 行可控可测、零依赖；LangGraph 强大但引入框架复杂度。对单仓库调查任务，显式状态机足够且更好归因。

**Q103. 如果任务需要多轮工具调用（先搜索再读文件再搜），现在支持吗？**
A: 当前是单轮检索（每关键词一次搜索，Agent 不自主决定下一步）。Planner 生成的 plan 里有 verification_command（建议的下一步只读检查），但 Phase 1 不自动执行——这是刻意的边界：先证明单轮证据质量，多轮工具循环留给评测通过后。面试可谈"多轮循环的评测难点"（状态爆炸、可复现性）。

---

## 十四、扩展与未来（5 题）

**Q104. 下一步最想做什么？为什么？**
A: 三个候选：①按 base_sha 逐 case 检出父提交（消除快照乐观偏差，数据集已记录字段，工程正确性高）；②关键词抽取的判别力进一步升级（当前 8/60 召回失败）；③Tree-sitter 调用关系（把"文本命中"升级为"调用路径"——从"提到"到"真的被调用"）。优先级取决于面试侧重：评测严谨性选①，检索效果选②，深度选③。

**Q105. 这个项目能产品化吗？差什么？**
A: 能——差三块：①异步/流式（SSE 实时任务）；②多仓库规模（索引层，如 ripgrep/parquet 预构建）；③权限与审批（开放写工具前的 sandbox/白名单）。产品形态：CI 里对 PR 自动跑调查，输出"改动影响面"报告；或 IDE 插件。

---

## 附：被问到不会的问题怎么答

- 不知道确切数字 → "我记得 Hit@10 是 0.75，精确到小数的数字我可以现场重跑评测拿到"（你的评测可复现就是底气）。
- 被质疑设计 → 先承认取舍再讲依据："这是已知权衡，因为……我选择……代价是……未来可以……"。
- 被问没做过的事 → 明确区分"没做过"和"没想过"："没做过 X，但我思考过，方案是……"。

## 附：10 个必背数字

| 数字 | 含义 |
|---|---|
| 0.750 / 0.647 / 0.487 | 阶段 C Hit@10 / Recall@10 / MRR |
| 0.615 | 无泄漏子集 Hit@10（阶段 A 0.231） |
| 60 | OpenCV 评测 case 数 |
| 8 | 阶段 C 后剩余召回失败数（原 20） |
| 38 | 测试用例数（全绿） |
| 2.8s → 1.9s | 阶段 B → C 的延迟 p50 |
| 0.283 | BM25 长度归一实测 Hit@10（负收益，已回退） |
| 3 | 泛化验证仓库数（go/react/fastapi） |
| 0.3 / 0.1 | docs / vendored 降权系数 |
| 0.95 | 置信度上限 |
