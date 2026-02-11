"""
SoftwareInputDriver — 基于 PyAutoGUI 的软件输入实现
===================================================
P0 阶段默认驱动。包含基本的随机延迟以降低被检测风险。

安全特性:
- 所有鼠标移动附带随机时长
- 所有点击前后有随机延迟
- 按键按住时长随机化
"""

import random
import time
from typing import Tuple, Optional

import pyautogui

from .base import InputDriver

# PyAutoGUI 安全设置
pyautogui.PAUSE = 0.0  # 我们自己管理延迟
pyautogui.FAILSAFE = True  # 鼠标移到左上角时中止（安全阀）


class SoftwareInputDriver(InputDriver):
    """基于 PyAutoGUI 的输入驱动，附带随机延迟 + 贝塞尔曲线鼠标。"""

    def __init__(self, delay_multiplier: float = 1.0, use_bezier: bool = True):
        """
        Args:
            delay_multiplier: 全局延迟倍率。1.0 = 正常, 0.5 = 快速, 2.0 = 更慢更安全
            use_bezier: 是否使用贝塞尔曲线鼠标移动（True=拟人化, False=P0 直线）
        """
        self._delay_mul = delay_multiplier
        self._use_bezier = use_bezier

    def _scaled_range(self, r: Tuple[float, float]) -> Tuple[float, float]:
        return (r[0] * self._delay_mul, r[1] * self._delay_mul)

    # ── 鼠标 ───────────────────────────────────────────────

    def move_mouse(
        self,
        x: int,
        y: int,
        duration_range: Tuple[float, float] = (0.3, 0.8),
    ) -> None:
        lo, hi = self._scaled_range(duration_range)
        duration = random.uniform(lo, hi)

        if self._use_bezier:
            from .bezier import generate_path, move_along_path
            current = pyautogui.position()
            path = generate_path(
                start=(current.x, current.y),
                end=(x, y),
                curvature=random.uniform(0.3, 0.7),
            )
            move_along_path(path, lambda px, py: pyautogui.moveTo(px, py), duration)
        else:
            pyautogui.moveTo(x, y, duration=duration, tween=pyautogui.easeOutQuad)

    def click(
        self,
        button: str = "left",
        clicks: int = 1,
        interval_range: Tuple[float, float] = (0.05, 0.15),
    ) -> None:
        lo, hi = self._scaled_range(interval_range)
        interval = random.uniform(lo, hi) if clicks > 1 else 0
        self.random_delay(0.02, 0.08)  # 点击前微延迟
        pyautogui.click(button=button, clicks=clicks, interval=interval)
        self.random_delay(0.02, 0.08)  # 点击后微延迟

    def press(self, key: str, hold_range: Tuple[float, float] = (0.04, 0.12)) -> None:
        lo, hi = self._scaled_range(hold_range)
        self.random_delay(0.02, 0.06)
        pyautogui.keyDown(key)
        time.sleep(random.uniform(lo, hi))
        pyautogui.keyUp(key)

    def key_down(self, key: str) -> None:
        self.random_delay(0.01, 0.05)
        pyautogui.keyDown(key)

    def key_up(self, key: str) -> None:
        self.random_delay(0.01, 0.05)
        pyautogui.keyUp(key)

    def drag(
        self,
        start: Tuple[int, int],
        end: Tuple[int, int],
        button: str = "left",
        duration_range: Tuple[float, float] = (0.5, 1.0),
    ) -> None:
        lo, hi = self._scaled_range(duration_range)
        self.move_mouse(start[0], start[1])
        self.random_delay(0.05, 0.15)
        duration = random.uniform(lo, hi)
        pyautogui.drag(
            end[0] - start[0],
            end[1] - start[1],
            duration=duration,
            button=button,
            tween=pyautogui.easeInOutQuad,
        )

    def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        if x is not None and y is not None:
            self.move_mouse(x, y)
            self.random_delay(0.05, 0.15)
        pyautogui.scroll(clicks)
        self.random_delay(0.05, 0.1)
