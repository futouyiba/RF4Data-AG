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
    
    # 尝试设置常见的 Windows Tesseract 路径，防止找不到
    import os
    _tess_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(_tess_path):
        pytesseract.pytesseract.tesseract_cmd = _tess_path
        
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
        # 新格式: "Player: FishName, Weight g" (e.g. "futou: Roach, 500 g")
        re.compile(r":\s*(.+?),\s*(\d+\.?\d*)\s*(kg|g)", re.IGNORECASE),
        # 弹窗格式往往分行，或者直接是 "Roach" 下一行 "500 g"
    ]

    def extract_catch_from_popup(self, text: str) -> Optional[dict]:
        """
        从弹窗 OCR 文本中提取渔获。
        弹窗通常包含:
            Fish Name (e.g. Common Roach)
            Weight (e.g. 591 g)
            Length (e.g. 29 cm)
            [Keep] [Release]
        """
        # 1. 寻找重量 (e.g. "591 g" or "1.234 kg")
        weight_match = re.search(r"(\d+\.?\d*)\s*(kg|g)", text, re.IGNORECASE)
        if not weight_match:
            return None
        
        weight_val = float(weight_match.group(1))
        unit = weight_match.group(2).lower()
        if unit == 'g':
            weight_val /= 1000.0  # 统一转为 kg
            
        # 2. 寻找鱼名 (通常在第一行，或重量上方)
        # 简单策略：取第一行非空文本，且不是重量/长度/按钮
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        fish_name = "Unknown"
        
        for line in lines:
            # 跳过包含数字的行 (往往是重量/长度)
            if re.search(r"\d", line):
                continue
            # 跳过常见 UI 词
            if line.lower() in ["keep", "release", "space", "backspace", "valuable"]:
                continue
            # 假设第一行符合条件的就是鱼名
            fish_name = line
            break
            
        return {
            "fish_name": fish_name,
            "weight_kg": weight_val,
        }

    def extract_catch(self, text: str) -> Optional[dict]:
        """
        从 OCR 文本中提取渔获信息。

        Returns:
            {"fish_name": str, "weight_kg": float} 或 None
        """
        for pattern in self._CATCH_PATTERNS:
            match = pattern.search(text)
            if match:
                weight = float(match.group(2))
                # 如果有第三个分组且是单位 (kg/g)
                if len(match.groups()) >= 3:
                     unit = match.group(3).lower()
                     if unit == 'g':
                         weight /= 1000.0
                
                return {
                    "fish_name": match.group(1).strip(),
                    "weight_kg": weight,
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
