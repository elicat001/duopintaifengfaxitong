# 📡 企业级内容分发调度系统

> Enterprise Content Distribution & Scheduling Platform

全自动化的多平台内容分发调度系统，集成 AI 内容生成、趋势分析、账号管理、智能排期等功能，支持 8 大社交媒体平台。

---

## 功能概览

| 模块 | 功能 |
|------|------|
| **仪表盘** | 实时数据统计、内容状态分布图、近期任务概览、快速操作入口 |
| **内容管理** | 内容 CRUD、多平台变体生成、富文本编辑、标签管理、状态流转 |
| **AI 工作台** | 多 AI 供应商配置、内容生成流水线、趋势扫描、话题建议、用量统计 |
| **账号管理** | 多平台账号管理、浏览器自动登录、登录状态监控、健康评分、凭据加密存储 |
| **策略配置** | 发布策略编排、时间窗口设置、频率控制、平台权重分配 |
| **任务中心** | 定时任务队列、执行日志、手动触发、失败重试 |

### 支持平台

微博 · 抖音 · 小红书 · 哔哩哔哩 · Twitter/X · Instagram · TikTok · YouTube

---

## 技术栈

| 层级 | 技术 |
|------|------|
| **后端框架** | Flask 3.x + Flask-CORS |
| **数据库** | SQLite (WAL 模式) — 26 张数据表 |
| **任务调度** | APScheduler (BlockingScheduler) |
| **AI 供应商** | Anthropic Claude · OpenAI GPT · Google Gemini |
| **浏览器自动化** | Playwright (Chromium) |
| **数据校验** | Pydantic v2 |
| **认证** | JWT (HS256) + 管理员用户名/密码 |
| **加密** | AES-256-GCM (凭据加密存储) |
| **前端** | 单文件 SPA (原生 HTML/CSS/JS)，6 套主题 |

---

## 项目结构

```
inswuxianfa/
├── app.py                      # Flask 应用入口
├── main.py                     # APScheduler 调度器入口
├── config.py                   # 全局配置 (环境变量 + 默认值)
├── requirements.txt            # Python 依赖
├── .env.example                # 环境变量模板
│
├── api/                        # API 蓝图 (12 个模块)
│   ├── auth.py                 #   认证装饰器 & JWT 校验
│   ├── dashboard.py            #   仪表盘统计接口
│   ├── contents.py             #   内容 CRUD + 变体生成
│   ├── accounts.py             #   账号管理
│   ├── policies.py             #   发布策略配置
│   ├── jobs.py                 #   任务管理
│   ├── ai.py                   #   AI 配置 / 生成 / 趋势 / 话题
│   ├── credentials.py          #   加密凭据管理
│   ├── login_status.py         #   登录状态监控
│   ├── browser_login.py        #   浏览器自动登录
│   ├── proxies.py              #   代理管理
│   └── account_health.py       #   账号健康评分
│
├── services/                   # 业务逻辑层 (18 个服务)
│   ├── content_service.py      #   内容服务
│   ├── account_service.py      #   账号服务
│   ├── policy_service.py       #   策略服务
│   ├── job_service.py          #   任务服务
│   ├── ai_config_service.py    #   AI 配置管理
│   ├── ai_generation_service.py#   AI 内容生成
│   ├── ai_provider_registry.py #   AI 供应商注册
│   ├── pipeline_service.py     #   AI 流水线服务
│   ├── trend_service.py        #   趋势扫描 (RSS)
│   ├── topic_suggestion_service.py # 话题建议
│   ├── credential_service.py   #   凭据服务
│   ├── crypto_service.py       #   AES-256-GCM 加密
│   ├── browser_service.py      #   Playwright 浏览器控制
│   ├── login_orchestrator.py   #   登录编排器
│   ├── login_status_service.py #   登录状态服务
│   ├── proxy_service.py        #   代理服务
│   ├── account_health_service.py#  健康评分服务
│   └── platform_logins/        #   平台登录实现
│       ├── base.py             #     基类
│       ├── registry.py         #     平台注册表
│       ├── weibo.py            #     微博
│       ├── douyin.py           #     抖音
│       ├── xiaohongshu.py      #     小红书
│       ├── bilibili.py         #     哔哩哔哩
│       ├── twitter.py          #     Twitter/X
│       ├── instagram.py        #     Instagram
│       ├── tiktok.py           #     TikTok
│       └── youtube.py          #     YouTube
│
├── agents/                     # 调度智能体
│   ├── scheduler.py            #   主调度器 (编排所有子智能体)
│   ├── content_manager.py      #   内容发布管理
│   ├── scoring_engine.py       #   表现评分引擎
│   ├── performance_tracker.py  #   数据追踪器
│   └── ai_pipeline_executor.py #   AI 流水线执行器
│
├── models/                     # 数据模型
│   ├── database.py             #   SQLite 建表 & 迁移 (26 表)
│   └── schemas.py              #   Pydantic 模型 & 枚举
│
├── static/                     # 前端静态资源
│   └── index.html              #   单文件 SPA (含 6 套主题)
│
├── data/                       # 运行时数据 (自动创建)
│   ├── scheduler.db            #   SQLite 数据库
│   ├── uploads/                #   上传文件
│   └── screenshots/            #   登录截图
│
└── tests/                      # 测试套件
    ├── test_scheduler.py
    ├── test_content_manager.py
    ├── test_scoring_engine.py
    └── test_performance_tracker.py
```

