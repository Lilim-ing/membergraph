# 架构与执行过程

## 一次运行的完整生命周期

```
1. Tracer 打开 trace.jsonl，Budget 初始化
2. Planner: LLM 拆 3-4 个子问题 → blackboard["sub_questions"]
3. Analyst × N:
     LLM 决定 metric/dimension（不能偷换 metric）
     → charge_tool → compute_metric(本期) → charge_tool → compute_metric(上期)
     → Evidence 写入 blackboard，Tracer 记 tool_call
4. 分解（可选）: 主指标支持 shift-share 才执行，否则记 decomposition_skipped
5. Diagnostician: 读全部 Evidence → LLM 归因 → 过滤掉引用不存在证据的 Claim
6. Strategist: 读 Claim + 人群规模 → LLM 出动作 → 过滤掉无证据的动作
7. Critic 循环（≤2 轮）:
     pass → 进入合规
     fail → Strategist 带 critique 重做
8. Compliance: 纯规则检查（引用完整性、绝对化、PII、折扣、夸大、频控）
9. 组装 Plan → plan.json / plan.md / blackboard.json
10. Tracer 记 run_end，关闭文件
```

## 关键不变量

| 不变量 | 保障位置 | 违反后果 |
|---|---|---|
| 结论必须有证据 | `Claim.evidence_ids` 的 `min_length=1` | Pydantic 校验失败 |
| 结论不能引用不存在的证据 | Diagnostician 过滤 + Compliance 兜底 | 该条结论被丢弃 / 方案被阻断 |
| 动作必须挂证据 | Strategist 过滤 | 动作不进入方案 |
| 指标不能被偷换 | Analyst 校验 `metric == sub_question.metric` | 抛错，不静默改题 |
| 维度必须被支持 | Analyst 回退到首个允许维度 + trace | 不崩，但留痕 |
| 预算不可超支 | `Budget.charge_*` | `BudgetExceeded` → 降级 |
| 历史不可篡改 | Blackboard 只追加，每次写产生新 revision | — |

## 模块职责

| 模块 | 职责 | 不做什么 |
|---|---|---|
| `contracts.py` | 类型契约与校验 | 不做业务计算 |
| `blackboard.py` | 版本化共享状态 | 不感知 agent 语义 |
| `budget.py` | 计费与阈值 | 不决定降级策略（编排层决定） |
| `orchestrator.py` | 流程、降级、产物落盘 | 不写 prompt，不算指标 |
| `agents/*` | 单角色决策 | 不直接读写文件，只经黑板 |
| `tools/*` | 确定性计算 | 不调 LLM |
| `observability/*` | 事件记录与渲染 | 不影响主流程（失败不阻断运行） |
| `llm/*` | provider 适配 | 不校验业务语义（由 agent 校验） |

## Trace 事件格式

每行一个 JSON：

```json
{
  "seq": 12,
  "ts": "2026-10-21T09:42:31+08:00",
  "offset_ms": 182.4,
  "run_id": "mg-20261021-094231-bf41",
  "type": "tool_call",
  "agent": "analyst",
  "tool": "compute_metric",
  "metric": "repurchase_rate_90d",
  "dimension": "register_channel",
  "value": 0.124,
  "delta": -0.0193,
  "evidence_id": "e1"
}
```

事件类型：`run_start` / `plan` / `llm_call` / `tool_call` / `dimension_fallback` / `decomposition_skipped` / `diagnose` / `strategize` / `critique` / `critique_exhausted` / `compliance` / `degrade` / `run_end` / `run_error`。

## 扩展点

**加一个指标**：在 `tools/metrics.py` 写计算函数 + 在 `METRIC_META` 注册维度 → `COMPUTERS` 加一行。Planner 会自动看到它。

**加一个角色**：继承 `BaseAgent`，实现 `run(ctx, bb)`，在 orchestrator 里插入一步。黑板上加自己的 key。

**换模型**：`build_llm("deepseek")` 或任何 OpenAI 兼容网关。agent 代码不动。

**接真实数据**：替换 `data/fixtures/*.parquet`，保持表结构。`Warehouse` 只读本地 parquet，不持有任何连接串。
