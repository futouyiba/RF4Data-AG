"""
SQLite 数据库管理模块
===================
负责数据库初始化、表创建、以及所有 CRUD 操作。
数据库文件默认在 data/rf4_research.db。
"""

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from .models import Session, RodConfig, EnvSnapshot, Event, Catch

logger = logging.getLogger(__name__)

# ── SQL Schema ────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    map_name        TEXT    NOT NULL DEFAULT 'Old Burg',
    spot_id         TEXT    DEFAULT '',
    start_ts        TEXT    NOT NULL,
    end_ts          TEXT,
    render_width    INTEGER DEFAULT 1920,
    render_height   INTEGER DEFAULT 1080,
    roi_version     TEXT    DEFAULT '',
    notes           TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS rod_configs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id         INTEGER NOT NULL REFERENCES sessions(session_id),
    rod_slot           INTEGER NOT NULL CHECK (rod_slot BETWEEN 1 AND 3),
    rod_name           TEXT    DEFAULT '',
    reel_name          TEXT    DEFAULT '',
    line_type          TEXT    DEFAULT '',
    line_strength_kg   REAL    DEFAULT 0,
    hook_size          TEXT    DEFAULT '',
    bait_name          TEXT    DEFAULT '',
    groundbait_recipe  TEXT    DEFAULT '',
    clip_depth_m       INTEGER,
    updated_ts         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS env_snapshots (
    snapshot_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES sessions(session_id),
    ts             TEXT    NOT NULL,
    game_time      TEXT    DEFAULT '',
    weather        TEXT    DEFAULT '',
    wind_dir       TEXT    DEFAULT '',
    wind_speed     REAL,
    pressure       REAL,
    water_temp     REAL,
    evidence_path  TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES sessions(session_id),
    ts             TEXT    NOT NULL,
    rod_slot       INTEGER NOT NULL CHECK (rod_slot BETWEEN 1 AND 3),
    event_type     TEXT    NOT NULL,
    value_json     TEXT    DEFAULT '{}',
    confidence     REAL    DEFAULT 1.0,
    evidence_path  TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS catches (
    catch_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES sessions(session_id),
    ts_land        TEXT    NOT NULL,
    rod_slot       INTEGER NOT NULL CHECK (rod_slot BETWEEN 1 AND 3),
    fish_name_raw  TEXT    DEFAULT '',
    weight_g       REAL    DEFAULT 0,
    value          REAL    DEFAULT 0,
    trophy_flag    INTEGER DEFAULT 0,
    fight_time_s   REAL    DEFAULT 0,
    outcome        TEXT    DEFAULT 'CATCH',
    env_ref_ts     TEXT,
    evidence_path  TEXT    DEFAULT '',
    confidence     REAL    DEFAULT 1.0
);

-- 常用查询索引
CREATE INDEX IF NOT EXISTS idx_events_session     ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_type        ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_catches_session    ON catches(session_id);
CREATE INDEX IF NOT EXISTS idx_env_session        ON env_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_rod_configs_session ON rod_configs(session_id);
"""


class Database:
    """SQLite 数据库管理器。"""

    def __init__(self, db_path: str | Path = "data/rf4_research.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    # ── 连接管理 ─────────────────────────────────────────

    def connect(self) -> sqlite3.Connection:
        """打开连接并启用外键。"""
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.row_factory = sqlite3.Row
            logger.info("数据库已连接: %s", self.db_path)
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("数据库已关闭")

    @property
    def conn(self) -> sqlite3.Connection:
        return self.connect()

    def init_schema(self) -> None:
        """创建所有表（如果不存在）。"""
        self.conn.executescript(_SCHEMA_SQL)
        self.conn.commit()
        logger.info("数据库 Schema 初始化完成")

    # ── Session CRUD ─────────────────────────────────────

    def create_session(self, session: Session) -> int:
        """创建新 Session，返回 session_id。"""
        now = session.start_ts or datetime.now()
        cur = self.conn.execute(
            """INSERT INTO sessions
               (map_name, spot_id, start_ts, render_width, render_height, roi_version, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session.map_name, session.spot_id, now.isoformat(),
             session.render_width, session.render_height,
             session.roi_version, session.notes),
        )
        self.conn.commit()
        session.session_id = cur.lastrowid
        logger.info("Session #%d 已创建", session.session_id)
        return session.session_id

    def end_session(self, session_id: int) -> None:
        """结束 Session，写入 end_ts。"""
        self.conn.execute(
            "UPDATE sessions SET end_ts = ? WHERE session_id = ?",
            (datetime.now().isoformat(), session_id),
        )
        self.conn.commit()
        logger.info("Session #%d 已结束", session_id)

    # ── RodConfig CRUD ───────────────────────────────────

    def save_rod_config(self, config: RodConfig) -> int:
        """保存/更新杆具配置。"""
        now = config.updated_ts or datetime.now()
        cur = self.conn.execute(
            """INSERT INTO rod_configs
               (session_id, rod_slot, rod_name, reel_name, line_type,
                line_strength_kg, hook_size, bait_name, groundbait_recipe,
                clip_depth_m, updated_ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (config.session_id, config.rod_slot, config.rod_name,
             config.reel_name, config.line_type, config.line_strength_kg,
             config.hook_size, config.bait_name, config.groundbait_recipe,
             config.clip_depth_m, now.isoformat()),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_latest_rod_config(self, session_id: int, rod_slot: int) -> Optional[dict]:
        """获取某根杆最新的配置（用于关联渔获）。"""
        row = self.conn.execute(
            """SELECT * FROM rod_configs
               WHERE session_id = ? AND rod_slot = ?
               ORDER BY updated_ts DESC LIMIT 1""",
            (session_id, rod_slot),
        ).fetchone()
        return dict(row) if row else None

    # ── EnvSnapshot CRUD ────────────────────────────────

    def save_env_snapshot(self, snap: EnvSnapshot) -> int:
        now = snap.ts or datetime.now()
        cur = self.conn.execute(
            """INSERT INTO env_snapshots
               (session_id, ts, game_time, weather, wind_dir,
                wind_speed, pressure, water_temp, evidence_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (snap.session_id, now.isoformat(), snap.game_time,
             snap.weather, snap.wind_dir, snap.wind_speed,
             snap.pressure, snap.water_temp, snap.evidence_path),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_nearest_env(self, session_id: int, ts: datetime) -> Optional[dict]:
        """获取最近的环境快照。"""
        row = self.conn.execute(
            """SELECT * FROM env_snapshots
               WHERE session_id = ?
               ORDER BY ABS(JULIANDAY(ts) - JULIANDAY(?))
               LIMIT 1""",
            (session_id, ts.isoformat()),
        ).fetchone()
        return dict(row) if row else None

    # ── Event CRUD ──────────────────────────────────────

    def log_event(self, event: Event) -> int:
        now = event.ts or datetime.now()
        cur = self.conn.execute(
            """INSERT INTO events
               (session_id, ts, rod_slot, event_type,
                value_json, confidence, evidence_path)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event.session_id, now.isoformat(), event.rod_slot,
             event.event_type, event.value_json,
             event.confidence, event.evidence_path),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_events(
        self,
        session_id: int,
        event_type: Optional[str] = None,
        rod_slot: Optional[int] = None,
    ) -> List[dict]:
        """查询事件列表。"""
        query = "SELECT * FROM events WHERE session_id = ?"
        params: list = [session_id]
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if rod_slot is not None:
            query += " AND rod_slot = ?"
            params.append(rod_slot)
        query += " ORDER BY ts"
        return [dict(r) for r in self.conn.execute(query, params).fetchall()]

    # ── Catch CRUD ──────────────────────────────────────

    def save_catch(self, catch: Catch) -> int:
        now = catch.ts_land or datetime.now()
        cur = self.conn.execute(
            """INSERT INTO catches
               (session_id, ts_land, rod_slot, fish_name_raw,
                weight_g, value, trophy_flag, fight_time_s,
                outcome, env_ref_ts, evidence_path, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (catch.session_id, now.isoformat(), catch.rod_slot,
             catch.fish_name_raw, catch.weight_g, catch.value,
             int(catch.trophy_flag), catch.fight_time_s,
             catch.outcome,
             catch.env_ref_ts.isoformat() if catch.env_ref_ts else None,
             catch.evidence_path, catch.confidence),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_catches(self, session_id: int) -> List[dict]:
        """获取某 Session 的所有渔获。"""
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM catches WHERE session_id = ? ORDER BY ts_land",
                (session_id,),
            ).fetchall()
        ]

    # ── 统计查询（供报告模块使用）────────────────────────

    def get_session_stats(self, session_id: int) -> dict:
        """获取 Session 统计摘要。"""
        catches = self.get_catches(session_id)
        events = self.get_events(session_id)

        total_catch = len([c for c in catches if c["outcome"] == "CATCH"])
        total_loss = len([c for c in catches if c["outcome"] != "CATCH"])
        total_weight = sum(c["weight_g"] for c in catches if c["outcome"] == "CATCH")
        total_value = sum(c["value"] for c in catches if c["outcome"] == "CATCH")
        trophies = len([c for c in catches if c["trophy_flag"]])

        # 计算 Session 时长
        session = self.conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        duration_h = 0.0
        if session:
            start = datetime.fromisoformat(session["start_ts"])
            end_str = session["end_ts"]
            end = datetime.fromisoformat(end_str) if end_str else datetime.now()
            duration_h = (end - start).total_seconds() / 3600

        return {
            "session_id": session_id,
            "duration_hours": round(duration_h, 2),
            "total_catch": total_catch,
            "total_loss": total_loss,
            "total_weight_g": round(total_weight, 1),
            "total_value": round(total_value, 1),
            "trophies": trophies,
            "cpue_fish_per_hour": round(total_catch / duration_h, 2) if duration_h > 0 else 0,
            "cpue_weight_per_hour": round(total_weight / duration_h, 1) if duration_h > 0 else 0,
            "total_events": len(events),
        }