---

## 快速开始

### 环境要求

- **Python** 3.10+
- **Node.js** (仅 Playwright 浏览器安装需要)
- **操作系统**: Windows / macOS / Linux

### 1. 克隆项目

```bash
git clone <your-repo-url>
cd inswuxianfa
```

### 2. 创建虚拟环境

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 安装 Playwright 浏览器（可选，用于自动登录）

```bash
playwright install chromium
```

### 5. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，设置以下必要参数：

```ini
# ── 生产环境必填 ──────────────────────────────────
JWT_SECRET=your-random-secret-at-least-32-chars
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-this-password
CREDENTIAL_KEY=separate-encryption-key-32-chars

# ── 可选配置 ──────────────────────────────────────
FLASK_DEBUG=false
CORS_ORIGINS=https://yourdomain.com

# 浏览器自动化
BROWSER_HEADLESS=true
BROWSER_TIMEOUT_SECONDS=60
BROWSER_MAX_CONCURRENT=3
```

### 6. 启动服务

系统由两个独立进程组成：

#### 启动 Web 服务器

```bash
python app.py
```

服务将在 `http://localhost:5000` 启动。浏览器打开即可访问管理界面。

#### 启动自动调度器（可选）

```bash
python main.py
```

调度器使用 APScheduler 驱动，默认每 **3600 秒**（1 小时）执行一次调度循环，启动时立即执行首次循环。

> **提示**: Web 服务器和调度器是独立进程，可以只运行 Web 服务器用于手动管理，也可以同时运行实现全自动化调度。

---

## 运行测试

```bash
pytest tests/ -v
```

当前测试覆盖：4 个测试文件，51 个测试用例，全部通过。

---

## API 接口概览

所有接口均需 JWT 认证（登录接口除外），请求头携带 `Authorization: Bearer <token>`。

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 管理员登录，返回 JWT |

### 仪表盘

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/dashboard/stats` | 获取统计概览 |

### 内容管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/contents` | 内容列表 (分页/筛选) |
| POST | `/api/contents` | 创建内容 |
| GET | `/api/contents/<id>` | 获取内容详情 |
| PUT | `/api/contents/<id>` | 更新内容 |
| DELETE | `/api/contents/<id>` | 删除内容 |
| POST | `/api/contents/<id>/variants` | 生成平台变体 |

### 账号管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/accounts` | 账号列表 |
| POST | `/api/accounts` | 创建账号 |
| PUT | `/api/accounts/<id>` | 更新账号 |
| DELETE | `/api/accounts/<id>` | 删除账号 |

