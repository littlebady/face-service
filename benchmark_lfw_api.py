from __future__ import annotations

import argparse
import json
import logging
import random
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Sequence, Tuple
from urllib.request import urlretrieve
from uuid import uuid4

import numpy as np
from fastapi.testclient import TestClient
from sklearn.datasets import fetch_lfw_people

from app.core.settings import Settings, ensure_directories
from app.factory import create_app


LFW_URL = "https://vis-www.cs.umass.edu/lfw/lfw-funneled.tgz"


@dataclass
class PersonSample:
    name: str
    register_image: Path
    probe_images: List[Path]


@dataclass
class ImpostorAttempt:
    attacker_name: str
    target_name: str
    probe_image: Path


def compute_stats(latencies_ms: Sequence[float]) -> Dict[str, float]:
    if not latencies_ms:
        return {
            "count": 0,
            "avg_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
        }
    arr = np.asarray(latencies_ms, dtype=np.float64)
    return {
        "count": int(arr.size),
        "avg_ms": float(np.mean(arr)),
        "p50_ms": float(np.percentile(arr, 50)),
        "p95_ms": float(np.percentile(arr, 95)),
        "p99_ms": float(np.percentile(arr, 99)),
        "min_ms": float(np.min(arr)),
        "max_ms": float(np.max(arr)),
    }


def download_and_extract_lfw(dataset_dir: Path) -> Path:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    lfw_root = dataset_dir / "lfw_funneled"
    if lfw_root.exists():
        return lfw_root

    archive_path = dataset_dir / "lfw-funneled.tgz"
    print(f"[1/4] 下载 LFW 数据集: {LFW_URL}")
    try:
        if not archive_path.exists():
            urlretrieve(LFW_URL, archive_path)  # noqa: S310

        print("[2/4] 解压数据集...")
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(path=dataset_dir)

        if lfw_root.exists():
            return lfw_root
    except Exception as exc:
        print(f"主下载源失败，自动切换 sklearn 官方下载链路: {exc}")

    print("[2/4] 使用 sklearn 下载并准备 LFW...")
    fetch_lfw_people(
        data_home=str(dataset_dir),
        min_faces_per_person=1,
        resize=0.4,
        color=False,
        download_if_missing=True,
    )
    sklearn_root = dataset_dir / "lfw_home" / "lfw_funneled"
    if sklearn_root.exists():
        return sklearn_root

    raise RuntimeError("LFW 下载失败：主源与 sklearn 备用源均不可用")


def choose_samples(
    lfw_root: Path,
    *,
    max_identities: int,
    min_images_per_identity: int,
    register_ratio: float,
    use_all_images: bool,
    seed: int,
) -> Tuple[List[PersonSample], List[Tuple[str, List[Path]]]]:
    rng = random.Random(seed)
    candidates: List[Tuple[str, List[Path]]] = []

    for person_dir in sorted(lfw_root.iterdir()):
        if not person_dir.is_dir():
            continue
        images = sorted(
            [
                p
                for p in person_dir.iterdir()
                if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
            ]
        )
        if len(images) >= min_images_per_identity:
            candidates.append((person_dir.name, images))

    if not candidates:
        return [], []

    if max_identities <= 0:
        max_identities = int(len(candidates) * register_ratio)
    max_identities = max(1, min(max_identities, len(candidates)))

    rng.shuffle(candidates)
    picked = candidates[:max_identities]
    leftovers = candidates[max_identities:]
    samples: List[PersonSample] = []
    for name, images in picked:
        register_image = images[0]
        if use_all_images:
            probe_images = images[1:]
        else:
            probe_images = [images[rng.randrange(1, len(images))]]
        samples.append(
            PersonSample(
                name=name,
                register_image=register_image,
                probe_images=probe_images,
            )
        )
    return samples, leftovers


