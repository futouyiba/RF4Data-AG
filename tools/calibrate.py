"""
ROI 校准工具 (GUI)
==================
启动一个交互式窗口，允许用户框选游戏 UI 的关键区域。
校准结果保存到 config/roi_config.json。

用法:
    python tools/calibrate.py
    python tools/calibrate.py --from-screenshot path/to/screenshot.png
"""

import sys
import json
import tkinter as tk
from tkinter import messagebox, filedialog
from pathlib import Path
from typing import Dict, Tuple, Optional

import cv2
import numpy as np

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.screenshot import ScreenCapture

# ── 需要校准的 ROI 区域 ─────────────────────────────────

ROI_DEFINITIONS = [
    {
        "name": "rod_1_indicator",
        "label": "1号杆图标 (左下角第1个鱼竿图标)",
        "color": "#FF4444",
    },
    {
        "name": "rod_2_indicator",
        "label": "2号杆图标 (左下角第2个鱼竿图标)",
        "color": "#44FF44",
    },
    {
        "name": "rod_3_indicator",
        "label": "3号杆图标 (左下角第3个鱼竿图标)",
        "color": "#4444FF",
    },
    {
        "name": "chat_box",
        "label": "聊天框区域 (左下角文字区域)",
        "color": "#FFFF00",
    },
    {
        "name": "tension_bar",
        "label": "拉力条 (右侧竖条)",
        "color": "#FF8800",
    },
    {
        "name": "weather_area",
        "label": "天气面板 (按M键后左上角信息区)",
        "color": "#00FFFF",
    },
    {
        "name": "catch_popup",
        "label": "起鱼弹窗 (屏幕中央鱼获信息)",
        "color": "#FF00FF",
    },
]


