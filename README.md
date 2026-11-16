# API数据聚合采集中心

面向多源API接入、接口编排、数据聚合、响应校验、频率控制与数据转储的API数据聚合采集中心。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   ├── app/audit.py          日志审计摘要与链摘要算法
│   ├── app/store.py          内存数据仓库与示例数据
│   └── tests/                日志审计数据集回归用例（python -I 直接运行）
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 接口管理 | `endpoint` | API端点 | 端点编号、接口地址、请求方法 |
| 接口编排 | `chain` | 调用链路 | 链路编号、端点序列、数据传递映射 |
| 频率控制 | `freq` | 频率规则 | 规则编号、目标端点、每秒上限 |
| 数据映射 | `mapper` | 映射规则 | 规则编号、源字段路径、目标字段名 |
| 响应校验 | `validator` | 校验规则 | 规则编号、关联端点、校验字段 |
| 失败重试 | `retry` | 重试策略 | 策略编号、关联端点、最大重试 |
| 数据聚合 | `aggregator` | 聚合任务 | 任务编号、输入端点列表、合并策略 |
| 凭证管理 | `auth` | 认证凭证 | 凭证编号、关联端点、认证类型 |
| 缓存策略 | `cache` | 缓存规则 | 规则编号、关联端点、缓存键模板 |
| 数据转储 | `dump` | 转储配置 | 配置编号、数据来源、存储类型 |
| 采集调度 | `schedule` | 调度计划 | 计划编号、关联链路、调度表达式 |
| 采集监控 | `monitor` | 监控指标 | 指标编号、关联端点、成功率阈值 |
| 数据转换 | `transform` | 转换脚本 | 脚本编号、输入数据源、转换表达式 |
| 数据清洗 | `cleanse` | 清洗规则 | 规则编号、目标字段、空值替换 |
| 限流配置 | `ratelimit` | 限流规则 | 规则编号、目标端点、令牌速率 |
| 采集日志 | `log` | 日志记录 | 记录编号、关联端点、请求时间 |
| 日志审计 | `audit` | 审计数据集 | 数据集编号、归档文件、记录摘要 |
| 增量采集 | `delta` | 增量游标 | 游标编号、目标端点、增量字段 |
| 数据导出 | `export` | 导出通道 | 通道编号、输出数据集、目标系统 |

## 日志审计数据集

按采集请求日志批次建立日志审计数据集，解决采集日志归档缺少不可改写顺序与摘要链、
导出后无法证明记录是否缺失的问题。

- 主链只追加：每条请求日志写入时生成 `主链序号`、`记录摘要`（4 位短摘要）、
  `摘要指纹`（完整 SHA-256）、`前序摘要` 与 `链摘要`，序号与摘要一旦写入不再回填。
- 相同记录只写一次：`记录编号` 与 `记录摘要` 都相同即视为重复写入，沿用原节点，
  主节点数与采集请求数不变。
- 摘要断点：迟到更正写入独立「更正段」，通过 `归属节点` 锚定原主节点，不参与主链排序；
  请求时间早于归档末尾的新日志仍按追加顺序写入主链末位，但标记 `顺序异常` 并交裁决。
- 审计交付待处理队列（`/api/audit/queue`）：每个摘要断点生成一条队列项，收存归档结果，
  可确认交付或关闭。
- 导出详情（`GET /api/audit/{id}/export`）：按主链序号逐条列出记录数、首条时间、
  记录摘要与链摘要，并同步列出摘要断点。

接口一览：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/audit` | 数据集列表 |
| POST | `/api/audit` | 按批次建立数据集（`归档文件`、`来源批次`、`记录列表`、`采集日志记录`） |
| GET | `/api/audit/{id}` | 数据集明细：节点、冲突、断点与校验结果 |
| POST | `/api/audit/{id}/records` | 写入一条请求日志（重复写入自动去重） |
| POST | `/api/audit/{id}/actions` | 校验摘要链、裁决冲突、封存/解封数据集 |
| GET | `/api/audit/{id}/verify` | 逐项重算主链并返回检查清单 |
| GET | `/api/audit/{id}/export` | 导出批次详情与摘要断点 |
| POST | `/api/audit/{id}/recheck` | 在副本上复测重复写入与迟到更正 |
| GET/POST | `/api/audit/queue`、`/api/audit/queue/{id}/actions` | 交付待处理队列 |

示例数据：`AUD-0001` 对应归档文件 `ARC-55`，含 128 条请求，首条 `LOG-301` 的主摘要为
`H7K2`。复测用例见 `backend/tests/test_audit.py`，运行
`.venv/bin/python -I tests/test_audit.py`。

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数据采集、爬虫与RPA
