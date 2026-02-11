"""
视觉感知模块 (Vision Sensor)
============================
负责从游戏画面中提取关键信息:
1. 鱼口检测（Rod Indicator 图标颜色变化）
2. 拉力条状态（Tension Bar 颜色分区）
3. 聊天框 OCR（渔获信息提取）
4. 环境信息 OCR（天气面板读取）

所有检测均返回 (结果, 置信度) 元组。
"""

import logging
from enum import Enum, auto
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ── 枚举 & 数据类 ───────────────────────────────────────

class BiteStatus(Enum):
    """鱼口状态。"""
    NONE = auto()       # 无信号
    NIBBLE = auto()     # 轻微试探（黄色）
    BITE = auto()       # 明确咬钩（红色/亮红）


class TensionZone(Enum):
    """拉力条区域。"""
    SAFE = auto()       # 绿色 — 安全，可以收线
    WARNING = auto()    # 黄色 — 注意
    DANGER = auto()     # 红色 — 危险，需放线
    GONE = auto()       # 拉力条消失（鱼跑了/未在收线状态）


@dataclass
class DetectionResult:
    """通用检测结果。"""
    value: object           # 检测到的值
    confidence: float       # 0.0 ~ 1.0
    raw_metrics: dict = None  # 原始指标（调试用）

    def __post_init__(self):
        if self.raw_metrics is None:
            self.raw_metrics = {}


