# Morning Note — 晨会纪要

买方风格的晨会纪要生成器。管理自选股列表，通过 Claude CLI 调用 equity-research 插件生成每日晨会报告。

## 功能

- **自选股管理** — 快速添加/编辑/删除关注的公司
- **晨会纪要生成** — 一键调用 Claude CLI 联网获取最新动态，生成 Top Call、隔夜动态、关键事件、交易想法
- **历史记录** — 所有生成的报告自动保存，支持回溯查看
- **报告操作** — 复制到剪贴板、下载为 Markdown 文件

## 界面

三栏布局：

| 左侧 | 中间 | 右侧 |
|------|------|------|
| 自选股列表 | 晨会纪要历史 | 报告预览 |

栏宽可拖拽调整，位置自动记忆。

## 依赖

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code/overview) (`claude` 命令)
- Python 3.12+（Homebrew 版本）
- tkinter（Python 自带）

## 使用

```bash
# 1. 安装依赖
pip install flask

# 2. 启动（两种方式）
cd /Users/patrickge/晨会
./app.py              # 终端启动
open Morning-Note.command  # 双击启动
```

## 技术栈

- **前端界面**: Python tkinter (ttk)
- **报告生成**: Claude Code CLI (`claude -p` + `--dangerously-skip-permissions`)
- **数据存储**: JSON (companies.json) + Markdown 文件 (notes/)

## 项目结构

```
晨会/
├── app.py                  # 主程序
├── Morning-Note.command    # macOS 双击启动脚本
├── companies.json          # 自选股数据
├── notes/                  # 生成的晨会纪要
│   └── YYYY-MM-DD_HHMM.md
├── .gitignore
└── README.md
```
