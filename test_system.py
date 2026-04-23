#!/usr/bin/env python3
import os
import sys
import traceback
from pathlib import Path

from config import BASE_DIR, DB_PATH

def check_face_detection():
    print("=" * 50)
    print("测试1: 人脸检测和特征提取")
    print("=" * 50)
    
    try:
        from face_model import detect_and_extract
        
        test_image = BASE_DIR / "images" / "zhanghanwen.jpg"
        if not test_image.exists():
            print(f"❌ 测试图片不存在: {test_image}")
            return False
            
        print(f"📸 正在检测图片: {test_image}")
        results = detect_and_extract(test_image, visualize=False, as_list=False)
        
        if results:
            print(f"✅ 检测成功！发现 {len(results)} 张人脸")
            for i, face in enumerate(results):
                print(f"   人脸 {i+1}:")
                print(f"     - 边界框: {face['bbox']}")
                print(f"     - 关键点数量: {len(face['kps'])}")
                print(f"     - 特征向量维度: {len(face['embedding'])}")
                print(f"     - 特征向量类型: {type(face['embedding'])}")
        else:
            print("❌ 未检测到人脸")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ 人脸检测测试失败: {e}")
        traceback.print_exc()
        return False

def check_database():
    print("\n" + "=" * 50)
    print("测试2: 数据库操作")
    print("=" * 50)
    
    try:
        from db_manager import FaceDB
        
        print("🗄️  初始化数据库...")
        db = FaceDB(db_path=DB_PATH)
        print("✅ 数据库初始化成功")
        
        print("📋 查看现有数据...")
        faces = db.get_all_faces()
        print(f"✅ 数据库中共有 {len(faces)} 条人脸记录")
        
        for face in faces:
            print(f"   - ID: {face['face_id']}, 姓名: {face['person_name']}, 图片: {face['image_path']}")
            
        return True
        
    except Exception as e:
        print(f"❌ 数据库测试失败: {e}")
        traceback.print_exc()
        return False

def check_face_matching():
    print("\n" + "=" * 50)
    print("测试3: 人脸匹配功能")
    print("=" * 50)
    
    try:
        from matcher import match_student
        
        test_image = BASE_DIR / "picture3.jpg"
        if not test_image.exists():
            print(f"❌ 测试图片不存在: {test_image}")
            return False
            
        print(f"🔍 正在匹配图片: {test_image}")
        
        with open(test_image, "rb") as f:
            img_bytes = f.read()
        
        result, message = match_student(img_bytes, threshold=0.6)
        
        print(f"📝 匹配结果: {message}")
        if result:
            print(f"✅ 匹配成功！")
            print(f"   - 姓名: {result['person_name']}")
            print(f"   - 相似度: {result['similarity']:.4f}")
            print(f"   - 图片路径: {result['image_path']}")
        else:
            print("❌ 匹配失败")
            
        return True
        
    except Exception as e:
        print(f"❌ 人脸匹配测试失败: {e}")
        traceback.print_exc()
        return False

def check_api_creation():
    print("\n" + "=" * 50)
    print("测试4: API创建测试")
    print("=" * 50)
    
    try:
        from api import app
        
        print("✅ API应用创建成功")
        print(f"   - 标题: {app.title}")
        print(f"   - 版本: {app.version}")
        
        routes = []
        for route in app.routes:
            if hasattr(route, 'path'):
                routes.append(f"{route.methods} {route.path}")
        
        print(f"   - 可用路由: {len(routes)} 个")
        for route in routes:
            print(f"     {route}")
            
        return True
        
    except Exception as e:
        print(f"❌ API创建测试失败: {e}")
        traceback.print_exc()
        return False

def main():
    print("🚀 开始测试人脸识别系统...")
    print(f"📁 当前工作目录: {os.getcwd()}")
    
    tests = [
        ("人脸检测", check_face_detection),
        ("数据库操作", check_database),
        ("人脸匹配", check_face_matching),
        ("API创建", check_api_creation),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
                print(f"✅ {test_name} 测试通过")
            else:
                print(f"❌ {test_name} 测试失败")
        except Exception as e:
            print(f"❌ {test_name} 测试异常: {e}")
    
    print("\n" + "=" * 50)
    print("测试总结")
    print("=" * 50)
    print(f"📊 总测试数: {total}")
    print(f"✅ 通过: {passed}")
    print(f"❌ 失败: {total - passed}")
    print(f"📈 成功率: {passed/total*100:.1f}%")
    
    if passed == total:
        print("\n🎉 所有测试通过！系统运行正常")
        print("\n📖 下一步操作:")
        print("1. 启动API服务: uvicorn api:app --host 0.0.0.0 --port 8000 --reload")
        print("2. 访问接口文档: http://127.0.0.1:8000/docs")
        print("3. 测试注册接口: POST /faces/register")
        print("4. 测试搜索接口: POST /faces/search")
        print("5. 测试签到接口: POST /checkin")
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败，请检查错误信息")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
