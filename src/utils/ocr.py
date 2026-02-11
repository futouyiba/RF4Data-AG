"""
OCR 工具
=======
封装 Tesseract OCR，提供预处理 + 识别 + 正则提取。
"""

import re
import logging
from typing import Optional, Tuple, List

import cv2
import numpy as np

logger = logging.getLogger(__name__)

try:
    import pytesseract
    _HAS_TESSERACT = True
except ImportError:
    _HAS_TESSERACT = False
    logger.warning("pytesseract 未安装。建议: pip install pytesseract")


class OCREngine:
    """Tesseract OCR 引擎封装。"""

    def __init__(self, lang: str = "eng+chi_sim", confidence_threshold: float = 0.6):
        """
        Args:
            lang: Tesseract 语言包
            confidence_threshold: 置信度阈值，低于此值的识别结果会被标记
        """
        self.lang = lang
        self.confidence_threshold = confidence_threshold
        if not _HAS_TESSERACT:
            raise RuntimeError("pytesseract 未安装")

    # ── 图像预处理 ───────────────────────────────────────

    @staticmethod
    def preprocess_for_ocr(image: np.ndarray, mode: str = "default") -> np.ndarray:
        """
        针对 OCR 的图像预处理。

        Args:
            image: BGR 输入图像
            mode:
                "default" - 灰度 + 自适应二值化
                "dark_bg" - 针对深色背景的白色文字（聊天框场景）
                "light_bg" - 针对浅色背景（弹窗场景）
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        if mode == "dark_bg":
            # 深色背景白字：反色后二值化
            inverted = cv2.bitwise_not(gray)
            _, binary = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return binary
        elif mode == "light_bg":
            # 浅色背景黑字：直接二值化
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return binary
        else:
            # 默认：自适应阈值
            return cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2,
            )

    # ── OCR 识别 ─────────────────────────────────────────

    def recognize(
        self,
        image: np.ndarray,
        preprocess_mode: str = "default",
        config: str = "--psm 6",
    ) -> Tuple[str, float]:
        """
        对图像进行 OCR 识别。

        Args:
            image: BGR 输入图像
            preprocess_mode: 预处理模式
            config: Tesseract 配置（PSM 模式等）

        Returns:
            (识别文本, 平均置信度 0-1)
        """
        processed = self.preprocess_for_ocr(image, preprocess_mode)

        # 获取详细数据（含置信度）
        data = pytesseract.image_to_data(
            processed, lang=self.lang, config=config,
            output_type=pytesseract.Output.DICT,
        )

        texts = []
        confidences = []
        for i, text in enumerate(data["text"]):
            conf = int(data["conf"][i])
            if conf > 0 and text.strip():
                texts.append(text.strip())
                confidences.append(conf / 100.0)

        full_text = " ".join(texts)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return full_text, avg_conf

    # ── 渔获提取 ─────────────────────────────────────────

    # 匹配模式示例:
    # "捕获了 Common Bream 1.45 kg"
    # "Caught Common Bream 1.45 kg"
    _CATCH_PATTERNS = [
        re.compile(r"捕获了?\s*(.+?)\s+(\d+\.?\d*)\s*kg", re.IGNORECASE),
        re.compile(r"Caught\s+(.+?)\s+(\d+\.?\d*)\s*kg", re.IGNORECASE),
    ]

    def extract_catch(self, text: str) -> Optional[dict]:
        """
        从 OCR 文本中提取渔获信息。

        Returns:
            {"fish_name": str, "weight_kg": float} 或 None
        """
        for pattern in self._CATCH_PATTERNS:
            match = pattern.search(text)
            if match:
                return {
                    "fish_name": match.group(1).strip(),
                    "weight_kg": float(match.group(2)),
                }
        return None

    def extract_catches_from_lines(self, text: str) -> List[dict]:
        """从多行文本中提取所有渔获（去重）。"""
        results = []
        seen = set()
        for line in text.split("\n"):
            catch = self.extract_catch(line)
            if catch:
                key = (catch["fish_name"], catch["weight_kg"])
                if key not in seen:
                    seen.add(key)
                    results.append(catch)
        return results
