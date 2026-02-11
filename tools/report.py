"""
CLI 报告生成工具
===============
从已有数据库中为指定 Session 生成完整报告。

用法:
    python tools/report.py                    # 最近一个 Session
    python tools/report.py --session 5        # 指定 Session
    python tools/report.py --all              # 所有 Session
    python tools/report.py --list             # 列出所有 Session
"""

import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import ConfigLoader
from src.data.db import Database
from src.analysis.reporter import ReportGenerator
from src.analysis.quality import DataQualityAnalyzer
from src.utils.llm_client import MockLLMClient


def list_sessions(db: Database) -> None:
    """列出所有 Session。"""
    rows = db.conn.execute(
        "SELECT session_id, map_name, spot_id, start_ts, end_ts, notes "
        "FROM sessions ORDER BY session_id DESC"
    ).fetchall()

    if not rows:
        print("没有找到任何 Session。")
        return

    print(f"{'ID':>4} | {'地图':<12} | {'钓点':<8} | {'开始时间':<20} | {'备注'}")
    print("-" * 80)
    for r in rows:
        r = dict(r)
        sid = r["session_id"]
        map_name = r.get("map_name", "")[:12]
        spot = r.get("spot_id", "")[:8]
        start = r.get("start_ts", "")[:19]
        notes = r.get("notes", "")[:30]
        print(f"{sid:>4} | {map_name:<12} | {spot:<8} | {start:<20} | {notes}")


def generate_report(db: Database, session_id: int, output_dir: str) -> None:
    """为指定 Session 生成报告。"""
    print(f"\n{'='*60}")
    print(f"  生成 Session #{session_id} 报告")
    print(f"{'='*60}")

    gen = ReportGenerator(db, session_id)
    result = gen.generate_all(output_dir)

    print(f"  📄 Markdown: {result['markdown']}")
    print(f"  📊 CSV: {len(result['csv_files'])} 个文件")
    print(f"  📈 图表: {len(result['charts'])} 张")

    # 数据质量
    qa = DataQualityAnalyzer(db, session_id)
    quality = qa.analyze()
    print(f"  📋 数据质量: {quality.grade()} ({quality.overall_score:.0f}/100)")

    # LLM 日志
    stats = db.get_session_stats(session_id)
    llm = MockLLMClient()
    summary = llm.generate_session_summary(stats)
    print(f"  📝 心得: {summary}")

    # 将质量报告追加到 Markdown
    md_path = Path(result["markdown"])
    qa_md = qa.to_markdown(quality)
    with open(md_path, "a", encoding="utf-8") as f:
        f.write("\n" + qa_md + "\n")
        f.write(f"## 📝 垂钓心得\n\n{summary}\n")

    print(f"\n  ✅ 报告已保存到: {md_path.parent}")


def main():
    parser = argparse.ArgumentParser(
        description="RF4 Session 报告生成工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--session", "-s", type=int, default=0,
                        help="Session ID（默认: 最近一个）")
    parser.add_argument("--all", "-a", action="store_true",
                        help="为所有 Session 生成报告")
    parser.add_argument("--list", "-l", action="store_true",
                        help="列出所有 Session")
    parser.add_argument("--config-dir", default="config",
                        help="配置目录")
    parser.add_argument("--output", "-o", default="",
                        help="输出目录（默认: 从配置读取）")
    args = parser.parse_args()

    config = ConfigLoader(args.config_dir)
    db_path = config.get("db_path", "data/rf4_research.db")
    db = Database(db_path)
    db.init_schema()

    output_dir = args.output or config.get("report_dir", "data/reports")

    if args.list:
        list_sessions(db)
    elif args.all:
        rows = db.conn.execute(
            "SELECT session_id FROM sessions ORDER BY session_id"
        ).fetchall()
        for r in rows:
            generate_report(db, r["session_id"], output_dir)
    else:
        sid = args.session
        if sid == 0:
            row = db.conn.execute(
                "SELECT session_id FROM sessions ORDER BY session_id DESC LIMIT 1"
            ).fetchone()
            if not row:
                print("没有找到任何 Session。请先运行 main.py。")
                db.close()
                return
            sid = row["session_id"]
        generate_report(db, sid, output_dir)

    db.close()


if __name__ == "__main__":
    main()