def choose_impostor_attempts(
    *,
    leftover_candidates: Sequence[Tuple[str, List[Path]]],
    victims: Sequence[PersonSample],
    impostor_count: int,
    use_all_images: bool,
    seed: int,
) -> List[ImpostorAttempt]:
    if not victims:
        return []
    if impostor_count <= 0 and not use_all_images:
        return []

    rng = random.Random(seed + 7919)
    pool = list(leftover_candidates)
    rng.shuffle(pool)

    attempts: List[ImpostorAttempt] = []
    if use_all_images:
        image_pool: List[Tuple[str, Path]] = []
        for attacker_name, images in pool:
            image_pool.extend((attacker_name, img) for img in images)
        rng.shuffle(image_pool)
        if impostor_count > 0:
            image_pool = image_pool[:impostor_count]
        for attacker_name, probe_image in image_pool:
            target_name = victims[rng.randrange(0, len(victims))].name
            attempts.append(
                ImpostorAttempt(
                    attacker_name=attacker_name,
                    target_name=target_name,
                    probe_image=probe_image,
                )
            )
    else:
        picked = pool[:impostor_count]
        for attacker_name, images in picked:
            if len(images) < 2:
                continue
            probe_image = images[rng.randrange(1, len(images))]
            target_name = victims[rng.randrange(0, len(victims))].name
            attempts.append(
                ImpostorAttempt(
                    attacker_name=attacker_name,
                    target_name=target_name,
                    probe_image=probe_image,
                )
            )
    return attempts


def make_app_for_benchmark(runtime_root: Path, *, vector_backend: str) -> TestClient:
    base_dir = Path(__file__).resolve().parent
    media_root = (runtime_root / "media").resolve()
    db_path = (runtime_root / "bench.db").resolve()
    settings = Settings(
        base_dir=base_dir,
        data_dir=runtime_root.resolve(),
        db_path=db_path,
        media_root=media_root,
        register_image_dir=media_root / "registered_faces",
        checkin_image_dir=media_root / "checkins",
        cors_origins=["*"],
        cors_allow_credentials=False,
        upload_max_bytes=5 * 1024 * 1024,
        upload_allowed_extensions={".jpg", ".jpeg", ".png", ".bmp", ".webp"},
        admin_token="bench-admin-token",
        auto_geofence_min_samples=3,
        auto_geofence_max_points=500,
        auto_geofence_cluster_distance_m=120.0,
        vector_backend=vector_backend,
        vector_annoy_trees=20,
        vector_candidate_multiplier=8,
        enable_embedding_cache=True,
        query_embedding_cache_size=256,
        strict_liveness_required=False,
        liveness_challenge_ttl_seconds=45,
        liveness_max_proof_age_seconds=180,
        liveness_min_duration_ms=4200,
        liveness_max_duration_ms=25000,
        liveness_min_motion_score=0.0018,
        liveness_max_missing_frames=16,
        antispoof_model_path=(base_dir / "models" / "anti_spoof" / "anti_spoof.onnx"),
        antispoof_required=False,
        antispoof_min_live_score=0.60,
        antispoof_relaxed_pass_enabled=True,
        antispoof_relaxed_min_live_score=0.12,
        antispoof_input_size=128,
        antispoof_live_class_index=0,
        antispoof_preprocess_mode="minifas",
        liveness_ticket_ttl_seconds=180,
        liveness_signing_key="bench-liveness-signing-key",
        liveness_session_face_min_similarity=0.62,
        liveness_evidence_min_frames=2,
        liveness_evidence_max_frames=6,
    )
    ensure_directories(settings)
    app = create_app(settings=settings)
    logging.getLogger("face_service").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return TestClient(app)


