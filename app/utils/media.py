from __future__ import annotations

import csv
import io
import math
from pathlib import Path
from typing import Any, Dict, List, Optional


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    earth_radius_m = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * earth_radius_m * math.asin(math.sqrt(a))


def to_media_url(path_value: Optional[str], media_root: Path) -> Optional[str]:
    if not path_value:
        return None
    try:
        relative = Path(path_value).resolve().relative_to(media_root.resolve())
    except Exception:
        return None
    return f"/media/{relative.as_posix()}"


def serialize_face(face: Dict[str, Any], media_root: Path) -> Dict[str, Any]:
    payload = dict(face)
    payload["image_url"] = to_media_url(payload.get("image_path"), media_root)
    return payload


def serialize_checkin(record: Dict[str, Any], media_root: Path) -> Dict[str, Any]:
    payload = dict(record)
    payload["capture_image_url"] = to_media_url(payload.get("capture_image_path"), media_root)
    payload["matched_image_url"] = to_media_url(payload.get("matched_image_path"), media_root)
    return payload


def build_checkins_csv(records: List[Dict[str, Any]]) -> str:
    headers = [
        "checkin_id",
        "person_name",
        "matched_face_id",
        "similarity",
        "status",
        "reason",
        "capture_image_path",
        "matched_image_path",
        "lat",
        "lng",
        "center_lat",
        "center_lng",
        "radius_m",
        "distance_m",
        "create_time",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    for item in records:
        writer.writerow({key: item.get(key) for key in headers})
    return buffer.getvalue()
