"""
Session 管理器
=============
管理一次完整挂机作业的生命周期:
初始化 → 运行 → 报告 → 清理。
"""

import logging
from datetime import datetime
from typing import Optional, Dict

from src.core.config import ConfigLoader
from src.core.vision import VisionSensor
from src.core.fsm import FishingOrchestrator
from src.core.env_monitor import EnvMonitor
from src.drivers.base import InputDriver
from src.drivers.software import SoftwareInputDriver
from src.data.db import Database
from src.data.models import Session, RodConfig
from src.utils.screenshot import ScreenCapture

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Session 管理器 — 组装所有模块并运行。
    """

    def __init__(self, config: ConfigLoader):
        self.config = config
        self.db = Database(config.get("db_path"))
        self.db.init_schema()

        self.capture = ScreenCapture(config.get("evidence_dir"))

        # 构建 ROI 字典
        roi_dict = {}
        for name in config.roi_names:
            roi = config.get_roi(name)
            if roi:
                roi_dict[name] = roi
        self.vision = VisionSensor(roi_dict)

        # 输入驱动
        self.driver: InputDriver = SoftwareInputDriver(
            delay_multiplier=config.get("input_delay_multiplier", 1.0)
        )

        self.session_id: Optional[int] = None
        self.orchestrator: Optional[FishingOrchestrator] = None
        self.env_monitor: Optional[EnvMonitor] = None

    def start(
        self,
        map_name: str = "Old Burg",
        spot_id: str = "",
        notes: str = "",
        rod_configs: Optional[Dict[int, RodConfig]] = None,
    ) -> int:
        """
        启动一个新 Session。

        Args:
            map_name: 地图名称
            spot_id: 钓点坐标
            notes: 备注
            rod_configs: 可选的初始杆具配置

        Returns:
            session_id
        """
        session = Session(
            map_name=map_name,
            spot_id=spot_id,
            render_width=self.config.get("render_width"),
            render_height=self.config.get("render_height"),
            roi_version=self.config.roi_version,
            notes=notes,
        )
        self.session_id = self.db.create_session(session)
        logger.info("Session #%d 已启动", self.session_id)

        # 保存初始杆具配置
        if rod_configs:
            for slot, cfg in rod_configs.items():
                cfg.session_id = self.session_id
                cfg.rod_slot = slot
                self.db.save_rod_config(cfg)

        # 创建协调器
        self.orchestrator = FishingOrchestrator(
            session_id=self.session_id,
            driver=self.driver,
            vision=self.vision,
            capture=self.capture,
            db=self.db,
            wait_timeout_s=self.config.get("wait_timeout_s", 1200),
            retrieve_timeout_s=self.config.get("retrieve_timeout_s", 180),
        )

        # 创建环境监控
        self.env_monitor = EnvMonitor(
            session_id=self.session_id,
            driver=self.driver,
            vision=self.vision,
            capture=self.capture,
            db=self.db,
            interval_s=self.config.get("env_snapshot_interval_s", 60),
        )

        # 绑定 tick 回调
        def _tick_callback(tick_count, frame):
            states = self.orchestrator.get_status()
            self.env_monitor.on_tick(tick_count, frame, states)

        self.orchestrator.set_on_tick(_tick_callback)

        return self.session_id

    def run(self) -> None:
        """运行主循环（阻塞）。"""
        if not self.orchestrator:
            raise RuntimeError("请先调用 start()")
        self.orchestrator.start()

    def stop(self) -> dict:
        """
        停止 Session 并返回统计摘要。

        Returns:
            Session 统计字典
        """
        if self.orchestrator:
            self.orchestrator.stop()

        if self.session_id:
            self.db.end_session(self.session_id)
            stats = self.db.get_session_stats(self.session_id)
        else:
            stats = {}

        self.capture.close()
        self.db.close()

        logger.info("Session #%s 已关闭", self.session_id)
        return stats
