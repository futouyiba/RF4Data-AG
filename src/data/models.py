"""
数据模型（Data Models）
======================
对应 SQLite 数据库的 5 张表，使用 dataclass 定义。
用于在 Python 层传递结构化数据。
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class Session:
    """实验会话 —— 一次完整的挂机作业。"""
    session_id: Optional[int] = None
    map_name: str = "Old Burg"
    spot_id: str = ""             # 钓点坐标，如 "35:67"
    start_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None
    render_width: int = 1920
    render_height: int = 1080
    roi_version: str = ""         # roi_config.json 的哈希或版本号
    notes: str = ""


@dataclass
class RodConfig:
    """
    杆具配置快照 —— 弥补起鱼弹窗不显示饵料的缺陷。
    每次换饵/换钩/换线时手动或自动更新。
    """
    session_id: Optional[int] = None
    rod_slot: int = 1             # 1, 2, 3
    rod_name: str = ""
    reel_name: str = ""
    line_type: str = ""
    line_strength_kg: float = 0.0
    hook_size: str = ""           # 如 "10", "12"
    bait_name: str = ""           # 如 "Garlic Dough", "Maggot"
    groundbait_recipe: str = ""
    clip_depth_m: Optional[int] = None
    updated_ts: Optional[datetime] = None


@dataclass
class EnvSnapshot:
    """
    环境快照 —— 定时采集的游戏内天气/环境信息。
    通过 ts 与 events/catches 关联。
    """
    snapshot_id: Optional[int] = None
    session_id: Optional[int] = None
    ts: Optional[datetime] = None
    game_time: str = ""           # 游戏内时间，如 "04:00"
    weather: str = ""             # 天气描述
    wind_dir: str = ""            # 风向
    wind_speed: Optional[float] = None
    pressure: Optional[float] = None      # 气压 (mmHg)
    water_temp: Optional[float] = None    # 水温 (°C)
    evidence_path: str = ""       # 截图路径


@dataclass
class Event:
    """
    事件日志 —— 三杆状态机的所有状态变化。
    event_type: CAST, BITE, HOOK, RETRIEVE_START, CATCH, LOSS, TIMEOUT, RESET
    """
    event_id: Optional[int] = None
    session_id: Optional[int] = None
    ts: Optional[datetime] = None
    rod_slot: int = 1
    event_type: str = ""
    value_json: str = "{}"        # 附加数据（JSON 字符串）
    confidence: float = 1.0       # 识别置信度 [0, 1]
    evidence_path: str = ""       # 关键帧截图路径


@dataclass
class Catch:
    """
    渔获记录 —— 每次成功起鱼的详细数据。
    通过 rod_slot + session_id 可 JOIN 到 rod_configs 获取饵料等配置。
    """
    catch_id: Optional[int] = None
    session_id: Optional[int] = None
    ts_land: Optional[datetime] = None
    rod_slot: int = 1
    fish_name_raw: str = ""       # OCR 原始识别的鱼名
    weight_g: float = 0.0         # 重量（克）
    value: float = 0.0            # 售价
    trophy_flag: bool = False
    fight_time_s: float = 0.0     # 遛鱼时长（秒）
    outcome: str = "CATCH"        # CATCH / LOSS / LINE_BREAK
    env_ref_ts: Optional[datetime] = None  # 最近的环境快照时间戳
    evidence_path: str = ""       # 截图路径
    confidence: float = 1.0       # OCR 识别置信度
