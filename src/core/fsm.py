"""
三杆有限状态机 (FSM) 引擎
=========================
每根杆是一个独立的 RodFSM 实例，拥有完整的状态流转:

    IDLE → CASTING → WAITING → HOOKING → RETRIEVING → LOGGING → IDLE
                      ↓ (timeout)
                    IDLE (重置换饵)
                                          ↓ (loss/break)
                                        IDLE

FishingOrchestrator 协调三根杆的并行运行。
"""

import time
import logging
from enum import Enum, auto
from typing import Optional, Dict, Callable
from datetime import datetime

from src.core.vision import VisionSensor, BiteStatus, TensionZone, DetectionResult
from src.drivers.base import InputDriver
from src.data.db import Database
from src.data.models import Event, Catch
from src.utils.screenshot import ScreenCapture

logger = logging.getLogger(__name__)


class RodState(Enum):
    """杆状态。"""
    IDLE = auto()
    CASTING = auto()
    WAITING = auto()
    HOOKING = auto()
    RETRIEVING = auto()
    LOGGING = auto()


class RodFSM:
    """
    单根杆的有限状态机。

    每次调用 update() 时，根据当前状态执行对应行为，
    并根据 vision 检测结果进行状态转移。
    """

    def __init__(
        self,
        rod_slot: int,
        session_id: int,
        driver: InputDriver,
        vision: VisionSensor,
        capture: ScreenCapture,
        db: Database,
        wait_timeout_s: float = 1200,
        retrieve_timeout_s: float = 180,
    ):
        self.rod_slot = rod_slot
        self.session_id = session_id
        self.driver = driver
        self.vision = vision
        self.capture = capture
        self.db = db

        self.state = RodState.IDLE
        self.wait_timeout_s = wait_timeout_s
        self.retrieve_timeout_s = retrieve_timeout_s

        # 时间追踪
        self._state_enter_time: float = time.time()
        self._last_bite_time: Optional[float] = None
        self._cast_count: int = 0
        self._retrieve_start: Optional[float] = None

        # 键位映射: 杆号 → 数字键
        self._slot_key = str(rod_slot)

    @property
    def time_in_state(self) -> float:
        """在当前状态中已停留的秒数。"""
        return time.time() - self._state_enter_time

    def _transition(self, new_state: RodState, reason: str = "") -> None:
        """状态转移。"""
        old_state = self.state
        self.state = new_state
        self._state_enter_time = time.time()
        logger.info(
            "Rod%d: %s → %s%s",
            self.rod_slot, old_state.name, new_state.name,
            f" ({reason})" if reason else "",
        )
        # 记录事件
        self.db.log_event(Event(
            session_id=self.session_id,
            rod_slot=self.rod_slot,
            event_type=f"STATE_{new_state.name}",
            value_json=f'{{"from": "{old_state.name}", "reason": "{reason}"}}',
            ts=datetime.now(),
        ))

    def update(self, frame=None) -> None:
        """
        状态机主循环 tick。

        Args:
            frame: 当前全屏帧（可选，None 则实时截图）
        """
        if frame is None:
            frame = self.capture.capture_full_screen()

        handler = {
            RodState.IDLE: self._handle_idle,
            RodState.CASTING: self._handle_casting,
            RodState.WAITING: self._handle_waiting,
            RodState.HOOKING: self._handle_hooking,
            RodState.RETRIEVING: self._handle_retrieving,
            RodState.LOGGING: self._handle_logging,
        }.get(self.state)

        if handler:
            handler(frame)

    # ── 各状态处理器 ─────────────────────────────────────

    def _handle_idle(self, frame) -> None:
        """IDLE: 切杆 → 挂饵(假设已挂好) → 抛竿。"""
        logger.debug("Rod%d: IDLE — 准备抛竿", self.rod_slot)

        # 按数字键切换到本杆
        self.driver.press(self._slot_key)
        self.driver.random_delay(0.3, 0.6)

        self._transition(RodState.CASTING, "开始抛竿")

    def _handle_casting(self, frame) -> None:
        """CASTING: 长按左键抛竿 → 放竿。"""
        # 长按左键抛竿（模拟蓄力）
        self.driver.key_down("left")  # 鼠标左键按住 — 实际应通过 click 的 hold 模式
        self.driver.random_delay(1.5, 2.5)  # 蓄力时间
        self.driver.key_up("left")
        self.driver.random_delay(2.0, 3.0)  # 等待落水

        # 按 0 放下杆子（底钓特有）
        self.driver.press("0")
        self.driver.random_delay(0.5, 1.0)

        self._cast_count += 1
        self.db.log_event(Event(
            session_id=self.session_id,
            rod_slot=self.rod_slot,
            event_type="CAST",
            value_json=f'{{"cast_count": {self._cast_count}}}',
            ts=datetime.now(),
        ))

        self._transition(RodState.WAITING, f"第 {self._cast_count} 次抛竿")

    def _handle_waiting(self, frame) -> None:
        """WAITING: 持续监测鱼口 → BITE 则转 HOOKING, 超时则重置。"""
        bite = self.vision.detect_bite(self.rod_slot, frame)

        if bite.value == BiteStatus.BITE:
            self._last_bite_time = time.time()

            # 保存 evidence
            evidence_path = self.capture.save_evidence(
                frame, prefix=f"bite_rod{self.rod_slot}",
                session_id=self.session_id,
            )
            self.db.log_event(Event(
                session_id=self.session_id,
                rod_slot=self.rod_slot,
                event_type="BITE",
                confidence=bite.confidence,
                evidence_path=evidence_path,
                ts=datetime.now(),
            ))
            self._transition(RodState.HOOKING, f"检测到鱼口 (conf={bite.confidence:.0%})")

        elif self.time_in_state > self.wait_timeout_s:
            # 超时 → 重置
            logger.warning("Rod%d: 等待超时 (%.0fs)，准备重置",
                           self.rod_slot, self.time_in_state)
            self.db.log_event(Event(
                session_id=self.session_id,
                rod_slot=self.rod_slot,
                event_type="TIMEOUT",
                value_json=f'{{"wait_time_s": {self.time_in_state:.0f}}}',
                ts=datetime.now(),
            ))
            self._transition(RodState.IDLE, "等待超时")

    def _handle_hooking(self, frame) -> None:
        """HOOKING: 刺鱼（提竿） → RETRIEVING。"""
        # 切换到本杆
        self.driver.press(self._slot_key)
        self.driver.random_delay(0.2, 0.5)

        # 刺鱼动作 — 快速向上移动鼠标 + 点击
        # 不同钩法可能不同，P0 用最简单的方式
        self.driver.random_delay(0.1, 0.3)  # 模拟人类反应时间
        self.driver.click("left")
        self.driver.random_delay(0.3, 0.6)

        self._retrieve_start = time.time()
        self._transition(RodState.RETRIEVING, "已提竿")

    def _handle_retrieving(self, frame) -> None:
        """RETRIEVING: 收线 + 拉力管理 → 检测渔获或超时/断线。"""
        # 检测拉力条
        tension = self.vision.detect_tension(frame)

        if tension.value == TensionZone.DANGER:
            # 危险！松收线
            self.driver.key_up("left")  # 确保松开
            self.driver.random_delay(0.5, 1.0)
            logger.debug("Rod%d: 拉力危险，放线", self.rod_slot)

        elif tension.value == TensionZone.GONE:
            # 拉力条消失 — 可能起鱼、跑鱼或空钩
            # 转入 LOGGING 状态统一等待结果（弹窗/聊天/超时）
            self.driver.key_up("left")
            self._transition(RodState.LOGGING, "拉力消失，进入结算")
            return

        else:
            # 安全/警告区 — 继续收线
            self.driver.key_down("left")
            self.driver.random_delay(0.1, 0.3)

        # 收线超时检查
        if self._retrieve_start and (time.time() - self._retrieve_start) > self.retrieve_timeout_s:
            logger.warning("Rod%d: 收线超时，可能挂底", self.rod_slot)
            self.db.log_event(Event(
                session_id=self.session_id,
                rod_slot=self.rod_slot,
                event_type="RETRIEVE_TIMEOUT",
                ts=datetime.now(),
            ))
            self.driver.key_up("left")
            self._transition(RodState.IDLE, "收线超时")

        # 注意：不再在 RETRIEVING 这里检测聊天框，统一放到 LOGGING里

    def _handle_logging(self, frame) -> None:
        """
        LOGGING: 结算阶段。
        等待起鱼弹窗 或 聊天框信息。
        如果超时无结果，则视为空杆或未知跑鱼。
        """
        # 1. 优先尝试检测弹窗 (更准确)
        popup = self.vision.detect_catch_popup(frame)
        if popup.value:
            self._log_catch_and_finish(frame, popup.value, popup.confidence, "POPUP")
            # 弹窗需要按空格确认收鱼
            logger.info("Rod%d: 检测到起鱼弹窗，按空格收鱼", self.rod_slot)
            self.driver.random_delay(0.5, 1.0)
            self.driver.press("space")
            self.driver.random_delay(0.5, 1.0)
            return

        # 2. 其次尝试检测聊天框 (Backup)
        # 只有在弹窗没出现时才依赖这个（比如弹窗被禁用了？）
        chat = self.vision.detect_catch_from_chat(frame)
        if chat.value:
            self._log_catch_and_finish(frame, chat.value, chat.confidence, "CHAT")
            return

        # 3. 超时检查
        # 进入 LOGGING 状态如果在 8 秒内还没识别到，就认为是空杆/跑鱼
        if self.time_in_state > 8.0:
            logger.info("Rod%d: 结算超时(8s)，未检测到渔获", self.rod_slot)
            # 记录一个空retrieve或者loss? 
            # 如果之前的 retrieve 时间很短 (<5s)，可能是才刚抛下去就提杆了 -> 视为 IDLE reset
            # 如果 retrieve 时间长，可能是跑鱼了但没检测到 LOSS 信号
            
            # 这里简单处理：视为完成，不记录 Catch
            self._pending_catch = None
            self._retrieve_start = None
            self._transition(RodState.IDLE, "结算结束(无渔获)")

    def _log_catch_and_finish(self, frame, fish_info: dict, conf: float, source: str):
        """记录渔获并结束 LOGGING 状态。"""
        evidence_path = self.capture.save_evidence(
            frame, prefix=f"catch_rod{self.rod_slot}_{source}",
            session_id=self.session_id,
        )

        fight_time = (time.time() - self._retrieve_start) if self._retrieve_start else 0
        weight_g = fish_info.get("weight_kg", 0) * 1000

        catch = Catch(
            session_id=self.session_id,
            rod_slot=self.rod_slot,
            fish_name_raw=fish_info.get("fish_name", "Unknown"),
            weight_g=weight_g,
            outcome="CATCH",
            fight_time_s=round(fight_time, 1),
            evidence_path=evidence_path,
            confidence=conf,
            ts_land=datetime.now(),
        )
        catch_id = self.db.save_catch(catch)
        
        logger.info(
            "Rod%d: 🐟 [%s] %s %.2fkg (conf=%.0f%%) → #%d",
            self.rod_slot, source, catch.fish_name_raw,
            catch.weight_g / 1000, catch.confidence * 100, catch_id,
        )

        self._pending_catch = None
        self._retrieve_start = None
        self._transition(RodState.IDLE, "记录完成")