### AI 工作台

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/ai/config` | AI 配置 |
| PUT | `/api/ai/config` | 更新 AI 配置 |
| POST | `/api/ai/generate` | AI 内容生成 |
| GET | `/api/ai/usage` | AI 用量统计 |
| POST | `/api/ai/trends/scan` | 触发趋势扫描 |
| GET | `/api/ai/trends` | 获取趋势列表 |
| GET | `/api/ai/topics/suggestions` | 获取话题建议 |
| GET | `/api/ai/pipelines` | 流水线列表 |
| POST | `/api/ai/pipelines` | 创建流水线 |
| POST | `/api/ai/pipelines/<id>/execute` | 执行流水线 |

### 策略配置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/policies` | 策略列表 |
| POST | `/api/policies` | 创建策略 |
| PUT | `/api/policies/<id>` | 更新策略 |
| DELETE | `/api/policies/<id>` | 删除策略 |

### 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/jobs` | 任务列表 |
| POST | `/api/jobs/<id>/retry` | 重试失败任务 |
| DELETE | `/api/jobs/<id>` | 删除任务 |

### 凭据 & 登录

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/credentials` | 存储加密凭据 |
| GET | `/api/login-status` | 登录状态列表 |
| POST | `/api/browser-login/<id>/start` | 启动浏览器登录 |
| GET | `/api/browser-login/<id>/status` | 获取登录状态 |

### 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/proxies` | 代理列表 |
| POST | `/api/proxies` | 添加代理 |
| GET | `/api/account-health` | 账号健康评分 |

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                       浏览器 (前端 SPA)                        │
│           index.html — 6 大模块 · 6 套主题 · 响应式             │
└──────────────────────┬───────────────────────────────────────┘
                       │ HTTP/JSON
