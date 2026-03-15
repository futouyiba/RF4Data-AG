"""
CV 算法批量离线测试工具
======================
用于在真实游戏截图样本集上批量运行视觉检测模块，
统计准确率，以便调试 HSV 颜色阈值和 OCR 参数。

用法:
    python tools/batch_test_cv.py --type bite --dir data/samples/bites/ --rod 1
    python tools/batch_test_cv.py --type tension --dir data/samples/tension/
    python tools/batch_test_cv.py --type popup --dir data/samples/popups/
"""

import sys
import argparse
import logging
from pathlib import Path
from typing import List, Callable, Dict, Any

import cv2
import numpy as np
from tabulate import tabulate

# 确保能导入 src 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.vision import VisionSensor
from src.core.config import ConfigLoader

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("batch_tester")


def get_expected_label(filename: str) -> str:
    """
    从文件名中提取期望结果 (Label)。
    约定格式：`BITE_sample_1.png`, `NIBBLE_002.jpg`, `SAFE_bar.png` 等。
    提取第一段大写字母。
    """
    stem = Path(filename).stem
    parts = stem.split("_")
    for part in parts:
        if part.isupper() and part.isalpha():
            return part
    return "UNKNOWN"


def run_batch_test(
    test_type: str,
    sample_dir: Path,
    detect_func: Callable[[np.ndarray], Any],
    value_extractor: Callable[[Any], str],
    confidence_threshold: float = 0.5,
    scale_720p: bool = False,
) -> None:
    """运行批量测试并输出统计。"""
    
    if not sample_dir.exists():
        logger.error(f"样本目录不存在: {sample_dir}")
        return

    images = list(sample_dir.glob("*.png")) + list(sample_dir.glob("*.jpg"))
    if not images:
        logger.warning(f"目录 {sample_dir} 中没有找到图片 (.png, .jpg)")
        return

    logger.info(f"开始批量测试 [{test_type}]，共 {len(images)} 张样本图片\n")

    results_table = []
    correct_count = 0
    total_count = len(images)

    for img_path in sorted(images):
        frame = cv2.imread(str(img_path))
        if frame is None:
            logger.error(f"无法读取图片: {img_path}")
            total_count -= 1
            continue

        if scale_720p and frame.shape[0] == 720 and frame.shape[1] == 1280:
            # 录制的 720p 视频截图，缩放回 1080p 基准
            frame = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_LANCZOS4)

        # 执行检测
        raw_result = detect_func(frame)
        predicted_val = value_extractor(raw_result)
        confidence = getattr(raw_result, "confidence", 0.0)
        
        # Ocr 等结果可能没有信心阈值过滤逻辑直接在 value 里，这里只做展示过滤
        if confidence < confidence_threshold and getattr(raw_result, "confidence", 1.0) < 1.0:
            predicted_val = "NONE/LOW_CONF"

        expected_val = get_expected_label(img_path.name)
        
        is_correct = ""
        if expected_val != "UNKNOWN":
            # 简单比较：是否包含 erwarted_val (忽略大小写)
            if expected_val.upper() in str(predicted_val).upper():
                is_correct = "✅"
                correct_count += 1
            else:
                is_correct = "❌"
                
        metrics = getattr(raw_result, "raw_metrics", {})
        metric_str = ", ".join(f"{k}: {v}" for k, v in metrics.items()) if metrics else ""

        results_table.append([
            img_path.name,
            expected_val,
            str(predicted_val),
            f"{confidence:.2f}",
            is_correct,
            metric_str
        ])

    print(tabulate(
        results_table,
        headers=["文件名", "期望结果(Label)", "预测结果", "置信度", "校验", "关键指标 (Metrics)"],
        tablefmt="github"
    ))

    # 统计
    evaluable_tasks = sum(1 for row in results_table if row[1] != "UNKNOWN")
    if evaluable_tasks > 0:
        acc = correct_count / evaluable_tasks
        print(f"\n=====================================")
        print(f"[{test_type}] 准确率评估结果:")
        print(f"带 Label 样本数 : {evaluable_tasks}")
        print(f"预测正确数量   : {correct_count}")
        print(f"准确率 (Acc)   : {acc:.1%}")
        print(f"=====================================\n")
    else:
        print("\n(注：未计算准确率，因为样本文件名中未包含预期 Label。请将文件名命名为如 BITE_01.png, SAFE_x.png)")

def main():
    parser = argparse.ArgumentParser(description="RF4-BRP 视觉算法离线批量测试工具")
    parser.add_argument("--type", choices=["bite", "tension", "popup", "chat"], required=True, 
                        help="测试的目标模块")
    parser.add_argument("--dir", required=True, help="样本图片存放目录")
    parser.add_argument("--rod", type=int, choices=[1, 2, 3], default=1, 
                        help="如果是鱼口测试，指定针对哪个插槽的竿")
    parser.add_argument("--config", default="config", help="配置文件目录，需要 roi_config.json")
    parser.add_argument("--scale-720p", action="store_true", help="如果样本是 720p 截图，自动放大回 1080p 以适配 ROI")
    
    args = parser.parse_args()
    
    from src.core.config import ConfigLoader
    config = ConfigLoader(args.config)
    
    if not config.has_roi:
        logger.error("未找到完整的 roi_config.json！请先运行 tools/calibrate.py 进行区域校准。")
        sys.exit(1)
        
    roi_config = {name: config.get_roi(name) for name in config.roi_names}

    sensor = VisionSensor(roi_config)
    sample_dir = Path(args.dir)

    if args.type == "bite":
        def detect_func(frame): return sensor.detect_bite(args.rod, frame)
        def val_extractor(res): return res.value.name
        run_batch_test("Bite Detection", sample_dir, detect_func, val_extractor, scale_720p=args.scale_720p)
        
    elif args.type == "tension":
        def detect_func(frame): return sensor.detect_tension(frame)
        def val_extractor(res): return res.value.name
        run_batch_test("Tension Bar", sample_dir, detect_func, val_extractor, scale_720p=args.scale_720p)
        
    elif args.type == "popup":
        def detect_func(frame): return sensor.detect_catch_popup(frame)
        def val_extractor(res):
            if res.value:
                return f"{res.value.get('fish_name', '')} {res.value.get('weight_kg', 0)}kg"
            return "No Catch"
        run_batch_test("Popup Catch OCR", sample_dir, detect_func, val_extractor, scale_720p=args.scale_720p)
        
    elif args.type == "chat":
        def detect_func(frame): return sensor.detect_catch_from_chat(frame)
        def val_extractor(res):
            if res.value:
                return f"{res.value.get('fish_name', '')} {res.value.get('weight_kg', 0)}kg"
            return "No Catch"
        run_batch_test("Chat Catch OCR", sample_dir, detect_func, val_extractor, scale_720p=args.scale_720p)

if __name__ == "__main__":
    main()
