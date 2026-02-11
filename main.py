"""
RF4 Bream Research Platform — 主入口
===================================
启动一个研究 Session，初始化所有模块，运行主循环。
"""

import os
import sys

# Windows 控制台 UTF-8 支持
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import time
import signal
import logging
import argparse
from pathlib import Path
from datetime import datetime

# 项目根目录加入路径
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import ConfigLoader
from src.data.db import Database
from src.data.models import Session
from src.utils.screenshot import ScreenCapture

logger = logging.getLogger("rf4brp")


def setup_logging(level: str = "INFO") -> None:
    """配置日志系统。"""
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"session_{ts}.log"

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(log_file), encoding="utf-8"),
    ]

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    logger.info("日志已初始化: %s", log_file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RF4 Bream Research Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config-dir", default="config",
        help="配置文件目录 (默认: config/)",
    )
    parser.add_argument(
        "--map", default="Old Burg",
        help="地图名称 (默认: Old Burg)",
    )
    parser.add_argument(
        "--spot", default="",
        help="钓点坐标 (如: 35:67)",
    )
    parser.add_argument(
        "--notes", default="",
        help="本次 Session 备注",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="试运行模式（不执行输入操作）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)

    logger.info("=" * 60)
    logger.info("  RF4 Bream Research Platform v0.1")
    logger.info("=" * 60)

    # ── 初始化配置 ──────────────────────────────────────
    config = ConfigLoader(args.config_dir)
    logger.info("配置已加载 (ROI 校准: %s)", "✓" if config.has_roi else "✗ 需要校准")

    # ── 初始化数据库 ────────────────────────────────────
    db = Database(config.get("db_path", "data/rf4_research.db"))
    db.init_schema()

    # ── 初始化截图工具 ─────────────────────────────────
    capture = ScreenCapture(config.get("evidence_dir", "data/evidence"))

    # ── 检查 ROI 是否已校准 ────────────────────────────
    if not config.has_roi:
        logger.warning("=" * 60)
        logger.warning("  ROI 尚未校准！请先运行:")
        logger.warning("  python tools/calibrate.py")
        logger.warning("=" * 60)
        logger.info("当前仅初始化数据库，不启动主循环。")
        db.close()
        capture.close()
        return

    # ── 使用 SessionManager 运行 ────────────────────────
    from src.core.session import SessionManager

    session_mgr = SessionManager(config)
    session_id = session_mgr.start(
        map_name=args.map,
        spot_id=args.spot,
        notes=args.notes,
    )
    logger.info("Session #%d 已创建 [%s | %s]", session_id, args.map, args.spot or "未指定钓点")

    if args.dry_run:
        logger.info("试运行模式 — 不启动主循环。")
        stats = session_mgr.stop()
    else:
        # ── 优雅退出 ────────────────────────────────────
        def _signal_handler(sig, frame):
            logger.info("收到退出信号，正在清理...")
            session_mgr.orchestrator.stop()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        logger.info("主循环启动。按 Ctrl+C 结束 Session。")
        try:
            session_mgr.run()
        except KeyboardInterrupt:
            pass
        finally:
            stats = session_mgr.stop()

    # ── 打印统计 ────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("  Session #%d 已结束", session_id)
    logger.info("  时长: %.1f 小时", stats.get("duration_hours", 0))
    logger.info("  渔获: %d 条 | 跑鱼: %d 次",
                stats.get("total_catch", 0), stats.get("total_loss", 0))
    logger.info("  总重: %.0fg | 总价值: %.0f",
                stats.get("total_weight_g", 0), stats.get("total_value", 0))
    logger.info("  CPUE: %.1f 条/时", stats.get("cpue_fish_per_hour", 0))
    logger.info("=" * 60)

    # ── 自动生成报告 ──────────────────────────────────────
    logger.info("正在生成报告...")
    try:
        report_db = Database(config.get("db_path", "data/rf4_research.db"))
        report_db.init_schema()

        from src.analysis.reporter import ReportGenerator
        gen = ReportGenerator(report_db, session_id)
        result = gen.generate_all()
        logger.info("📄 报告已生成: %s", result["markdown"])

        # 数据质量评估
        from src.analysis.quality import DataQualityAnalyzer
        qa = DataQualityAnalyzer(report_db, session_id)
        quality = qa.analyze()
        logger.info("📋 数据质量: %s (%.0f/100)", quality.grade(), quality.overall_score)

        # LLM 日志（使用 Mock — 无需 API key）
        from src.utils.llm_client import MockLLMClient
        llm = MockLLMClient()
        summary_log = llm.generate_session_summary(stats)
        logger.info("📝 垂钓心得: %s", summary_log)

        report_db.close()
    except Exception as e:
        logger.warning("报告生成失败: %s", e)

    logger.info("所有资源已释放。")


if __name__ == "__main__":
    main()
