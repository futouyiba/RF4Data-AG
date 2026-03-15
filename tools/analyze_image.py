"""
截图分析与调试工具
=================
加载单张或多张截图，进行 HSV 颜色分析、OCR 测试和模板匹配。
用于调试视觉参数和验证识别逻辑。

用法:
    python tools/analyze_image.py <image_path> [options]
    python tools/analyze_image.py data/evidence/*.png --hsv "100 900 50 50"
    python tools/analyze_image.py --ocr --roi "10 800 400 100" <image_path>
"""

import sys
import cv2
import argparse
import numpy as np
from pathlib import Path
from PIL import Image

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 尝试导入 pytesseract，如果失败则优雅降级
try:
    import pytesseract
    _HAS_OCR = True
except ImportError:
    _HAS_OCR = False


def analyze_hsv_roi(image: np.ndarray, roi: tuple[int, int, int, int]):
    """分析指定 ROI 的 HSV 统计信息。"""
    x, y, w, h = roi
    crop = image[y:y+h, x:x+w]
    
    if crop.size == 0:
        print(f"Error: ROI {roi} is empty or out of bounds.")
        return

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h_mean = np.mean(hsv[:, :, 0])
    s_mean = np.mean(hsv[:, :, 1])
    v_mean = np.mean(hsv[:, :, 2])
    
    print(f"\n--- ROI Analysis {roi} ---")
    print(f"Mean HSV: ({h_mean:.1f}, {s_mean:.1f}, {v_mean:.1f})")
    print(f"Min  HSV: {np.min(hsv, axis=(0,1))}")
    print(f"Max  HSV: {np.max(hsv, axis=(0,1))}")


def test_ocr(image: np.ndarray, roi: tuple[int, int, int, int] = None):
    """测试 OCR 识别。"""
    if not _HAS_OCR:
        print("pytesseract not installed, skipping OCR test.")
        return

    if roi:
        x, y, w, h = roi
        crop = image[y:y+h, x:x+w]
        print(f"\n--- OCR Test (ROI {roi}) ---")
    else:
        crop = image
        print("\n--- OCR Test (Full Image) ---")

    # 预处理：灰度 + 二值化
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # 尝试不同模式
    pil_img = Image.fromarray(binary)
    
    print("Mode 6 (Sparse text):")
    try:
        text = pytesseract.image_to_string(pil_img, config='--psm 6', lang='eng')
        print(f">>>\n{text.strip()}\n<<<")
    except Exception as e:
        print(f"OCR Error: {e}")

    print("Mode 7 (Single line):")
    try:
        text = pytesseract.image_to_string(pil_img, config='--psm 7', lang='eng')
        print(f">>>\n{text.strip()}\n<<<")
    except Exception as e:
        print(f"OCR Error: {e}")


def show_hsv_mask(image: np.ndarray, roi: tuple[int, int, int, int], lower: tuple[int, int, int], upper: tuple[int, int, int]):
    """显示指定 HSV 范围的遮罩。"""
    x, y, w, h = roi
    crop = image[y:y+h, x:x+w]
    
    if crop.size == 0:
        print(f"Error: ROI {roi} is empty or out of bounds.")
        return

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    lower_bound = np.array(lower, dtype=np.uint8)
    upper_bound = np.array(upper, dtype=np.uint8)
    
    mask = cv2.inRange(hsv, lower_bound, upper_bound)
    res = cv2.bitwise_and(crop, crop, mask=mask)
    
    cv2.imshow("Original Crop", crop)
    cv2.imshow("HSV Mask", mask)
    cv2.imshow("Color Filtered", res)
    print("Mask visualization active. Press any key to close the windows...")
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="RF4 Screenshot Analysis Tool")
    parser.add_argument("images", nargs='+', help="Path to image(s)")
    parser.add_argument("--roi", type=int, nargs=4, metavar=('X', 'Y', 'W', 'H'), 
                        help="ROI to analyze (x y w h)")
    parser.add_argument("--hsv", action="store_true", help="Analyze HSV statistics in ROI")
    parser.add_argument("--ocr", action="store_true", help="Perform OCR test on ROI")
    parser.add_argument("--show", action="store_true", help="Show image with ROI drawn")
    parser.add_argument("--mask-hsv", type=int, nargs=6, metavar=('H1','S1','V1','H2','S2','V2'),
                        help="显示特定HSV区间的Mask (lower_h s v upper_h s v)")
    parser.add_argument("--scale-720p", action="store_true", help="如果样本是 720p 截图，自动放大回 1080p 以适配 ROI")
    
    args = parser.parse_args()

    for img_path in args.images:
        path = Path(img_path)
        if not path.exists():
            print(f"File not found: {path}")
            continue
            
        print(f"\n{'='*40}")
        print(f"Analyzing: {path.name}")
        
        # 读取图片 (支持中文路径)
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print("Failed to load image.")
            continue
            
        if args.scale_720p and img.shape[0] == 720 and img.shape[1] == 1280:
            print("Auto-scaling 720p image to 1080p...")
            img = cv2.resize(img, (1920, 1080), interpolation=cv2.INTER_LANCZOS4)
            
        height, width = img.shape[:2]
        print(f"Size: {width}x{height}")

        # 如果没有指定 ROI，默认分析中心区域或全图
        roi = tuple(args.roi) if args.roi else (0, 0, width, height)

        if args.hsv:
            analyze_hsv_roi(img, roi)
            
        if args.mask_hsv:
            lower = tuple(args.mask_hsv[0:3])
            upper = tuple(args.mask_hsv[3:6])
            print(f"Showing mask for HSV Range: {lower} -> {upper}")
            show_hsv_mask(img, roi, lower, upper)
            
        if args.ocr:
            test_ocr(img, roi)

        if args.show:
            display = img.copy()
            x, y, w, h = roi
            cv2.rectangle(display, (x, y), (x+w, y+h), (0, 255, 0), 2)
            
            #缩放以适应屏幕
            scale = min(1.0, 1280/width, 800/height)
            if scale < 1.0:
                display = cv2.resize(display, None, fx=scale, fy=scale)
            
            cv2.imshow(f"Analysis - {path.name}", display)
            cv2.waitKey(0)
            cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
