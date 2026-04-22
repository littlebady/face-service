# 工程化重构说明

本次重构将原先的单文件 `api.py` 改造为分层架构，并保持原有接口路径不变。

## 目录结构

```text
app/
  core/
    settings.py        # 配置中心（环境变量、目录初始化）
    logging.py         # 请求 ID + 耗时日志中间件
  dependencies.py      # FastAPI 依赖注入（FaceDB、Settings、Admin 鉴权）
  routers/
    pages.py           # 首页/测试页
    faces.py           # /faces/register /faces/search /faces
    checkins.py        # /checkins* /checkin
    admin.py           # /admin/*（统一鉴权）
  services/
    face_service.py    # 人脸业务逻辑
    checkin_service.py # 签到业务逻辑
  utils/
    uploads.py         # 上传校验 + 落盘
    media.py           # URL 序列化、CSV、地理距离
  factory.py           # create_app 应用工厂
```

## 兼容性

- 启动命令保持不变：`uvicorn api:app --reload`
- 原有 API 路径保持不变
- `config.py` 仍保留旧常量接口（`DB_PATH` / `MEDIA_ROOT` 等）

## 新增工程化能力

- 管理接口统一 Bearer Token 鉴权（`FACE_SERVICE_ADMIN_TOKEN`）
- 上传图片类型和大小校验（默认 5MB）
- 请求 ID 与耗时日志
- 自动目录初始化
- 单测改为内存数据库，避免平台写盘限制
- 向量索引检索（FAISS/Annoy 自动回退到内置向量索引）
- embedding 缓存与批量写入能力（`FaceDB.add_face_embeddings_batch`）
- 性能压测脚本与基线报告输出（`benchmark_performance.py`）

## 关键环境变量

- `FACE_SERVICE_DB_PATH`
- `FACE_SERVICE_MEDIA_ROOT`
- `FACE_SERVICE_CORS_ORIGINS`
- `FACE_SERVICE_CORS_ALLOW_CREDENTIALS`
- `FACE_SERVICE_UPLOAD_MAX_BYTES`
- `FACE_SERVICE_UPLOAD_ALLOWED_EXTENSIONS`
- `FACE_SERVICE_ADMIN_TOKEN`
- `FACE_SERVICE_VECTOR_BACKEND` (`auto`/`faiss`/`annoy`/`bruteforce`)
- `FACE_SERVICE_VECTOR_ANNOY_TREES`
- `FACE_SERVICE_VECTOR_CANDIDATE_MULTIPLIER`
- `FACE_SERVICE_ENABLE_EMBEDDING_CACHE`
- `FACE_SERVICE_QUERY_EMBEDDING_CACHE_SIZE`

## 性能压测

运行：

```bash
python benchmark_performance.py --num-faces 5000 --num-queries 400
```

输出：

- `data/reports/performance_baseline_*.json`
- `data/reports/performance_baseline_*.md`
