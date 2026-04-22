#!/usr/bin/env python3
from pathlib import Path

from config import BASE_DIR, DB_PATH

def quick_test():
    print("🚀 快速测试人脸识别系统...")
    
    try:
        print("1️⃣ 测试模块导入...")
        from face_model import detect_and_extract
        from db_manager import FaceDB
        from matcher import match_student
        print("✅ 所有模块导入成功")
        
        print("2️⃣ 测试人脸检测...")
        test_image = BASE_DIR / "images" / "zhanghanwen.jpg"
        results = detect_and_extract(test_image, visualize=False, as_list=False)
        if results:
            print(f"✅ 检测到 {len(results)} 张人脸")
        else:
            print("❌ 未检测到人脸")
            return False
        
        print("3️⃣ 测试数据库...")
        db = FaceDB(db_path=DB_PATH)
        faces = db.get_all_faces()
        print(f"✅ 数据库中有 {len(faces)} 条记录")
        
        print("4️⃣ 测试人脸匹配...")
        test_match_image = BASE_DIR / "images" / "zhanghanwen.jpg"
        with open(test_match_image, "rb") as f:
            img_bytes = f.read()
        
        result, message = match_student(img_bytes, threshold=0.6)
        print(f"📝 匹配结果: {message}")
        
        if result:
            print(f"✅ 匹配成功: {result['person_name']}, 相似度: {result['similarity']:.4f}")
        else:
            print("❌ 匹配失败")
        
        print("\n🎉 快速测试完成！系统基本功能正常")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = quick_test()
    if success:
        print("\n📖 下一步:")
        print("1. 运行完整测试: python test_system.py")
        print("2. 启动API服务: uvicorn api:app --host 0.0.0.0 --port 8000 --reload")
    else:
        print("\n⚠️  请检查错误信息并修复问题")
