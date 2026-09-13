# 端到端验收套件（scripts/acceptance/）

REFACTOR_PLAN_R3 的 M11 交付物：把原先躺在 `.scratch/`（被 gitignore）里的五套端到端验收
**迁进仓库**，让干净克隆也能跑 —— 此前每一轮验收都依赖"我这台机器上恰好有那几个脚本"。

## 前提

四容器已在跑（仓库根目录）：

```bash
docker-compose up -d          # backend:8002 / frontend:4002 / db:5432 / worker
```

## 跑法

```bash
# 一条命令跑全（推荐）
python scripts/acceptance/run_all.py

# 换地址 / 只跑其中几套
python scripts/acceptance/run_all.py --base-url http://127.0.0.1:8002 --frontend-url http://127.0.0.1:4002
python scripts/acceptance/run_all.py --only verify_route_a.py,verify_graph.py

# 单套脚本也可以独立跑（参数：base-url [frontend-url]）
python scripts/acceptance/verify_metrics_live.py http://127.0.0.1:8002
```

环境变量：`RL_API`（后端地址，默认 `http://127.0.0.1:8002`）、`RL_WEB`（前端地址，默认 `http://127.0.0.1:4002`）。

## 五套脚本各自验什么

| 脚本 | 覆盖 |
|---|---|
| `verify_route_a.py` | 论文 manifest / sections / exhibits / 页码锚点 / 作者 / 年份 / 图表 image_url 等路由与字段 |
| `verify_graph.py` | 图谱节点与边、无断裂图、断点证据可达、exhibits.graph 快照 |
| `verify_e2e_extra.py` | `/claims` 详情、statement/evidence 字段、SSE 事件序列与 final 非空、前端 bundle 关键路径 |
| `verify_metrics_live.py` | 评测指标口径（proxy 有值、not_evaluated 不冒充 0、overall 未盖章） |
| `verify_qa_stability.py` | 多轮问答稳定性（同一问题重复问，答案非空且一致） |

## 退出码约定

| 码 | 含义 |
|---|---|
| `0` | 全绿 |
| `1` | 有脚本 fail / error（见 `results.json`） |
| `2` | **前置健康检查未通过**（服务栈没起来）。此时**不会**继续跑，也不会把检查标成"跳过=通过" |

## 输出

- stdout：每套脚本一行 JSON —— `{script, status, failures, elapsed_ms, tail}`，最后一行是汇总；
- `scripts/acceptance/results.json`：完整汇总（含每套的尾部输出，便于定位失败）。

## 已知偏离（如实记录）

R3 方案 §M11-2 写的是"**每脚本**输出统一 JSON 行"。当前实现是**由 run_all 统一汇总输出**
（各脚本保持原有的人读输出与退出码不变）。偏离原因：逐脚本改尾部输出结构的收益低、
而失败风险（改坏一套已验证的脚本）不成比例。若后续需要每脚本独立 JSON，
再在各脚本尾部加一行 `print(json.dumps(...))` 即可，run_all 无需改动。
