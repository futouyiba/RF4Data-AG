"""
数据质量模块
===========
评估 Session 数据的完整性和可靠性。

指标:
- OCR 识别成功率
- Evidence 截图覆盖率
- 事件完整性（每次 CATCH 是否有对应的 CAST → BITE 链）
- 环境快照缺失率
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, field

from src.data.db import Database

logger = logging.getLogger(__name__)


@dataclass
class QualityReport:
    """数据质量评估报告。"""
    session_id: int
    total_events: int = 0
    total_catches: int = 0
    total_env_snapshots: int = 0

    # OCR 质量
    ocr_high_confidence: int = 0       # confidence >= 0.8
    ocr_medium_confidence: int = 0     # 0.5 <= confidence < 0.8
    ocr_low_confidence: int = 0        # confidence < 0.5
    ocr_avg_confidence: float = 0.0

    # Evidence 覆盖
    catches_with_evidence: int = 0
    events_with_evidence: int = 0
    evidence_coverage_pct: float = 0.0

    # 事件链完整性
    complete_chains: int = 0           # CAST → BITE → CATCH 完整链
    broken_chains: int = 0             # 缺少环节的链

    # 环境快照
    session_duration_min: float = 0.0
    expected_snapshots: int = 0        # 按 60s 间隔期望值
    snapshot_coverage_pct: float = 0.0

    # 综合评分
    overall_score: float = 0.0        # 0-100

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    def grade(self) -> str:
        """根据评分返回等级。"""
        if self.overall_score >= 90:
            return "A"
        elif self.overall_score >= 75:
            return "B"
        elif self.overall_score >= 60:
            return "C"
        elif self.overall_score >= 40:
            return "D"
        return "F"


class DataQualityAnalyzer:
    """数据质量分析器。"""

    def __init__(self, db: Database, session_id: int, env_interval_s: float = 60):
        self.db = db
        self.session_id = session_id
        self.env_interval_s = env_interval_s

    def analyze(self) -> QualityReport:
        """执行完整的数据质量分析。"""
        report = QualityReport(session_id=self.session_id)

        catches = self.db.get_catches(self.session_id)
        events = self.db.get_events(self.session_id)
        env_snapshots = self._get_env_snapshots()
        session = self._get_session()

        report.total_events = len(events)
        report.total_catches = len(catches)
        report.total_env_snapshots = len(env_snapshots)

        self._analyze_ocr_quality(report, catches, events)
        self._analyze_evidence(report, catches, events)
        self._analyze_event_chains(report, events, catches)
        self._analyze_env_coverage(report, session, env_snapshots)
        self._calc_overall_score(report)

        return report

    def _get_env_snapshots(self) -> List[dict]:
        rows = self.db.conn.execute(
            "SELECT * FROM env_snapshots WHERE session_id = ?",
            (self.session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _get_session(self) -> Optional[dict]:
        row = self.db.conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (self.session_id,),
        ).fetchone()
        return dict(row) if row else None

    def _analyze_ocr_quality(self, report: QualityReport,
                              catches: List[dict], events: List[dict]):
        """分析 OCR 识别置信度分布。"""
        confidences = []
        for c in catches:
            conf = c.get("confidence", 0)
            confidences.append(conf)
        for e in events:
            conf = e.get("confidence", 0)
            if conf > 0:
                confidences.append(conf)

        if not confidences:
            return

        report.ocr_avg_confidence = sum(confidences) / len(confidences)
        report.ocr_high_confidence = sum(1 for c in confidences if c >= 0.8)
        report.ocr_medium_confidence = sum(1 for c in confidences if 0.5 <= c < 0.8)
        report.ocr_low_confidence = sum(1 for c in confidences if c < 0.5)

    def _analyze_evidence(self, report: QualityReport,
                           catches: List[dict], events: List[dict]):
        """分析 evidence 截图覆盖情况。"""
        report.catches_with_evidence = sum(
            1 for c in catches if c.get("evidence_path", "").strip()
        )
        report.events_with_evidence = sum(
            1 for e in events if e.get("evidence_path", "").strip()
        )

        total = report.total_catches + report.total_events
        with_evidence = report.catches_with_evidence + report.events_with_evidence
        report.evidence_coverage_pct = (
            (with_evidence / total * 100) if total > 0 else 0
        )

    def _analyze_event_chains(self, report: QualityReport,
                               events: List[dict], catches: List[dict]):
        """分析事件链完整性（CAST → BITE → CATCH）。"""
        # 按杆分组
        rod_events: Dict[int, List[dict]] = {}
        for e in events:
            slot = e.get("rod_slot", 0)
            rod_events.setdefault(slot, []).append(e)

        complete = 0
        broken = 0

        for slot, evts in rod_events.items():
            sorted_evts = sorted(evts, key=lambda x: x.get("ts", ""))
            chain = []
            for e in sorted_evts:
                etype = e.get("event_type", "")
                if "CAST" in etype:
                    chain = ["CAST"]
                elif "BITE" in etype or "HOOK" in etype:
                    if "CAST" in chain:
                        chain.append("BITE")
                    else:
                        broken += 1
                        chain = []
                elif "CATCH" in etype or "LOGGING" in etype:
                    if "BITE" in chain:
                        complete += 1
                    else:
                        broken += 1
                    chain = []
                elif "LOSS" in etype or "TIMEOUT" in etype:
                    chain = []

        report.complete_chains = complete
        report.broken_chains = broken

    def _analyze_env_coverage(self, report: QualityReport,
                               session: Optional[dict],
                               env_snapshots: List[dict]):
        """分析环境快照覆盖率。"""
        if not session:
            return

        start_str = session.get("start_ts", "")
        end_str = session.get("end_ts", "")
        if not start_str:
            return

        try:
            start = datetime.fromisoformat(start_str)
            end = datetime.fromisoformat(end_str) if end_str else datetime.now()
        except ValueError:
            return

        duration_s = (end - start).total_seconds()
        report.session_duration_min = duration_s / 60

        if duration_s > 0:
            report.expected_snapshots = max(1, int(duration_s / self.env_interval_s))
            report.snapshot_coverage_pct = min(
                100,
                report.total_env_snapshots / report.expected_snapshots * 100,
            )

    def _calc_overall_score(self, report: QualityReport):
        """计算综合评分 (0-100)。"""
        scores = []

        # OCR 质量 (权重 30%)
        if report.ocr_avg_confidence > 0:
            scores.append(report.ocr_avg_confidence * 100 * 0.3)
        else:
            scores.append(50 * 0.3)  # 无数据给中等分

        # Evidence 覆盖 (权重 20%)
        scores.append(report.evidence_coverage_pct * 0.2)

        # 事件链完整性 (权重 30%)
        total_chains = report.complete_chains + report.broken_chains
        if total_chains > 0:
            chain_pct = report.complete_chains / total_chains * 100
            scores.append(chain_pct * 0.3)
        else:
            scores.append(50 * 0.3)

        # 环境快照覆盖 (权重 20%)
        scores.append(report.snapshot_coverage_pct * 0.2)

        report.overall_score = round(sum(scores), 1)

    # ── 格式化输出 ───────────────────────────────────────

    def to_markdown(self, report: QualityReport) -> str:
        """生成 Markdown 格式的质量报告。"""
        grade = report.grade()
        lines = [
            f"## 📋 数据质量报告",
            "",
            f"**综合评分**: {report.overall_score:.0f}/100 (等级 {grade})",
            "",
            "| 维度 | 指标 | 值 |",
            "|:---|:---|:---|",
            f"| OCR 质量 | 平均置信度 | {report.ocr_avg_confidence:.0%} |",
            f"| | 高置信度 (≥80%) | {report.ocr_high_confidence} 条 |",
            f"| | 低置信度 (<50%) | {report.ocr_low_confidence} 条 |",
            f"| Evidence | 截图覆盖率 | {report.evidence_coverage_pct:.0f}% |",
            f"| 事件链 | 完整链 | {report.complete_chains} |",
            f"| | 断裂链 | {report.broken_chains} |",
            f"| 环境快照 | 实际/期望 | {report.total_env_snapshots}/{report.expected_snapshots} |",
            f"| | 覆盖率 | {report.snapshot_coverage_pct:.0f}% |",
            "",
        ]
        return "\n".join(lines)
