"""
截图工具
=======
负责游戏窗口截图、ROI 区域截图、evidence 保存。
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# 尝试导入 mss（比 PIL 截图更快）
try:
    import mss
    _HAS_MSS = True
except ImportError:
    _HAS_MSS = False
    logger.warning("mss 未安装，截图性能可能较差。建议: pip install mss")


class ScreenCapture:
    """屏幕截图管理器。"""

    def __init__(self, evidence_dir: str | Path = "data/evidence"):
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._sct = mss.mss() if _HAS_MSS else None

    def capture_full_screen(self) -> np.ndarray:
        """
        截取整个主屏幕。

        Returns:
            BGR 格式的 numpy 数组（OpenCV 标准）
        """
        if self._sct:
            monitor = self._sct.monitors[1]  # 主显示器
            raw = self._sct.grab(monitor)
            img = np.array(raw)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        else:
            # 后备方案: PIL
            from PIL import ImageGrab
            screenshot = ImageGrab.grab()
            return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    def capture_region(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        full_frame: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        截取屏幕某区域。

        Args:
            x, y, w, h: ROI 区域坐标
            full_frame: 如果已有全屏截图，直接裁切（避免重复截图）

        Returns:
            BGR 格式的 numpy 数组
        """
        if full_frame is not None:
            return full_frame[y : y + h, x : x + w].copy()

        if self._sct:
            monitor = {"left": x, "top": y, "width": w, "height": h}
            raw = self._sct.grab(monitor)
            img = np.array(raw)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        else:
            from PIL import ImageGrab
            screenshot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    def capture_roi(
        self,
        roi: Tuple[int, int, int, int],
        full_frame: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        截取 ROI 区域（元组格式）。

        Args:
            roi: (x, y, w, h)
            full_frame: 可选全屏帧
        """
        return self.capture_region(*roi, full_frame=full_frame)

    def save_evidence(
        self,
        image: np.ndarray,
        prefix: str = "evidence",
        session_id: Optional[int] = None,
    ) -> str:
        """
        保存 evidence 截图。

        Args:
            image: 要保存的图像
            prefix: 文件名前缀
            session_id: 可选 Session ID，用于子目录分类

        Returns:
            保存的文件路径（相对路径）
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

        if session_id:
            save_dir = self.evidence_dir / f"session_{session_id}"
            save_dir.mkdir(exist_ok=True)
        else:
            save_dir = self.evidence_dir

        filename = f"{prefix}_{ts}.png"
        filepath = save_dir / filename
        cv2.imwrite(str(filepath), image)
        logger.debug("Evidence 已保存: %s", filepath)
        return str(filepath)

    def close(self) -> None:
        """释放资源。"""
        if self._sct:
            self._sct.close()
