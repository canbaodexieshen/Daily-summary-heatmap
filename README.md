# 每日总结热力图

📊 一个自动化的 GitHub Pages 热力图项目，展示每日总结的完成情况。

## 功能特点

- 🌙 **暗色模式** - 自动跟随系统设置，也支持手动切换
- 🎨 **智能配色** - 根据创建时间自动调整颜色深浅
  - 浅绿色：较早完成（凌晨~中午）
  - 深绿色：较晚完成（下午~午夜）
- 🔄 **自动更新** - 每天早上自动从 Notion 同步数据
- 📱 **响应式设计** - 适配各种屏幕尺寸

## 颜色含义

| 颜色 | 含义 |
|------|------|
| 灰色方块 | 当天未创建每日总结 |
| 浅绿色 | 当天较早就完成了总结 |
| 深绿色 | 当天较晚才完成总结 |

**悬停提示**：显示具体日期和完成时间

## 本地运行

### 1. 配置环境变量

创建 `.env` 文件：

```env
NOTION_TOKEN=your_notion_token
NOTION_DATABASE_ID=your_database_id
```

### 2. 运行脚本

```bash
pip install github-heatmap
python update_daily_summary_heatmap.py
```

### 3. 本地预览

使用任意静态服务器：

```bash
# Python
python -m http.server 8000

# Node.js
npx serve
```

然后访问 `http://localhost:8000`

## GitHub 部署

### 1. Fork 此仓库

### 2. 配置 GitHub Secrets

在仓库设置中添加以下 Secrets：

| Secret 名称 | 说明 |
|-------------|------|
| `NOTION_TOKEN` | Notion Integration Token |
| `NOTION_DATABASE_ID` | 每日总结数据库 ID |

### 3. 启用 GitHub Pages

1. 进入仓库 **Settings** → **Pages**
2. Source 选择 **Deploy from a branch**
3. Branch 选择 **gh-pages** / **/ (root)**
4. 保存

### 4. 访问你的热力图

```
https://your-username.github.io/repository-name/
```

## Notion 数据库要求

你的"每日总结"数据库需要包含以下属性：

| 属性名 | 类型 | 说明 |
|--------|------|------|
| 日期 | Date | 总结对应的日期 |
| 创建时间 | - | 系统自动记录即可（使用 Notion 自带的 created_time） |

## 手动触发更新

如果你想立即更新热力图，可以：

1. 进入仓库的 **Actions** 页面
2. 选择 **Update Daily Summary Heatmap** 工作流
3. 点击 **Run workflow** 按钮
