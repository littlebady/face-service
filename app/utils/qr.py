from __future__ import annotations

import base64
import html
import io
from urllib.parse import quote


def build_qr_png_data_uri(text: str) -> str:
    payload = str(text or "").strip()
    if not payload:
        raise ValueError("二维码内容不能为空")

    try:
        import qrcode
    except Exception:
        safe = html.escape(payload[:80])
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='360' height='360'>"
            "<rect width='100%' height='100%' fill='#ffffff'/>"
            "<rect x='18' y='18' width='324' height='324' fill='#f4f7fb' stroke='#cbd5e1'/>"
            "<text x='180' y='155' text-anchor='middle' font-size='18' fill='#0f172a'>缺少 qrcode 依赖</text>"
            "<text x='180' y='188' text-anchor='middle' font-size='12' fill='#334155'>请安装 requirements.required.txt</text>"
            f"<text x='180' y='230' text-anchor='middle' font-size='11' fill='#64748b'>{safe}</text>"
            "</svg>"
        )
        return "data:image/svg+xml;charset=utf-8," + quote(svg)

    image = qrcode.make(payload)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