def run_benchmark(
    samples: Sequence[PersonSample],
    impostor_attempts: Sequence[ImpostorAttempt],
    *,
    threshold: float,
    search_top_k: int,
    vector_backend: str,
    temp_root: str | None = None,
) -> Dict[str, Any]:
    if temp_root:
        temp_root_path = Path(temp_root).resolve()
        temp_root_path.mkdir(parents=True, exist_ok=True)
        runtime_root = temp_root_path / f"lfw_bench_{uuid4().hex}"
        runtime_root.mkdir(parents=True, exist_ok=False)
    else:
        runtime_root = Path(tempfile.mkdtemp(prefix="lfw_bench_"))

    try:
        client = make_app_for_benchmark(runtime_root, vector_backend=vector_backend)

        register_latencies: List[float] = []
        search_latencies: List[float] = []
        checkin_latencies: List[float] = []

        register_ok = 0
        search_top1_hit = 0
        checkin_ok = 0
        genuine_probe_attempts = 0
        impostor_false_accept = 0
        impostor_targeted_success = 0
        impostor_latencies: List[float] = []
        impostor_hits: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        print(f"[3/4] 执行 API 基准测试（身份数: {len(samples)}）...")
        for idx, sample in enumerate(samples, start=1):
            print(f"  - [{idx}/{len(samples)}] {sample.name}")

            # register
            t0 = perf_counter()
            with sample.register_image.open("rb") as f:
                reg_resp = client.post(
                    "/faces/register",
                    data={"name": sample.name},
                    files={"file": (sample.register_image.name, f, "image/jpeg")},
                )
            register_latencies.append((perf_counter() - t0) * 1000.0)
            if reg_resp.status_code == 200 and reg_resp.json().get("ok"):
                register_ok += 1
            else:
                errors.append(
                    {
                        "stage": "register",
                        "person": sample.name,
                        "status_code": reg_resp.status_code,
                        "response": reg_resp.text[:400],
                    }
                )
                continue

            for probe_image in sample.probe_images:
                genuine_probe_attempts += 1

                # search
                t1 = perf_counter()
                with probe_image.open("rb") as f:
                    search_resp = client.post(
                        "/faces/search",
                        data={"threshold": str(threshold), "top_k": str(search_top_k)},
                        files={"file": (probe_image.name, f, "image/jpeg")},
                    )
                search_latencies.append((perf_counter() - t1) * 1000.0)
                if search_resp.status_code == 200 and search_resp.json().get("ok"):
                    results = search_resp.json().get("results", [])
                    if results and results[0].get("person_name") == sample.name:
                        search_top1_hit += 1
                else:
                    errors.append(
                        {
                            "stage": "search",
                            "person": sample.name,
                            "status_code": search_resp.status_code,
                            "response": search_resp.text[:400],
                        }
                    )

                # checkin
                t2 = perf_counter()
                with probe_image.open("rb") as f:
                    check_resp = client.post(
                        "/checkin",
                        data={
                            "lat": "30.274084",
                            "lng": "120.155070",
                            "threshold": str(threshold),
                            "top_k": "1",
                            "auto_geofence": "false",
                        },
                        files={"file": (probe_image.name, f, "image/jpeg")},
                    )
                checkin_latencies.append((perf_counter() - t2) * 1000.0)
                if check_resp.status_code == 200 and check_resp.json().get("ok"):
                    if check_resp.json().get("person_name") == sample.name:
                        checkin_ok += 1
                else:
                    errors.append(
                        {
                            "stage": "checkin",
                            "person": sample.name,
                            "status_code": check_resp.status_code,
                            "response": check_resp.text[:400],
                        }
                    )

        if impostor_attempts:
            print(f"[3/4-imp] 执行代签攻击测试（次数: {len(impostor_attempts)}）...")
            for idx, attempt in enumerate(impostor_attempts, start=1):
                if idx <= 5 or idx % 100 == 0 or idx == len(impostor_attempts):
                    print(
                        f"  - [A{idx}/{len(impostor_attempts)}] "
                        f"attacker={attempt.attacker_name} -> target={attempt.target_name}"
                    )
                t3 = perf_counter()
                with attempt.probe_image.open("rb") as f:
                    attack_resp = client.post(
                        "/checkin",
                        data={
                            "lat": "30.274084",
                            "lng": "120.155070",
                            "threshold": str(threshold),
                            "top_k": "1",
                            "auto_geofence": "false",
                        },
                        files={"file": (attempt.probe_image.name, f, "image/jpeg")},
                    )
                impostor_latencies.append((perf_counter() - t3) * 1000.0)
                if attack_resp.status_code != 200:
                    errors.append(
                        {
                            "stage": "impostor_checkin",
                            "attacker": attempt.attacker_name,
                            "target": attempt.target_name,
                            "status_code": attack_resp.status_code,
                            "response": attack_resp.text[:400],
                        }
                    )
                    continue

                payload = attack_resp.json()
                if payload.get("ok"):
                    impostor_false_accept += 1
                    matched_name = payload.get("person_name")
                    if matched_name == attempt.target_name:
                        impostor_targeted_success += 1
                    if len(impostor_hits) < 30:
                        impostor_hits.append(
                            {
                                "attacker": attempt.attacker_name,
                                "target": attempt.target_name,
                                "matched_name": matched_name,
                                "similarity": payload.get("similarity"),
                                "status": payload.get("status"),
                            }
                        )
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)

    total = len(samples)
    genuine_total = max(1, genuine_probe_attempts)
    impostor_total = len(impostor_attempts)
    true_reject = max(0, impostor_total - impostor_false_accept)
    return {
        "total_identities": total,
        "genuine_probe_attempts": genuine_probe_attempts,
        "vector_backend": vector_backend,
        "threshold": threshold,
        "search_top_k": search_top_k,
        "register": {
            "ok_count": register_ok,
            "ok_rate": float(register_ok / total) if total else 0.0,
            "latency": compute_stats(register_latencies),
        },
        "search": {
            "top1_hit_count": search_top1_hit,
            "top1_hit_rate": float(search_top1_hit / genuine_total),
            "latency": compute_stats(search_latencies),
        },
        "checkin": {
            "ok_count": checkin_ok,
            "ok_rate": float(checkin_ok / genuine_total),
            "latency": compute_stats(checkin_latencies),
        },
        "impostor_checkin": {
            "attempt_count": impostor_total,
            "false_accept_count": impostor_false_accept,
            "false_accept_rate": float(impostor_false_accept / impostor_total) if impostor_total else 0.0,
            "targeted_success_count": impostor_targeted_success,
            "targeted_success_rate": float(impostor_targeted_success / impostor_total) if impostor_total else 0.0,
            "true_reject_count": true_reject,
            "true_reject_rate": float(true_reject / impostor_total) if impostor_total else 0.0,
            "latency": compute_stats(impostor_latencies),
            "hits": impostor_hits,
        },
        "error_count": len(errors),
        "errors": errors[:30],
    }


