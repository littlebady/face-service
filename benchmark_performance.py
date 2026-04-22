from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Dict, List

import numpy as np

from db_manager import FaceDB


@dataclass
class ModeConfig:
    name: str
    vector_backend: str
    enable_embedding_cache: bool


def _normalize(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(arr))
    if norm == 0:
        raise ValueError("向量范数不能为 0")
    return arr / norm


def _compute_stats(latencies_ms: List[float]) -> Dict[str, float]:
    data = np.asarray(latencies_ms, dtype=np.float64)
    return {
        "avg_ms": float(np.mean(data)),
        "p50_ms": float(np.percentile(data, 50)),
        "p95_ms": float(np.percentile(data, 95)),
        "p99_ms": float(np.percentile(data, 99)),
        "min_ms": float(np.min(data)),
        "max_ms": float(np.max(data)),
    }


def _build_dataset(num_faces: int, dim: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    raw = rng.normal(size=(num_faces, dim)).astype(np.float32)
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return raw / norms


def _build_queries(base_embeddings: np.ndarray, num_queries: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed + 1000)
    idx = rng.integers(0, base_embeddings.shape[0], size=num_queries)
    noise = rng.normal(loc=0.0, scale=0.01, size=(num_queries, base_embeddings.shape[1])).astype(np.float32)
    queries = base_embeddings[idx] + noise
    return np.asarray([_normalize(item) for item in queries], dtype=np.float32)


def _chunk_records(records: List[Dict], batch_size: int) -> List[List[Dict]]:
    return [records[i : i + batch_size] for i in range(0, len(records), batch_size)]


def _build_report_markdown(payload: Dict) -> str:
    lines = [
        "# 人脸检索性能基线报告",
        "",
        f"- 生成时间: {payload['generated_at']}",
        f"- 样本规模: {payload['config']['num_faces']} faces",
        f"- 查询次数: {payload['config']['num_queries']}",
        f"- 向量维度: {payload['config']['dim']}",
        "",
        "## 指标说明",
        "",
        "- `avg_ms`: 平均延迟",
        "- `p95_ms`: 95 分位延迟",
        "- `p99_ms`: 99 分位延迟",
        "",
        "## 结果对比",
        "",
        "| 模式 | 后端 | 缓存 | avg_ms | p95_ms | p99_ms |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in payload["results"]:
        metric = item["metrics"]
        lines.append(
            f"| {item['mode']} | {item['index_backend']} | {int(item['embedding_cache_enabled'])} | "
            f"{metric['avg_ms']:.3f} | {metric['p95_ms']:.3f} | {metric['p99_ms']:.3f} |"
        )

    best = min(payload["results"], key=lambda x: x["metrics"]["p95_ms"])
    lines.extend(
        [
            "",
            "## 结论",
            "",
            (
                f"- 当前最佳模式（按 P95）: `{best['mode']}`，"
                f"P95={best['metrics']['p95_ms']:.3f} ms，P99={best['metrics']['p99_ms']:.3f} ms。"
            ),
        ]
    )
    return "\n".join(lines)


def run_benchmark(
    *,
    num_faces: int,
    num_queries: int,
    dim: int,
    top_k: int,
    threshold: float,
    batch_size: int,
    seed: int,
    report_dir: Path,
) -> Dict:
    modes = [
        ModeConfig(name="sqlite_scan", vector_backend="bruteforce", enable_embedding_cache=False),
        ModeConfig(name="vector_auto", vector_backend="auto", enable_embedding_cache=True),
        ModeConfig(name="vector_bruteforce", vector_backend="bruteforce", enable_embedding_cache=True),
    ]

    embeddings = _build_dataset(num_faces=num_faces, dim=dim, seed=seed)
    queries = _build_queries(base_embeddings=embeddings, num_queries=num_queries, seed=seed)

    records = [
        {
            "person_name": f"user_{i}",
            "embedding": embeddings[i],
            "image_path": f"embedded://user_{i}",
        }
        for i in range(num_faces)
    ]

    results = []
    for mode in modes:
        db = FaceDB(
            db_path=":memory:",
            vector_backend=mode.vector_backend,
            enable_embedding_cache=mode.enable_embedding_cache,
            query_embedding_cache_size=0,
        )
        try:
            insert_start = perf_counter()
            for chunk in _chunk_records(records, batch_size=batch_size):
                db.add_face_embeddings_batch(chunk)
            insert_ms = (perf_counter() - insert_start) * 1000.0

            # 预热一次，避免首查建索引影响统计
            db.search_face(embedding=queries[0], top_k=top_k, threshold=threshold)

            latencies_ms = []
            for query in queries:
                start = perf_counter()
                db.search_face(embedding=query, top_k=top_k, threshold=threshold)
                latencies_ms.append((perf_counter() - start) * 1000.0)

            mode_stats = db.get_vector_index_stats()
            metrics = _compute_stats(latencies_ms)
            metrics["insert_total_ms"] = float(insert_ms)
            metrics["insert_avg_per_face_ms"] = float(insert_ms / num_faces)

            results.append(
                {
                    "mode": mode.name,
                    "index_backend": mode_stats["backend"],
                    "requested_backend": mode_stats["requested_backend"],
                    "embedding_cache_enabled": mode.enable_embedding_cache,
                    "metrics": metrics,
                }
            )
        finally:
            db.close()

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "num_faces": num_faces,
            "num_queries": num_queries,
            "dim": dim,
            "top_k": top_k,
            "threshold": threshold,
            "batch_size": batch_size,
            "seed": seed,
        },
        "results": results,
    }

    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"performance_baseline_{stamp}.json"
    md_path = report_dir / f"performance_baseline_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_build_report_markdown(payload), encoding="utf-8")

    payload["report_json"] = str(json_path.resolve())
    payload["report_md"] = str(md_path.resolve())
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="人脸向量检索性能压测并输出基线报告")
    parser.add_argument("--num-faces", type=int, default=5000)
    parser.add_argument("--num-queries", type=int, default=400)
    parser.add_argument("--dim", type=int, default=512)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.6)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--report-dir", type=str, default="data/reports")
    args = parser.parse_args()

    payload = run_benchmark(
        num_faces=max(100, args.num_faces),
        num_queries=max(50, args.num_queries),
        dim=max(64, args.dim),
        top_k=max(1, args.top_k),
        threshold=min(1.0, max(0.0, args.threshold)),
        batch_size=max(10, args.batch_size),
        seed=args.seed,
        report_dir=Path(args.report_dir).resolve(),
    )

    print("性能压测完成。")
    for item in payload["results"]:
        m = item["metrics"]
        print(
            f"[{item['mode']}] backend={item['index_backend']} "
            f"avg={m['avg_ms']:.3f}ms p95={m['p95_ms']:.3f}ms p99={m['p99_ms']:.3f}ms"
        )
    print(f"JSON 报告: {payload['report_json']}")
    print(f"MD 报告:   {payload['report_md']}")


if __name__ == "__main__":
    main()
