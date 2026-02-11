"""
分析报告生成器
=============
从数据库中查询 Session 数据，生成:
1. Markdown 实验报告（含 CPUE/TTB/饵料效率/异常统计）
2. CSV 原始数据导出
3. 基础图表（matplotlib — TTB 分布、收益趋势）

用法:
    from src.analysis.reporter import ReportGenerator
    gen = ReportGenerator(db, session_id)
    gen.generate_all("data/reports")
"""

import csv
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from collections import Counter

logger = logging.getLogger(__name__)

try:
    import matplotlib
    matplotlib.use("Agg")  # 无头模式
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    _HAS_MATPLOTLIB = True
except ImportError:
    _HAS_MATPLOTLIB = False
    logger.warning("matplotlib 未安装，图表功能不可用")

from src.data.db import Database


class ReportGenerator:
    """Session 报告生成器。"""

    def __init__(self, db: Database, session_id: int):
        self.db = db
        self.session_id = session_id

    # ── 数据获取 ─────────────────────────────────────────

    def _get_session_info(self) -> dict:
        row = self.db.conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (self.session_id,),
        ).fetchone()
        return dict(row) if row else {}

    def _get_catches(self) -> List[dict]:
        return self.db.get_catches(self.session_id)

    def _get_events(self, event_type: Optional[str] = None) -> List[dict]:
        return self.db.get_events(self.session_id, event_type=event_type)

    def _get_rod_configs(self) -> List[dict]:
        rows = self.db.conn.execute(
            "SELECT * FROM rod_configs WHERE session_id = ? ORDER BY rod_slot, updated_ts",
            (self.session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _get_env_snapshots(self) -> List[dict]:
        rows = self.db.conn.execute(
            "SELECT * FROM env_snapshots WHERE session_id = ? ORDER BY ts",
            (self.session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 统计计算 ─────────────────────────────────────────

    def _calc_ttb(self, events: List[dict]) -> List[float]:
        """
        计算 Time-To-Bite (TTB)：每次 CAST 到 BITE 之间的秒数。
        """
        # 按杆分组
        rod_events: Dict[int, List[dict]] = {}
        for e in events:
            slot = e.get("rod_slot", 0)
            rod_events.setdefault(slot, []).append(e)

        ttb_list = []
        for slot, evts in rod_events.items():
            last_cast_time = None
            for e in sorted(evts, key=lambda x: x.get("ts", "")):
                etype = e.get("event_type", "")
                ts_str = e.get("ts", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str)
                except ValueError:
                    continue

                if etype == "CAST" or etype == "STATE_CASTING":
                    last_cast_time = ts
                elif etype in ("BITE", "STATE_HOOKING") and last_cast_time:
                    ttb = (ts - last_cast_time).total_seconds()
                    if 0 < ttb < 7200:  # 合理范围 0-2h
                        ttb_list.append(ttb)
                    last_cast_time = None

        return sorted(ttb_list)

    @staticmethod
    def _percentile(values: List[float], p: float) -> float:
        if not values:
            return 0.0
        k = (len(values) - 1) * p
        f = int(k)
        c = min(f + 1, len(values) - 1)
        return values[f] + (k - f) * (values[c] - values[f])

    # ── Markdown 报告 ────────────────────────────────────

    def generate_markdown(self, output_path: Path) -> str:
        """生成 Markdown 报告。"""
        session = self._get_session_info()
        catches = self._get_catches()
        events = self._get_events()
        rod_configs = self._get_rod_configs()
        stats = self.db.get_session_stats(self.session_id)
        ttb_list = self._calc_ttb(events)

        successful = [c for c in catches if c.get("outcome") == "CATCH"]
        losses = [c for c in catches if c.get("outcome") != "CATCH"]

        lines = []
        lines.append(f"# RF4 Session 报告 #{self.session_id}")
        lines.append("")
        lines.append(f"**地图**: {session.get('map_name', 'N/A')}")
        lines.append(f"**钓点**: {session.get('spot_id', 'N/A')}")
        lines.append(f"**开始**: {session.get('start_ts', 'N/A')}")
        lines.append(f"**结束**: {session.get('end_ts', 'N/A')}")
        lines.append(f"**时长**: {stats.get('duration_hours', 0):.1f} 小时")
        lines.append(f"**备注**: {session.get('notes', '')}")
        lines.append("")

        # 概览
        lines.append("## 📊 概览")
        lines.append("")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|:---|:---|")
        lines.append(f"| 总渔获 | {stats.get('total_catch', 0)} 条 |")
        lines.append(f"| 跑鱼/断线 | {stats.get('total_loss', 0)} 次 |")
        lines.append(f"| 总重量 | {stats.get('total_weight_g', 0):.0f}g |")
        lines.append(f"| 总价值 | {stats.get('total_value', 0):.0f} |")
        lines.append(f"| 奖杯鱼 | {stats.get('trophies', 0)} 条 |")
        lines.append(f"| CPUE (条/时) | {stats.get('cpue_fish_per_hour', 0):.1f} |")
        lines.append(f"| CPUE (g/时) | {stats.get('cpue_weight_per_hour', 0):.0f} |")
        lines.append("")

        # TTB
        if ttb_list:
            lines.append("## ⏱ Time-to-Bite 分布")
            lines.append("")
            lines.append(f"| 分位 | 秒数 |")
            lines.append(f"|:---|:---|")
            lines.append(f"| p25 | {self._percentile(ttb_list, 0.25):.0f}s |")
            lines.append(f"| p50 (中位数) | {self._percentile(ttb_list, 0.50):.0f}s |")
            lines.append(f"| p75 | {self._percentile(ttb_list, 0.75):.0f}s |")
            lines.append(f"| p90 | {self._percentile(ttb_list, 0.90):.0f}s |")
            lines.append(f"| 样本量 | {len(ttb_list)} |")
            lines.append("")

        # 鱼种分布
        if successful:
            lines.append("## 🐟 渔获明细")
            lines.append("")
            fish_count = Counter(c.get("fish_name_raw", "Unknown") for c in successful)
            fish_weight = {}
            for c in successful:
                name = c.get("fish_name_raw", "Unknown")
                fish_weight[name] = fish_weight.get(name, 0) + c.get("weight_g", 0)

            lines.append("| 鱼种 | 数量 | 占比 | 总重 (g) | 均重 (g) |")
            lines.append("|:---|:---|:---|:---|:---|")
            for name, count in fish_count.most_common(10):
                pct = count / len(successful) * 100
                tw = fish_weight.get(name, 0)
                avg_w = tw / count if count > 0 else 0
                lines.append(f"| {name} | {count} | {pct:.1f}% | {tw:.0f} | {avg_w:.0f} |")
            lines.append("")

        # 杆具配置
        if rod_configs:
            lines.append("## 🎣 杆具配置")
            lines.append("")
            lines.append("| 杆位 | 鱼竿 | 鱼线 | 钩号 | 饵料 |")
            lines.append("|:---|:---|:---|:---|:---|")
            seen = set()
            for cfg in rod_configs:
                slot = cfg.get("rod_slot", 0)
                if slot in seen:
                    continue
                seen.add(slot)
                lines.append(
                    f"| {slot} | {cfg.get('rod_name', '')} "
                    f"| {cfg.get('line_type', '')} {cfg.get('line_strength_kg', 0)}kg "
                    f"| #{cfg.get('hook_size', '')} "
                    f"| {cfg.get('bait_name', '')} |"
                )
            lines.append("")

        # 异常统计
        loss_events = [e for e in events if e.get("event_type") in ("LOSS", "RETRIEVE_TIMEOUT", "TIMEOUT")]
        if loss_events:
            lines.append("## ⚠ 异常事件")
            lines.append("")
            event_types = Counter(e.get("event_type") for e in loss_events)
            lines.append("| 类型 | 次数 |")
            lines.append("|:---|:---|")
            for etype, count in event_types.most_common():
                lines.append(f"| {etype} | {count} |")
            lines.append("")

        # 完成
        lines.append("---")
        lines.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        lines.append("")

        content = "\n".join(lines)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Markdown 报告已生成: %s", output_path)
        return content

    # ── CSV 导出 ─────────────────────────────────────────

    def generate_csv(self, output_dir: Path) -> List[str]:
        """导出 CSV 原始数据。返回生成的文件路径列表。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        files = []

        # catches.csv
        catches = self._get_catches()
        if catches:
            path = output_dir / f"session_{self.session_id}_catches.csv"
            self._write_csv(path, catches)
            files.append(str(path))

        # events.csv
        events = self._get_events()
        if events:
            path = output_dir / f"session_{self.session_id}_events.csv"
            self._write_csv(path, events)
            files.append(str(path))

        # env_snapshots.csv
        env = self._get_env_snapshots()
        if env:
            path = output_dir / f"session_{self.session_id}_env.csv"
            self._write_csv(path, env)
            files.append(str(path))

        logger.info("CSV 已导出 %d 个文件到: %s", len(files), output_dir)
        return files

    @staticmethod
    def _write_csv(path: Path, data: List[dict]) -> None:
        if not data:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)

    # ── 图表 ─────────────────────────────────────────────

    def generate_charts(self, output_dir: Path) -> List[str]:
        """生成基础图表。返回文件路径列表。"""
        if not _HAS_MATPLOTLIB:
            logger.warning("matplotlib 不可用，跳过图表生成")
            return []

        output_dir.mkdir(parents=True, exist_ok=True)
        files = []

        events = self._get_events()
        catches = self._get_catches()
        ttb = self._calc_ttb(events)

        # TTB 分布直方图
        if ttb:
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.hist(ttb, bins=20, color="#4CAF50", edgecolor="white", alpha=0.8)
            ax.set_xlabel("Time to Bite (秒)")
            ax.set_ylabel("频次")
            ax.set_title(f"Session #{self.session_id} — TTB 分布")
            ax.axvline(self._percentile(ttb, 0.5), color="red", linestyle="--",
                        label=f"p50 = {self._percentile(ttb, 0.5):.0f}s")
            ax.legend()
            path = output_dir / f"session_{self.session_id}_ttb.png"
            fig.savefig(str(path), dpi=120, bbox_inches="tight")
            plt.close(fig)
            files.append(str(path))

        # 渔获累计趋势
        successful = [c for c in catches if c.get("outcome") == "CATCH"]
        if successful:
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

            # 累计条数
            times = []
            cumulative = []
            for i, c in enumerate(successful):
                try:
                    t = datetime.fromisoformat(c["ts_land"])
                    times.append(t)
                    cumulative.append(i + 1)
                except (ValueError, KeyError):
                    pass

            if times:
                ax1.plot(times, cumulative, marker=".", color="#2196F3")
                ax1.set_xlabel("时间")
                ax1.set_ylabel("累计渔获 (条)")
                ax1.set_title("渔获累计趋势")
                ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

            # 单条重量散点
            weights = [c.get("weight_g", 0) for c in successful]
            ax2.scatter(range(len(weights)), weights, alpha=0.6, color="#FF9800", s=20)
            ax2.set_xlabel("序号")
            ax2.set_ylabel("重量 (g)")
            ax2.set_title("单条重量分布")
            if weights:
                avg_w = sum(weights) / len(weights)
                ax2.axhline(avg_w, color="red", linestyle="--",
                            label=f"均值 = {avg_w:.0f}g")
                ax2.legend()

            fig.suptitle(f"Session #{self.session_id} 渔获分析", fontsize=14)
            fig.tight_layout()
            path = output_dir / f"session_{self.session_id}_catches.png"
            fig.savefig(str(path), dpi=120, bbox_inches="tight")
            plt.close(fig)
            files.append(str(path))

        logger.info("图表已生成 %d 个文件", len(files))
        return files

    # ── 一键生成全部 ─────────────────────────────────────

    def generate_all(self, output_dir: str | Path = "data/reports") -> dict:
        """
        生成全部报告输出。

        Returns:
            {"markdown": path, "csv_files": [paths], "charts": [paths]}
        """
        out = Path(output_dir) / f"session_{self.session_id}"
        out.mkdir(parents=True, exist_ok=True)

        md_path = out / "report.md"
        self.generate_markdown(md_path)

        csv_files = self.generate_csv(out)
        chart_files = self.generate_charts(out)

        result = {
            "markdown": str(md_path),
            "csv_files": csv_files,
            "charts": chart_files,
        }
        logger.info("所有报告已生成: %s", out)
        return result
