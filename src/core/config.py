"""
配置管理模块
===========
处理全局设置（settings.json）和 ROI 区域配置（roi_config.json）。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 默认配置 ────────────────────────────────────────────

DEFAULT_SETTINGS = {
    # 显示
    "render_width": 1920,
    "render_height": 1080,
    "window_title": "Russian Fishing 4",

    # 数据库
    "db_path": "data/rf4_research.db",

    # 环境快照
    "env_snapshot_interval_s": 60,

    # FSM 超时
    "wait_timeout_s": 1200,       # 20 分钟无口 → 重置
    "retrieve_timeout_s": 180,    # 3 分钟收不上来 → 可能挂底

    # 输入延迟倍率
    "input_delay_multiplier": 1.0,

    # OCR
    "ocr_lang": "eng+chi_sim",
    "ocr_confidence_threshold": 0.6,

    # Evidence 截图
    "save_evidence": True,
    "evidence_dir": "data/evidence",

    # 报告输出
    "report_dir": "data/reports",
}


class ConfigLoader:
    """
    配置加载器。

    优先顺序: settings.json > 默认值
    """

    def __init__(self, config_dir: str | Path = "config"):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self._settings_path = self.config_dir / "settings.json"
        self._roi_path = self.config_dir / "roi_config.json"

        self._settings: Dict[str, Any] = {}
        self._roi: Dict[str, Dict[str, int]] = {}

        self._load_settings()
        self._load_roi()

    # ── Settings ────────────────────────────────────────

    def _load_settings(self) -> None:
        """加载 settings.json，缺失键用默认值填充。"""
        self._settings = dict(DEFAULT_SETTINGS)
        if self._settings_path.exists():
            try:
                with open(self._settings_path, "r", encoding="utf-8") as f:
                    user_settings = json.load(f)
                self._settings.update(user_settings)
                logger.info("已加载配置: %s", self._settings_path)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("配置文件读取失败，使用默认值: %s", e)
        else:
            self.save_settings()
            logger.info("已生成默认配置: %s", self._settings_path)

    def save_settings(self) -> None:
        """持久化当前设置。"""
        with open(self._settings_path, "w", encoding="utf-8") as f:
            json.dump(self._settings, f, indent=2, ensure_ascii=False)

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._settings[key] = value

    @property
    def settings(self) -> Dict[str, Any]:
        return self._settings

    # ── ROI Config ──────────────────────────────────────

    def _load_roi(self) -> None:
        """加载 roi_config.json。"""
        if self._roi_path.exists():
            try:
                with open(self._roi_path, "r", encoding="utf-8") as f:
                    self._roi = json.load(f)
                logger.info("已加载 ROI 配置: %s (%d 个区域)", self._roi_path, len(self._roi))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("ROI 配置读取失败: %s", e)
                self._roi = {}
        else:
            logger.warning("ROI 配置文件不存在: %s，请先运行校准工具", self._roi_path)
            self._roi = {}

    def save_roi(self, roi_data: Dict[str, Dict[str, int]]) -> None:
        """保存 ROI 配置。"""
        self._roi = roi_data
        with open(self._roi_path, "w", encoding="utf-8") as f:
            json.dump(self._roi, f, indent=2, ensure_ascii=False)
        logger.info("ROI 配置已保存: %s", self._roi_path)

    def get_roi(self, name: str) -> Optional[Tuple[int, int, int, int]]:
        """
        获取某个 ROI 区域。

        返回 (x, y, w, h) 或 None。
        """
        region = self._roi.get(name)
        if region:
            return (region["x"], region["y"], region["w"], region["h"])
        return None

    @property
    def roi_names(self) -> list:
        """当前已配置的 ROI 名称列表。"""
        return list(self._roi.keys())

    @property
    def has_roi(self) -> bool:
        """是否已完成 ROI 校准。"""
        required = ["rod_1_indicator", "rod_2_indicator", "rod_3_indicator", "chat_box"]
        return all(name in self._roi for name in required)

    @property
    def roi_version(self) -> str:
        """ROI 配置的简易版本标识（基于内容哈希）。"""
        import hashlib
        content = json.dumps(self._roi, sort_keys=True)
        return hashlib.md5(content.encode()).hexdigest()[:8]
