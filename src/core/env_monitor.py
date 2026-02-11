"""
环境快照监控器
=============
定时采集游戏内天气/环境信息（气温、风向、风速、气压等）。

策略: 在所有杆处于 WAITING 状态时，按 M 键打开地图截图天气面板，
然后关闭地图。如果有杆正在操作（HOOKING/RETRIEVING），则跳过本轮。
"""

import time
import logging
from datetime import datetime
from typing import Optional, Dict, Tuple

import numpy as np

from src.core.vision import VisionSensor
from src.drivers.base import InputDriver
from src.data.db import Database
from src.data.models import EnvSnapshot
from src.utils.screenshot import ScreenCapture

logger = logging.getLogger(__name__)


class EnvMonitor:
    """
    环境快照采集器。

    作为 FishingOrchestrator 的 on_tick 回调接入主循环。
    """

    def __init__(
        self,
        session_id: int,
        driver: InputDriver,
        vision: VisionSensor,
        capture: ScreenCapture,
        db: Database,
        interval_s: float = 60,
    ):
        self.session_id = session_id
        self.driver = driver
        self.vision = vision
        self.capture = capture
        self.db = db
        self.interval_s = interval_s

        self._last_capture_time: float = 0
        self._snapshot_count: int = 0

    def should_capture(self, rod_states: Dict[int, str]) -> bool:
        """
        判断是否应采集环境快照。

        条件:
        1. 距上次采集已过 interval_s 秒
        2. 所有杆都处于 WAITING 或 IDLE 状态（不打断操作）
        """
        elapsed = time.time() - self._last_capture_time
        if elapsed < self.interval_s:
            return False

        safe_states = {"WAITING", "IDLE"}
        all_safe = all(s in safe_states for s in rod_states.values())
        return all_safe

    def capture_snapshot(self, frame: Optional[np.ndarray] = None) -> Optional[int]:
        """
        执行一次环境快照采集。

        步骤:
        1. 按 M 键打开地图
        2. 等待 UI 出现
        3. 截图天气面板
        4. OCR 提取信息
        5. 按 M 关闭地图
        6. 保存到数据库

        Returns:
            snapshot_id 或 None
        """
        logger.debug("开始采集环境快照...")

        try:
            # 按 M 打开地图
            self.driver.press("m")
            self.driver.random_delay(0.8, 1.2)  # 等待地图 UI 展开

            # 截图
            frame = self.capture.capture_full_screen()
            evidence_path = self.capture.save_evidence(
                frame, prefix="env_snapshot",
                session_id=self.session_id,
            )

            # OCR 读取天气信息
            weather_result = self.vision.read_weather(frame)

            # 按 M 关闭地图
            self.driver.press("m")
            self.driver.random_delay(0.3, 0.6)

            # 解析天气文本（P0 先存原始文本，后续迭代增强解析）
            weather_text = weather_result.value if weather_result.value else ""

            # 构建快照
            snapshot = EnvSnapshot(
                session_id=self.session_id,
                ts=datetime.now(),
                game_time="",  # TODO: OCR 游戏内时间
                weather=weather_text,
                evidence_path=evidence_path,
            )

            snapshot_id = self.db.save_env_snapshot(snapshot)
            self._snapshot_count += 1
            self._last_capture_time = time.time()

            logger.info(
                "环境快照 #%d 已保存 (conf=%.0f%%): %s",
                self._snapshot_count,
                weather_result.confidence * 100,
                weather_text[:50] if weather_text else "(empty)",
            )
            return snapshot_id

        except Exception as e:
            logger.error("环境快照采集失败: %s", e, exc_info=True)
            # 确保地图关闭（安全措施）
            try:
                self.driver.press("m")
            except Exception:
                pass
            return None

    def on_tick(self, tick_count: int, frame: np.ndarray, rod_states: Dict[int, str]) -> None:
        """
        主循环回调接口。

        由 FishingOrchestrator 每 tick 调用。
        """
        if self.should_capture(rod_states):
            self.capture_snapshot(frame)