class ROICalibrator:
    """
    ROI 校准器 — 基于 tkinter 的交互式 GUI。

    用户在截图上拖拽矩形来标注各个 ROI 区域。
    """

    def __init__(self, screenshot: np.ndarray):
        self.original_image = screenshot
        self.display_scale = 1.0
        self.rois: Dict[str, Dict[str, int]] = {}

        # 当前正在标注的 ROI
        self._current_idx = 0
        self._drawing = False
        self._start_x = 0
        self._start_y = 0
        self._rect_id = None

        # ── 准备显示图像 ──────────────────────────────
        h, w = screenshot.shape[:2]
        # 限制显示尺寸，太大的图缩放
        max_w, max_h = 1280, 720
        if w > max_w or h > max_h:
            self.display_scale = min(max_w / w, max_h / h)
        disp_w = int(w * self.display_scale)
        disp_h = int(h * self.display_scale)
        self.display_image = cv2.resize(screenshot, (disp_w, disp_h))

        # BGR → RGB for tkinter
        rgb = cv2.cvtColor(self.display_image, cv2.COLOR_BGR2RGB)

        # ── 创建窗口 ─────────────────────────────────
        self.root = tk.Tk()
        self.root.title("RF4-BRP ROI 校准工具")
        self.root.resizable(False, False)

        # 顶部提示
        self.label_var = tk.StringVar()
        self.label = tk.Label(
            self.root, textvariable=self.label_var,
            font=("Microsoft YaHei", 14, "bold"),
            bg="#222", fg="#FFF", padx=10, pady=8,
        )
        self.label.pack(fill=tk.X)
        self._update_label()

        # 画布
        from PIL import Image, ImageTk
        self._pil_image = Image.fromarray(rgb)
        self._tk_image = ImageTk.PhotoImage(self._pil_image)

        self.canvas = tk.Canvas(
            self.root, width=disp_w, height=disp_h,
            cursor="crosshair",
        )
        self.canvas.pack()
        self._bg_id = self.canvas.create_image(0, 0, anchor=tk.NW, image=self._tk_image)

        # 绘制已有的矩形标注
        self._drawn_rects = []

        # 底部按钮
        btn_frame = tk.Frame(self.root, bg="#333", padx=5, pady=5)
        btn_frame.pack(fill=tk.X)

        self.btn_skip = tk.Button(
            btn_frame, text="跳过此区域", command=self._skip_roi,
            font=("Microsoft YaHei", 10),
        )
        self.btn_skip.pack(side=tk.LEFT, padx=5)

        self.btn_undo = tk.Button(
            btn_frame, text="撤销上一个", command=self._undo_roi,
            font=("Microsoft YaHei", 10),
        )
        self.btn_undo.pack(side=tk.LEFT, padx=5)

        self.btn_save = tk.Button(
            btn_frame, text="保存并退出", command=self._save_and_exit,
            font=("Microsoft YaHei", 10), bg="#4CAF50", fg="white",
            state=tk.DISABLED,
        )
        self.btn_save.pack(side=tk.RIGHT, padx=5)

        # 状态标签
        self.status_var = tk.StringVar(value="在截图上拖拽矩形来标注区域")
        tk.Label(
            btn_frame, textvariable=self.status_var,
            font=("Microsoft YaHei", 9), bg="#333", fg="#AAA",
        ).pack(side=tk.RIGHT, padx=20)

        # ── 绑定事件 ─────────────────────────────────
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

    def _update_label(self):
        if self._current_idx < len(ROI_DEFINITIONS):
            roi_def = ROI_DEFINITIONS[self._current_idx]
            self.label_var.set(
                f"[{self._current_idx + 1}/{len(ROI_DEFINITIONS)}] "
                f"请框选: {roi_def['label']}"
            )
        else:
            self.label_var.set("✅ 所有区域已标注完成！点击「保存并退出」")

    def _on_press(self, event):
        if self._current_idx >= len(ROI_DEFINITIONS):
            return
        self._drawing = True
        self._start_x = event.x
        self._start_y = event.y
        color = ROI_DEFINITIONS[self._current_idx]["color"]
        self._rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline=color, width=2, dash=(4, 4),
        )

    def _on_drag(self, event):
        if not self._drawing or self._rect_id is None:
            return
        self.canvas.coords(
            self._rect_id,
            self._start_x, self._start_y, event.x, event.y,
        )

    def _on_release(self, event):
        if not self._drawing:
            return
        self._drawing = False

        # 计算实际坐标（还原缩放）
        x1 = min(self._start_x, event.x)
        y1 = min(self._start_y, event.y)
        x2 = max(self._start_x, event.x)
        y2 = max(self._start_y, event.y)

        # 最小尺寸检查
        if (x2 - x1) < 5 or (y2 - y1) < 5:
            if self._rect_id:
                self.canvas.delete(self._rect_id)
                self._rect_id = None
            return

        # 还原到原图坐标
        scale = 1.0 / self.display_scale
        roi_def = ROI_DEFINITIONS[self._current_idx]
        self.rois[roi_def["name"]] = {
            "x": int(x1 * scale),
            "y": int(y1 * scale),
            "w": int((x2 - x1) * scale),
            "h": int((y2 - y1) * scale),
        }

        # 固化矩形显示
        color = roi_def["color"]
        if self._rect_id:
            self.canvas.itemconfig(self._rect_id, dash=(), width=2)
            # 添加标签
            self.canvas.create_text(
                x1 + 3, y1 - 3,
                text=roi_def["name"], anchor=tk.SW,
                fill=color, font=("Consolas", 9, "bold"),
            )
        self._drawn_rects.append(self._rect_id)
        self._rect_id = None

        self.status_var.set(f"已标注: {roi_def['name']} → {self.rois[roi_def['name']]}")

        # 下一个
        self._current_idx += 1
        self._update_label()
        self._check_completion()

    def _skip_roi(self):
        if self._current_idx >= len(ROI_DEFINITIONS):
            return
        roi_def = ROI_DEFINITIONS[self._current_idx]
        self.status_var.set(f"已跳过: {roi_def['name']}")
        self._current_idx += 1
        self._update_label()
        self._check_completion()

    def _undo_roi(self):
        if self._current_idx <= 0:
            return
        self._current_idx -= 1
        roi_def = ROI_DEFINITIONS[self._current_idx]
        # 删除画布上的矩形
        if self._drawn_rects:
            rect_id = self._drawn_rects.pop()
            if rect_id:
                self.canvas.delete(rect_id)
        # 删除数据
        self.rois.pop(roi_def["name"], None)
        self._update_label()
        self.status_var.set(f"已撤销: {roi_def['name']}")
        self.btn_save.config(state=tk.DISABLED)

    def _check_completion(self):
        # 至少标注了 4 个必需区域
        required = {"rod_1_indicator", "rod_2_indicator", "rod_3_indicator", "chat_box"}
        if required.issubset(self.rois.keys()):
            self.btn_save.config(state=tk.NORMAL)
        if self._current_idx >= len(ROI_DEFINITIONS):
            self.btn_save.config(state=tk.NORMAL)

    def _save_and_exit(self):
        if not self.rois:
            messagebox.showwarning("警告", "尚未标注任何区域！")
            return
        self._saved = True
        self.root.destroy()

    def run(self) -> Optional[Dict[str, Dict[str, int]]]:
        """运行校准 GUI，返回 ROI 字典或 None（取消）。"""
        self._saved = False
        self.root.mainloop()
        return self.rois if self._saved else None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="RF4-BRP ROI 校准工具")
    parser.add_argument(
        "--from-screenshot", type=str, default=None,
        help="从截图文件加载（不截屏）",
    )
    parser.add_argument(
        "--config-dir", type=str, default="config",
        help="配置输出目录 (默认: config/)",
    )
    args = parser.parse_args()

    # 获取图像
    if args.from_screenshot:
        img_path = Path(args.from_screenshot)
        if not img_path.exists():
            print(f"错误: 文件不存在: {img_path}")
            sys.exit(1)
        screenshot = cv2.imread(str(img_path))
        if screenshot is None:
            print(f"错误: 无法读取图像: {img_path}")
            sys.exit(1)
        print(f"从文件加载截图: {img_path} ({screenshot.shape[1]}x{screenshot.shape[0]})")
    else:
        print("正在截取当前屏幕...")
        print("请确保游戏窗口可见！(3秒后截图)")
        import time
        time.sleep(3)
        cap = ScreenCapture()
        screenshot = cap.capture_full_screen()
        cap.close()
        print(f"截图完成: {screenshot.shape[1]}x{screenshot.shape[0]}")

    # 运行校准
    calibrator = ROICalibrator(screenshot)
    result = calibrator.run()

    if result:
        # 保存
        config_dir = Path(args.config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        roi_path = config_dir / "roi_config.json"
        with open(roi_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\n✅ ROI 配置已保存: {roi_path}")
        print(f"   已标注 {len(result)} 个区域: {', '.join(result.keys())}")
    else:
        print("\n❌ 校准已取消。")


if __name__ == "__main__":
    main()
