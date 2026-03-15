# RF4 Bream Research Platform 🐟

> **RF4 底钓数据研究与自动化平台** — 在 Old Burg（奥尔德堡）围绕欧鳊底钓，建立稳定、可复盘、可分析的数据体系。

## ✨ 功能特性

- **视觉感知**：HSV 色彩检测鱼口 + 拉力条三色分析 + 聊天框 OCR
- **三杆 FSM 自动化**：6 状态有限状态机（IDLE→CASTING→WAITING→HOOKING→RETRIEVING→LOGGING），三杆并行
- **反作弊鼠标**：三阶贝塞尔曲线 + 随机控制点 + 缓动函数 + 末端微抖动
- **数据记录**：SQLite 5 表存储（Session / RodConfig / EnvSnapshot / Event / Catch）
- **分析报告**：Markdown 实验报告 + CSV 导出 + TTB 直方图 + 渔获趋势图
- **数据质量**：四维评分（OCR 置信度 / Evidence 覆盖 / 事件链完整性 / 环境快照）
- **LLM 日志**：AI 生成拟人化垂钓心得（支持 GLM-4 / DeepSeek / GPT）

## 📁 项目结构

```
RF4Data-AG/
├── main.py                         # 程序入口
├── requirements.txt                # 依赖
├── config/
│   ├── settings.json               # 运行时配置
│   └── settings.template.json      # 配置模板
├── src/
│   ├── drivers/                    # 输入驱动层
│   │   ├── base.py                 # InputDriver 抽象基类
│   │   ├── software.py             # PyAutoGUI 驱动 (带贝塞尔曲线)
│   │   └── bezier.py               # 贝塞尔曲线鼠标移动
│   ├── core/                       # 核心逻辑
│   │   ├── config.py               # 配置管理
│   │   ├── vision.py               # 视觉感知 (HSV/拉力/OCR)
│   │   ├── fsm.py                  # 6 状态 FSM + 三杆协调器
│   │   ├── env_monitor.py          # 环境快照采集
│   │   └── session.py              # Session 生命周期管理
│   ├── data/                       # 数据层
│   │   ├── models.py               # 数据模型 (5 表)
│   │   └── db.py                   # SQLite CRUD + 统计
│   ├── analysis/                   # 分析层
│   │   ├── reporter.py             # Markdown/CSV/图表报告
│   │   └── quality.py              # 数据质量评分 (A-F)
│   └── utils/                      # 工具
│       ├── screenshot.py           # mss 截图
│       ├── ocr.py                  # Tesseract OCR
│       └── llm_client.py           # LLM 日志 (Mock + OpenAI)
└── tools/                          # 独立工具
    ├── calibrate.py                # ROI 校准 GUI
    ├── analyze_image.py            # 截图单步调试 (HSV Mask / OCR)
    ├── batch_test_cv.py            # 离线批量 CV 回归测试
    └── report.py                   # CLI 报告生成
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

> **额外依赖**: [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) 需单独安装并加入 PATH。

### 2. 配置

```bash
cp config/settings.template.json config/settings.json
# 编辑 settings.json 修改窗口分辨率、OCR 语言等
```

### 3. 校准 ROI

启动游戏窗口后运行校准工具，框选关键 UI 区域：

```bash
python tools/calibrate.py
```

需要标定的区域：杆 1/2/3 指示器、聊天框、拉力条、起鱼弹窗。

### 4. 离线调试与测试 (M6 新增)

配置好 ROI 后，可以通过截取游戏画面离线调试计算机视觉参数，而无需一直开着游戏。

```bash
# 生成并显示指定 HSV 区间的 Color Mask 预览
python tools/analyze_image.py screenshot.png --roi 100 100 50 50 --hsv --mask-hsv 170 100 100 180 255 255

# 对收集到的样本图库进行批量回归测试，验证识别率
python tools/batch_test_cv.py --type bite --dir data/samples/bites/ --rod 1
python tools/batch_test_cv.py --type popup --dir data/samples/popups/
```

### 5. 运行自动化 Session

```bash
python main.py --map "Old Burg" --spot "35:67" --notes "测试欧鳊底钓"
```

按 `Ctrl+C` 停止，自动生成报告。

### 5. 查看报告

```bash
python tools/report.py --list          # 列出所有 Session
python tools/report.py --session 1     # 生成指定报告
python tools/report.py --all           # 生成所有报告
```

## 📊 报告示例

报告自动生成到 `data/reports/session_N/` 目录，包含：

| 文件 | 内容 |
|:---|:---|
| `report.md` | 概览/TTB 分布/鱼种明细/杆具配置/异常统计/质量评分/心得 |
| `*_catches.csv` | 渔获原始数据 |
| `*_events.csv` | 事件日志 |
| `*_ttb.png` | Time-to-Bite 分布直方图 |
| `*_catches.png` | 渔获累计趋势 + 重量散点图 |

## 🎯 FSM 状态流转

```
IDLE → CASTING → WAITING → HOOKING → RETRIEVING → LOGGING → IDLE
                    ↓ timeout                ↓ loss
                  IDLE                     IDLE
```

## ⚙️ 配置说明

| 参数 | 说明 | 默认值 |
|:---|:---|:---|
| `render_width/height` | 游戏窗口分辨率 | 1920×1080 |
| `wait_timeout_s` | 等待鱼口超时（秒） | 1200 |
| `retrieve_timeout_s` | 收线超时（秒） | 180 |
| `input_delay_multiplier` | 输入延迟倍率（越大越安全越慢） | 1.0 |
| `use_bezier` | 启用贝塞尔曲线鼠标 | true |
| `env_snapshot_interval_s` | 环境快照间隔（秒） | 60 |

## 📜 License

本项目仅供学习和数据研究使用。请遵守游戏服务条款。