class VisionSensor:
    """
    视觉感知器。

    需要 ROI 配置才能工作。与截图工具配合使用:
    frame = capture.capture_full_screen()
    bite = sensor.detect_bite(1, frame)
    """

    def __init__(
        self,
        roi_config: Dict[str, Tuple[int, int, int, int]],
        bite_red_threshold: float = 0.15,
        bite_yellow_threshold: float = 0.10,
        tension_min_pixels: int = 50,
    ):
        """
        Args:
            roi_config: {name: (x, y, w, h)} ROI 字典
            bite_red_threshold: 红色像素占比阈值 → BITE
            bite_yellow_threshold: 黄色像素占比阈值 → NIBBLE
            tension_min_pixels: 拉力条最小有效像素数
        """
        self.rois = roi_config
        self.bite_red_threshold = bite_red_threshold
        self.bite_yellow_threshold = bite_yellow_threshold
        self.tension_min_pixels = tension_min_pixels

        # OCR 引擎（延迟初始化）
        self._ocr = None

    def _get_ocr(self):
        if self._ocr is None:
            from src.utils.ocr import OCREngine
            self._ocr = OCREngine()
        return self._ocr

    def _crop_roi(self, frame: np.ndarray, roi_name: str) -> Optional[np.ndarray]:
        """从全屏帧中裁切 ROI 区域。"""
        roi = self.rois.get(roi_name)
        if roi is None:
            logger.warning("ROI 未配置: %s", roi_name)
            return None
        x, y, w, h = roi
        return frame[y : y + h, x : x + w].copy()

    # ── 鱼口检测 ─────────────────────────────────────────

    # HSV 颜色范围定义
    # 红色（H 分两段：0-10 和 170-180）
    _RED_LOWER_1 = np.array([0, 100, 100])
    _RED_UPPER_1 = np.array([10, 255, 255])
    _RED_LOWER_2 = np.array([170, 100, 100])
    _RED_UPPER_2 = np.array([180, 255, 255])

    # 黄色/橙色
    _YELLOW_LOWER = np.array([15, 100, 100])
    _YELLOW_UPPER = np.array([35, 255, 255])

    def detect_bite(self, rod_slot: int, frame: np.ndarray) -> DetectionResult:
        """
        检测某根杆是否有鱼口。

        通过分析杆图标区域的红色/黄色像素占比来判断。

        Args:
            rod_slot: 1, 2, 3
            frame: 全屏 BGR 帧

        Returns:
            DetectionResult(value=BiteStatus, confidence, raw_metrics)
        """
        roi_name = f"rod_{rod_slot}_indicator"
        crop = self._crop_roi(frame, roi_name)
        if crop is None:
            return DetectionResult(BiteStatus.NONE, 0.0)

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        total_pixels = crop.shape[0] * crop.shape[1]

        if total_pixels == 0:
            return DetectionResult(BiteStatus.NONE, 0.0)

        # 检测红色像素
        mask_red1 = cv2.inRange(hsv, self._RED_LOWER_1, self._RED_UPPER_1)
        mask_red2 = cv2.inRange(hsv, self._RED_LOWER_2, self._RED_UPPER_2)
        mask_red = cv2.bitwise_or(mask_red1, mask_red2)
        red_ratio = np.count_nonzero(mask_red) / total_pixels

        # 检测黄色像素
        mask_yellow = cv2.inRange(hsv, self._YELLOW_LOWER, self._YELLOW_UPPER)
        yellow_ratio = np.count_nonzero(mask_yellow) / total_pixels

        metrics = {
            "red_ratio": round(red_ratio, 4),
            "yellow_ratio": round(yellow_ratio, 4),
            "total_pixels": total_pixels,
        }

        # 判定
        if red_ratio >= self.bite_red_threshold:
            confidence = min(1.0, red_ratio / self.bite_red_threshold)
            return DetectionResult(BiteStatus.BITE, confidence, metrics)
        elif yellow_ratio >= self.bite_yellow_threshold:
            confidence = min(1.0, yellow_ratio / self.bite_yellow_threshold)
            return DetectionResult(BiteStatus.NIBBLE, confidence, metrics)
        else:
            # 无咬口时置信度 = 1 - 最大颜色比例（越少颜色越确信是 NONE）
            max_ratio = max(red_ratio, yellow_ratio)
            confidence = 1.0 - max_ratio
            return DetectionResult(BiteStatus.NONE, confidence, metrics)

    def detect_all_bites(self, frame: np.ndarray) -> Dict[int, DetectionResult]:
        """一次检测三根杆的鱼口状态。"""
        return {
            slot: self.detect_bite(slot, frame)
            for slot in (1, 2, 3)
        }

    # ── 拉力条检测 ───────────────────────────────────────

    # 拉力条颜色范围
    _GREEN_LOWER = np.array([35, 80, 80])
    _GREEN_UPPER = np.array([85, 255, 255])

    _TENSION_YELLOW_LOWER = np.array([20, 80, 80])
    _TENSION_YELLOW_UPPER = np.array([35, 255, 255])

    _TENSION_RED_LOWER_1 = np.array([0, 80, 80])
    _TENSION_RED_UPPER_1 = np.array([10, 255, 255])
    _TENSION_RED_LOWER_2 = np.array([170, 80, 80])
    _TENSION_RED_UPPER_2 = np.array([180, 255, 255])

    def detect_tension(self, frame: np.ndarray) -> DetectionResult:
        """
        检测拉力条当前状态。

        Returns:
            DetectionResult(value=TensionZone, confidence, raw_metrics)
        """
        crop = self._crop_roi(frame, "tension_bar")
        if crop is None:
            return DetectionResult(TensionZone.GONE, 0.0)

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        total_pixels = crop.shape[0] * crop.shape[1]

        if total_pixels == 0:
            return DetectionResult(TensionZone.GONE, 0.0)

        # 统计各颜色像素
        mask_green = cv2.inRange(hsv, self._GREEN_LOWER, self._GREEN_UPPER)
        mask_yellow = cv2.inRange(hsv, self._TENSION_YELLOW_LOWER, self._TENSION_YELLOW_UPPER)
        mask_red1 = cv2.inRange(hsv, self._TENSION_RED_LOWER_1, self._TENSION_RED_UPPER_1)
        mask_red2 = cv2.inRange(hsv, self._TENSION_RED_LOWER_2, self._TENSION_RED_UPPER_2)
        mask_red = cv2.bitwise_or(mask_red1, mask_red2)

        green_count = np.count_nonzero(mask_green)
        yellow_count = np.count_nonzero(mask_yellow)
        red_count = np.count_nonzero(mask_red)
        colored_total = green_count + yellow_count + red_count

        metrics = {
            "green_px": green_count,
            "yellow_px": yellow_count,
            "red_px": red_count,
            "colored_total": colored_total,
            "total_pixels": total_pixels,
        }

        # 颜色像素太少 → 拉力条不可见
        if colored_total < self.tension_min_pixels:
            return DetectionResult(TensionZone.GONE, 0.8, metrics)

        # 根据占比最大的颜色判定
        if red_count >= yellow_count and red_count >= green_count:
            # 红色主导 → 危险
            confidence = red_count / colored_total
            return DetectionResult(TensionZone.DANGER, confidence, metrics)
        elif yellow_count >= green_count:
            # 黄色主导 → 警告
            confidence = yellow_count / colored_total
            return DetectionResult(TensionZone.WARNING, confidence, metrics)
        else:
            # 绿色主导 → 安全
            confidence = green_count / colored_total
            return DetectionResult(TensionZone.SAFE, confidence, metrics)

    # ── 聊天框 OCR ───────────────────────────────────────

    def read_chat(self, frame: np.ndarray) -> DetectionResult:
        """
        读取聊天框文字（用于检测渔获信息）。

        Returns:
            DetectionResult(value=str(文本), confidence)
        """
        crop = self._crop_roi(frame, "chat_box")
        if crop is None:
            return DetectionResult("", 0.0)

        ocr = self._get_ocr()
        text, confidence = ocr.recognize(crop, preprocess_mode="dark_bg")
        return DetectionResult(text, confidence)

    def detect_catch_from_chat(self, frame: np.ndarray) -> DetectionResult:
        """
        从聊天框中检测渔获信息。

        Returns:
            DetectionResult(value=dict|None, confidence)
            value = {"fish_name": str, "weight_kg": float} 或 None
        """
        chat_result = self.read_chat(frame)
        if not chat_result.value:
            return DetectionResult(None, 0.0)

        ocr = self._get_ocr()
        catch = ocr.extract_catch(chat_result.value)
        return DetectionResult(catch, chat_result.confidence)

    # ── 环境信息 OCR ────────────────────────────────────

    def read_weather(self, frame: np.ndarray) -> DetectionResult:
        """
        读取天气面板信息（需要先按 M 键打开地图）。

        Returns:
            DetectionResult(value=str(原始文本), confidence)
        """
        crop = self._crop_roi(frame, "weather_area")
        if crop is None:
            return DetectionResult("", 0.0)

        ocr = self._get_ocr()
        text, confidence = ocr.recognize(crop, preprocess_mode="light_bg")
        return DetectionResult(text, confidence)

    # ── 调试工具 ─────────────────────────────────────────

    def debug_visualize(self, frame: np.ndarray, save_path: Optional[str] = None) -> np.ndarray:
        """
        在帧上绘制所有 ROI 和检测结果（调试用）。
        """
        vis = frame.copy()

        colors = {
            "rod_1_indicator": (0, 0, 255),
            "rod_2_indicator": (0, 255, 0),
            "rod_3_indicator": (255, 0, 0),
            "chat_box": (0, 255, 255),
            "tension_bar": (0, 128, 255),
            "weather_area": (255, 255, 0),
        }

        for name, roi in self.rois.items():
            x, y, w, h = roi
            color = colors.get(name, (255, 255, 255))
            cv2.rectangle(vis, (x, y), (x + w, y + h), color, 2)
            cv2.putText(vis, name, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        # 检测鱼口并标注
        for slot in (1, 2, 3):
            result = self.detect_bite(slot, frame)
            roi_name = f"rod_{slot}_indicator"
            if roi_name in self.rois:
                x, y, w, h = self.rois[roi_name]
                status_text = f"{result.value.name} ({result.confidence:.0%})"
                cv2.putText(vis, status_text, (x, y + h + 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # 检测拉力条
        tension = self.detect_tension(frame)
        if "tension_bar" in self.rois:
            x, y, w, h = self.rois["tension_bar"]
            status_text = f"Tension: {tension.value.name} ({tension.confidence:.0%})"
            cv2.putText(vis, status_text, (x, y + h + 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        if save_path:
            cv2.imwrite(save_path, vis)

        return vis
