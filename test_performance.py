#!/usr/bin/env python3
"""测试人脸识别性能（时间）"""
import time
import os
from pathlib import Path

# 设置环境变量避免OpenMP库重复初始化
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

from face_model import detect_and_extract


def benchmark_recognition_time(image_path: Path, iterations: int = 10) -> float:
    """测试人脸识别时间
    
    Args:
        image_path: 测试图片路径
        iterations: 测试次数
    
    Returns:
        平均识别时间（秒）
    """
    print(f"测试图片: {image_path}")
    print(f"测试次数: {iterations}")
    print("=" * 50)
    
    # 预热（首次运行会加载模型，不计入时间）
    print("正在预热...")
    _ = detect_and_extract(image_path)
    print("预热完成")
    
    # 正式测试
    times = []
    for i in range(iterations):
        start_time = time.time()
        _ = detect_and_extract(image_path)
        end_time = time.time()
        elapsed = end_time - start_time
        times.append(elapsed)
        print(f"第 {i+1} 次: {elapsed:.4f} 秒")
    
    # 计算统计信息
    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)
    
    print("=" * 50)
    print(f"平均时间: {avg_time:.4f} 秒")
    print(f"最短时间: {min_time:.4f} 秒")
    print(f"最长时间: {max_time:.4f} 秒")
    
    return avg_time


if __name__ == "__main__":
    # 测试图片路径
    test_image = Path(__file__).resolve().parent / "images" / "zhanghanwen.jpg"
    
    # 运行性能测试
    benchmark_recognition_time(test_image, iterations=10)