class FishingOrchestrator:
    """
    钓鱼协调器 — 管理三根杆的并行运行。

    主循环中轮询三根杆的 FSM，每帧只截图一次，
    同一帧分发给所有需要视觉检测的杆。
    """

    def __init__(
        self,
        session_id: int,
        driver: InputDriver,
        vision: VisionSensor,
        capture: ScreenCapture,
        db: Database,
        wait_timeout_s: float = 1200,
        retrieve_timeout_s: float = 180,
        tick_interval_s: float = 0.5,
        rod_count: int = 3,
    ):
        self.session_id = session_id
        self.capture = capture
        self.tick_interval = tick_interval_s
        self.running = False

        # 创建 FSM 实例
        self.rods: Dict[int, RodFSM] = {}
        for slot in range(1, rod_count + 1):
            self.rods[slot] = RodFSM(
                rod_slot=slot,
                session_id=session_id,
                driver=driver,
                vision=vision,
                capture=capture,
                db=db,
                wait_timeout_s=wait_timeout_s,
                retrieve_timeout_s=retrieve_timeout_s,
            )

        # 回调
        self._on_tick: Optional[Callable] = None
        self._tick_count = 0

    def set_on_tick(self, callback: Callable) -> None:
        """设置每 tick 回调（用于环境快照等）。"""
        self._on_tick = callback

    def start(self) -> None:
        """启动主循环。"""
        self.running = True
        logger.info("钓鱼协调器启动 — %d 根杆", len(self.rods))

        while self.running:
            try:
                self._tick()
                time.sleep(self.tick_interval)
            except KeyboardInterrupt:
                self.stop()
                break
            except Exception as e:
                logger.error("主循环异常: %s", e, exc_info=True)
                time.sleep(1)  # 防止死循环打爆日志

    def stop(self) -> None:
        """停止主循环。"""
        self.running = False
        # 释放所有按住的键
        logger.info("钓鱼协调器停止")

    def _tick(self) -> None:
        """一次 tick：截图 → 更新所有活跃的杆。"""
        self._tick_count += 1
        frame = self.capture.capture_full_screen()

        # 找出当前需要操作的杆
        # 优先处理正在 HOOKING/RETRIEVING 的杆（时间敏感）
        priority_order = sorted(
            self.rods.values(),
            key=lambda r: {
                RodState.HOOKING: 0,
                RodState.RETRIEVING: 1,
                RodState.LOGGING: 2,
                RodState.CASTING: 3,
                RodState.WAITING: 4,
                RodState.IDLE: 5,
            }.get(r.state, 9),
        )

        for rod in priority_order:
            rod.update(frame)

        # tick 回调
        if self._on_tick:
            self._on_tick(self._tick_count, frame)

    def get_status(self) -> Dict[int, str]:
        """获取所有杆的当前状态。"""
        return {slot: rod.state.name for slot, rod in self.rods.items()}
