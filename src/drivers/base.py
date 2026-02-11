"""
InputDriver 抽象基类
===================
所有输入操作必须通过此接口。
业务逻辑中严禁直接调用 pyautogui / pynput 等底层库。

P0: SoftwareInputDriver (PyAutoGUI)
P1: HardwareInputDriver (Arduino Leonardo via Serial)
"""

from abc import ABC, abstractmethod
from typing import Tuple, Optional


class InputDriver(ABC):
    """
    输入驱动抽象基类。

    所有方法都应包含拟人化的随机延迟，由具体实现负责。
    """

    @abstractmethod
    def move_mouse(
        self,
        x: int,
        y: int,
        duration_range: Tuple[float, float] = (0.3, 0.8),
    ) -> None:
        """
        以拟人化的方式移动鼠标到 (x, y)。

        Args:
            x: 目标 X 坐标
            y: 目标 Y 坐标
            duration_range: 移动耗时范围（秒），实际值在范围内随机
        """
        ...

    @abstractmethod
    def click(
        self,
        button: str = "left",
        clicks: int = 1,
        interval_range: Tuple[float, float] = (0.05, 0.15),
    ) -> None:
        """
        模拟鼠标点击。

        Args:
            button: 'left' | 'right' | 'middle'
            clicks: 点击次数
            interval_range: 多次点击时的间隔范围
        """
        ...

    @abstractmethod
    def press(self, key: str, hold_range: Tuple[float, float] = (0.04, 0.12)) -> None:
        """
        模拟按键（按下并松开）。

        Args:
            key: 键名（如 '1', 'space', 'ctrl'）
            hold_range: 按住时长范围
        """
        ...

    @abstractmethod
    def key_down(self, key: str) -> None:
        """按住某键不放。"""
        ...

    @abstractmethod
    def key_up(self, key: str) -> None:
        """释放某键。"""
        ...

    @abstractmethod
    def drag(
        self,
        start: Tuple[int, int],
        end: Tuple[int, int],
        button: str = "left",
        duration_range: Tuple[float, float] = (0.5, 1.0),
    ) -> None:
        """
        从 start 拖拽到 end。

        Args:
            start: 起点坐标
            end: 终点坐标
            button: 拖拽使用的鼠标按键
            duration_range: 拖拽耗时范围
        """
        ...

    @abstractmethod
    def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """
        模拟滚轮。

        Args:
            clicks: 正值向上，负值向下
            x, y: 如指定，先移动到该位置再滚动
        """
        ...

    def random_delay(
        self, low: float = 0.1, high: float = 0.3
    ) -> None:
        """
        在操作之间插入随机延迟。子类可覆盖以调整策略。
        """
        import time
        import random
        time.sleep(random.uniform(low, high))