def build_markdown_report(payload: Dict[str, Any]) -> str:
    reg = payload["results"]["register"]
    sea = payload["results"]["search"]
    chk = payload["results"]["checkin"]
    imp = payload["results"].get("impostor_checkin", {})

    def line_latency(name: str, metrics: Dict[str, float]) -> str:
        return (
            f"| {name} | {metrics['count']} | {metrics['avg_ms']:.2f} | "
            f"{metrics['p95_ms']:.2f} | {metrics['p99_ms']:.2f} | {metrics['min_ms']:.2f} | {metrics['max_ms']:.2f} |"
        )

    lines = [
        "# LFW ???????????",
        "",
        f"- ????: {payload['generated_at']}",
        f"- ???: LFW (Labeled Faces in the Wild), ??: {payload['dataset']['url']}",
        f"- ?????: {payload['dataset']['used_identities']}",
        f"- ?????: {payload['dataset'].get('register_image_count', payload['dataset']['used_identities'])}",
        f"- ????????: {payload['dataset'].get('genuine_probe_image_count', 0)}",
        f"- ???????: {payload['dataset'].get('impostor_attempts', 0)}",
        f"- ??????(????): {payload['dataset'].get('total_test_images', 0)}",
        f"- ????: `{payload['results']['vector_backend']}`",
        f"- ??: `{payload['results']['threshold']}`",
        "",
        "## ?????",
        "",
        f"- ?????: {reg['ok_rate'] * 100:.2f}% ({reg['ok_count']}/{payload['dataset']['used_identities']})",
        f"- ?? Top1 ???: {sea['top1_hit_rate'] * 100:.2f}% ({sea['top1_hit_count']}/{payload['results'].get('genuine_probe_attempts', 0)})",
        f"- ?????: {chk['ok_rate'] * 100:.2f}% ({chk['ok_count']}/{payload['results'].get('genuine_probe_attempts', 0)})",
        "",
        "## ??????",
        "",
        f"- ?????: {imp.get('attempt_count', 0)}",
        f"- ?????(FAR): {imp.get('false_accept_rate', 0.0) * 100:.2f}% ({imp.get('false_accept_count', 0)}/{imp.get('attempt_count', 0)})",
        f"- ???????: {imp.get('targeted_success_rate', 0.0) * 100:.2f}% ({imp.get('targeted_success_count', 0)}/{imp.get('attempt_count', 0)})",
        f"- ???(TRR): {imp.get('true_reject_rate', 0.0) * 100:.2f}% ({imp.get('true_reject_count', 0)}/{imp.get('attempt_count', 0)})",
        "",
        "## ????(??)",
        "",
        "| ?? | ??? | avg | p95 | p99 | min | max |",
        "|---|---:|---:|---:|---:|---:|---:|",
        line_latency("register", reg["latency"]),
        line_latency("search", sea["latency"]),
        line_latency("checkin", chk["latency"]),
        line_latency("impostor_checkin", imp.get("latency", compute_stats([]))),
        "",
        "## ??",
        "",
        "- ??????? API ?????????????????????/???",
        "- ???????????CPU/GPU?????????",
        f"- ????: {payload['results']['error_count']}",
    ]

    if payload["results"]["errors"]:
        lines.extend(
            [
                "",
                "## ???????30??",
                "",
                "```json",
                json.dumps(payload["results"]["errors"], ensure_ascii=False, indent=2),
                "```",
            ]
        )

    if imp.get("hits"):
        lines.extend(
            [
                "",
                "## ?????????30??",
                "",
                "```json",
                json.dumps(imp["hits"], ensure_ascii=False, indent=2),
                "```",
            ]
        )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="?? LFW ??????? API ????")
    parser.add_argument("--dataset-dir", default="data/datasets")
    parser.add_argument("--max-identities", type=int, default=30, help="<=0 ?? register-ratio ????")
    parser.add_argument("--min-images-per-identity", type=int, default=2)
    parser.add_argument("--register-ratio", type=float, default=0.8, help="? max-identities<=0 ?????????????")
    parser.add_argument("--use-all-images", action="store_true", help="?????????????????????")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--threshold", type=float, default=0.55)
    parser.add_argument("--search-top-k", type=int, default=5)
    parser.add_argument("--vector-backend", default="auto", choices=["auto", "bruteforce", "faiss", "annoy"])
    parser.add_argument("--impostor-count", type=int, default=200, help="?????????? --use-all-images ? <=0 ????????????")
    parser.add_argument("--report-dir", default="data/reports")
    parser.add_argument("--temp-root", default=None, help="??????????????????? TEMP ????")
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir).resolve()
    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    lfw_root = download_and_extract_lfw(dataset_dir)
    samples, leftovers = choose_samples(
        lfw_root,
        max_identities=args.max_identities,
        min_images_per_identity=max(2, args.min_images_per_identity),
        register_ratio=min(0.95, max(0.1, args.register_ratio)),
        use_all_images=args.use_all_images,
        seed=args.seed,
    )
    if len(samples) < 5:
        raise RuntimeError("??????????????????<5?")

    impostor_count = max(0, args.impostor_count)
    if (not args.use_all_images) and impostor_count > len(leftovers):
        print(f"?????? {impostor_count} ???????? {len(leftovers)}???? {len(leftovers)}")
        impostor_count = len(leftovers)
    impostor_attempts = choose_impostor_attempts(
        leftover_candidates=leftovers,
        victims=samples,
        impostor_count=impostor_count,
        use_all_images=args.use_all_images,
        seed=args.seed,
    )

    results = run_benchmark(
        samples,
        impostor_attempts,
        threshold=min(1.0, max(0.0, args.threshold)),
        search_top_k=max(1, args.search_top_k),
        vector_backend=args.vector_backend,
        temp_root=args.temp_root,
    )

    register_image_count = len(samples)
    genuine_probe_image_count = sum(len(s.probe_images) for s in samples)
    total_test_images = genuine_probe_image_count + len(impostor_attempts)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": {
            "name": "LFW",
            "url": LFW_URL,
            "root": str(lfw_root),
            "used_identities": len(samples),
            "impostor_attempts": len(impostor_attempts),
            "min_images_per_identity": max(2, args.min_images_per_identity),
            "use_all_images": bool(args.use_all_images),
            "register_ratio": min(0.95, max(0.1, args.register_ratio)),
            "register_image_count": register_image_count,
            "genuine_probe_image_count": genuine_probe_image_count,
            "total_test_images": total_test_images,
        },
        "results": results,
    }

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"lfw_api_benchmark_{stamp}.json"
    md_path = report_dir / f"lfw_api_benchmark_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_markdown_report(payload), encoding="utf-8")

    print("[4/4] ????")
    print(f"JSON ??: {json_path}")
    print(f"MD ??:   {md_path}")
    print(
        f"?????={results['register']['ok_rate']*100:.2f}% | "
        f"??Top1={results['search']['top1_hit_rate']*100:.2f}% | "
        f"?????={results['checkin']['ok_rate']*100:.2f}% | "
        f"?????(FAR)={results['impostor_checkin']['false_accept_rate']*100:.2f}%"
    )
    print(
        f"??(ms): register p95={results['register']['latency']['p95_ms']:.2f}, "
        f"search p95={results['search']['latency']['p95_ms']:.2f}, "
        f"checkin p95={results['checkin']['latency']['p95_ms']:.2f}"
    )


if __name__ == "__main__":
    main()
