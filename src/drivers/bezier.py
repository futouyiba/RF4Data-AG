"""
贝塞尔曲线鼠标移动
=================
生成拟人化的鼠标运动轨迹，避免被反作弊检测。

原理:
- 用 3 阶贝塞尔曲线（2 个随机控制点）模拟人手的弧线移动
- 速度沿曲线非匀速分布（先加速再减速，模拟人手惯性）
- 末端添加微抖动（模拟手持鼠标的不稳定）

参考: https://en.wikipedia.org/wiki/B%C3%A9zier_curve
"""

import math
import random
import time
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

Point = Tuple[float, float]


def _lerp(a: float, b: float, t: float) -> float:
    """线性插值。"""
    return a + (b - a) * t


def cubic_bezier_point(
    p0: Point, p1: Point, p2: Point, p3: Point, t: float
) -> Point:
    """
    计算三阶贝塞尔曲线上 t 处的点。

    B(t) = (1-t)³·P0 + 3(1-t)²t·P1 + 3(1-t)t²·P2 + t³·P3
    """
    u = 1.0 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t

    x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]
    return (x, y)


def generate_control_points(
    start: Point,
    end: Point,
    curvature: float = 0.6,
) -> Tuple[Point, Point]:
    """
    为贝塞尔曲线生成两个随机控制点。

    curvature 控制曲线弯曲程度 (0 = 直线, 1 = 大弧线)。
    控制点偏移方向随机（上下左右），偏移量与起止距离成正比。
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dist = math.sqrt(dx * dx + dy * dy) or 1.0

    # 垂直于起止连线的方向
    perp_x = -dy / dist
    perp_y = dx / dist

    # 控制点 1: 在 1/3 处 + 随机偏移
    offset1 = dist * curvature * random.uniform(-0.5, 0.5)
    cp1 = (
        _lerp(start[0], end[0], 0.3) + perp_x * offset1 + random.uniform(-5, 5),
        _lerp(start[1], end[1], 0.3) + perp_y * offset1 + random.uniform(-5, 5),
    )

    # 控制点 2: 在 2/3 处 + 随机偏移（独立随机）
    offset2 = dist * curvature * random.uniform(-0.3, 0.3)
    cp2 = (
        _lerp(start[0], end[0], 0.7) + perp_x * offset2 + random.uniform(-3, 3),
        _lerp(start[1], end[1], 0.7) + perp_y * offset2 + random.uniform(-3, 3),
    )

    return cp1, cp2


def ease_out_quad(t: float) -> float:
    """缓出二次: 先快后慢。"""
    return 1 - (1 - t) * (1 - t)


def ease_in_out_sine(t: float) -> float:
    """正弦缓入缓出: 更平滑的加减速。"""
    return -(math.cos(math.pi * t) - 1) / 2


def generate_path(
    start: Point,
    end: Point,
    num_points: int = 0,
    curvature: float = 0.6,
    easing: str = "ease_out_quad",
) -> List[Point]:
    """
    生成贝塞尔曲线运动路径上的点序列。

    Args:
        start: 起始坐标 (x, y)
        end: 目标坐标 (x, y)
        num_points: 路径点数（0=自动根据距离决定）
        curvature: 曲线弯曲程度 (0-1)
        easing: 缓动函数 ("ease_out_quad" | "ease_in_out_sine" | "linear")

    Returns:
        [(x, y), ...] 路径点列表（包含 start 和 end）
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dist = math.sqrt(dx * dx + dy * dy)

    if dist < 2:
        return [start, end]

    if num_points <= 0:
        # 根据距离自动计算: 每 3-5 个像素一个采样点
        num_points = max(15, min(100, int(dist / random.uniform(3, 5))))

    cp1, cp2 = generate_control_points(start, end, curvature)

    # 选择缓动函数
    ease_fn = {
        "ease_out_quad": ease_out_quad,
        "ease_in_out_sine": ease_in_out_sine,
        "linear": lambda t: t,
    }.get(easing, ease_out_quad)

    path = []
    for i in range(num_points + 1):
        t_linear = i / num_points
        t_eased = ease_fn(t_linear)
        point = cubic_bezier_point(start, cp1, cp2, end, t_eased)
        path.append((round(point[0]), round(point[1])))

    # 去重相邻点
    deduped = [path[0]]
    for p in path[1:]:
        if p != deduped[-1]:
            deduped.append(p)

    # 末端微抖动（模拟手指不稳定）
    if len(deduped) > 3:
        last_x, last_y = deduped[-1]
        jitter = random.uniform(0.5, 2.0)
        deduped[-1] = (
            last_x + random.randint(-1, 1),
            last_y + random.randint(-1, 1),
        )
        deduped.append(end)  # 确保最终到达目标

    return deduped


def move_along_path(
    path: List[Point],
    move_fn,
    total_duration_s: float = 0.5,
) -> None:
    """
    沿路径逐点移动鼠标。

    Args:
        path: generate_path 返回的点序列
        move_fn: 底层移动函数 (x, y) -> None（如 pyautogui.moveTo）
        total_duration_s: 总移动时间
    """
    if len(path) < 2:
        if path:
            move_fn(path[0][0], path[0][1])
        return

    step_delay = total_duration_s / (len(path) - 1)
    for x, y in path:
        move_fn(x, y)
        # 随机化步间延迟 (±30%)
        actual_delay = step_delay * random.uniform(0.7, 1.3)
        time.sleep(max(0.001, actual_delay))