┌──────────────────────▼───────────────────────────────────────┐
│                      Flask Web Server (app.py)                │
│  ┌─────────┐ ┌─────────┐ ┌────────┐ ┌──────────┐ ┌────────┐ │
│  │ auth.py │ │contents │ │accounts│ │ policies │ │ jobs   │ │
│  └────┬────┘ └────┬────┘ └───┬────┘ └────┬─────┘ └───┬────┘ │
│       │      ┌────┴──────────┴───────────┴────────────┘      │
│       │      ▼                                               │
│  ┌────┴──────────────────────────────────────────────────┐   │
│  │               Services 业务逻辑层 (18 个服务)            │   │
│  │  content · account · policy · job · AI · crypto · …   │   │
│  └────┬──────────────┬───────────────────┬───────────────┘   │
│       │              │                   │                   │
│  ┌────▼────┐   ┌─────▼──────┐    ┌──────▼──────┐            │
│  │ SQLite  │   │ AI Providers│    │  Playwright  │            │
│  │ 26 表   │   │ Claude/GPT/ │    │  浏览器自动化  │            │
│  │ WAL模式  │   │ Gemini     │    │              │            │
│  └─────────┘   └────────────┘    └──────────────┘            │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│               APScheduler 调度器 (main.py)                     │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                    Scheduler 主智能体                     │  │
│  │  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐ │  │
│  │  │  Content  │ │ Scoring  │ │Performance│ │    AI    │ │  │
│  │  │  Manager  │ │  Engine  │ │  Tracker  │ │ Pipeline │ │  │
│  │  └──────────┘ └──────────┘ └───────────┘ └──────────┘ │  │
│  └────────────────────────────────────────────────────────┘  │
│                    每 3600 秒执行一次调度循环                     │
└──────────────────────────────────────────────────────────────┘
```

---

## 核心工作流

### 内容发布流程

```
创建内容 → AI 生成/润色 → 生成平台变体 → 策略匹配 → 定时队列 → 自动发布 → 表现追踪 → 评分
```

### 账号养号流程

```
添加账号 → 凭据加密存储 → 浏览器自动登录 → 登录状态监控 → 5阶段养号 → 健康评分
```

养号分 5 个阶段，逐步提升每日发布限额：

| 阶段 | 日限额 | 时限额 | 持续天数 |
|------|--------|--------|----------|
| 1 | 2 | 1 | 3 天 |
| 2 | 4 | 2 | 3 天 |
| 3 | 6 | 2 | 5 天 |
| 4 | 8 | 3 | 5 天 |
| 5 | 10 | 3 | 7 天 |

### AI 流水线

```
趋势扫描 (RSS) → 话题提取 → AI 内容生成 → 多平台变体 → 自动排期发布
```

支持的 AI 供应商：
- **Anthropic Claude** (默认: claude-sonnet-4-20250514)
- **OpenAI GPT** 系列
- **Google Gemini** 系列

---

## 配置说明

### 全局配置 (`config.py`)

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `JWT_EXPIRY_HOURS` | 24 | JWT 过期时间 (小时) |
| `SCHEDULE_INTERVAL_SECONDS` | 3600 | 调度循环间隔 (秒) |
| `AI_DEFAULT_PROVIDER` | anthropic | 默认 AI 供应商 |
| `AI_DEFAULT_MODEL` | claude-sonnet-4-20250514 | 默认 AI 模型 |
| `AI_MAX_DAILY_GENERATIONS` | 50 | 每日最大生成次数 |
| `AI_MAX_DAILY_TOKENS` | 500,000 | 每日最大 Token 数 |
| `AI_TREND_SCAN_INTERVAL_HOURS` | 6 | 趋势扫描间隔 (小时) |
| `PROXY_CHECK_INTERVAL_MINUTES` | 15 | 代理检测间隔 (分钟) |
| `LOGIN_CHECK_INTERVAL_MINUTES` | 30 | 登录检测间隔 (分钟) |
| `RISK_SCORE_HIGH` | 70.0 | 高风险阈值 |
| `RISK_SCORE_MEDIUM` | 40.0 | 中风险阈值 |

### 评分权重

| 指标 | 权重 |
|------|------|
| 点赞 (likes) | 1.0 |
| 评论 (comments) | 3.0 |
| 转发 (shares) | 5.0 |
| 浏览 (views) | 0.1 |

### 评分等级

| 等级 | 阈值 |
|------|------|
| 高表现 (high) | ≥ 80 分 |
| 正常 (normal) | ≥ 40 分 |
| 低表现 (low) | ≥ 15 分 |

---

## 安全特性

- **JWT 认证**: 所有 API 接口(除登录外)需携带有效 Token
- **密码哈希**: 管理员密码通过环境变量配置
- **凭据加密**: 平台登录凭据使用 AES-256-GCM 加密存储，密钥与 JWT 密钥分离
- **CORS 控制**: 可配置允许的跨域来源
- **SQL 参数化**: 所有数据库查询使用参数化语句，防止 SQL 注入
- **异常隐藏**: 生产环境不向客户端暴露内部错误详情
- **输入校验**: Pydantic v2 模型校验所有 API 输入

> ⚠️ **生产部署注意**: 务必设置 `JWT_SECRET`、`ADMIN_PASSWORD`、`CREDENTIAL_KEY` 环境变量，不要使用默认值。

---

## 前端主题

系统内置 6 套主题，在侧边栏底部可切换：

| 主题 | 色调 |
|------|------|
| 午夜蓝 (默认) | 深蓝灰色系 |
| 深海 | 深海军蓝 |
| 暖炭 | 暖褐琥珀色系 |
| 翡翠 | 森林绿色系 |
| 皇紫 | 紫罗兰色系 |
| 亮色 | 浅色模式 |

主题偏好自动保存到浏览器本地存储。

---

## 开发指南

### 添加新平台支持

1. 在 `services/platform_logins/` 下创建新文件，继承 `BasePlatformLogin`
2. 实现 `login()` 和 `check_status()` 方法
3. 在 `services/platform_logins/registry.py` 中注册
4. 在 `models/schemas.py` 的 `Platform` 枚举中添加新平台

### 添加新 AI 供应商

1. 在 `services/ai_provider_registry.py` 中注册新供应商
2. 实现对应的 API 调用逻辑
3. 在 `config.py` 中添加相关配置项

### 项目约定

- API 蓝图统一前缀 `/api/`
- 服务层与 API 层分离，API 层仅做参数校验和路由
- 数据库操作集中在 `models/database.py`
- 所有配置通过 `config.py` 管理，支持环境变量覆盖

---

## 许可证

私有项目，版权所有。
