from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["页面"])

_BASE_DIR = Path(__file__).resolve().parents[2]
_CHECKIN_UI_PATH = (_BASE_DIR / "checkin-ui-standalone.html").resolve()
_ANALYSIS_UI_PATH = (_BASE_DIR / "checkinexcel" / "test.html").resolve()
_ANALYSIS_BTN_MARKER = 'data-role="analysis-entry-btn"'


def _load_html_page(path: Path, *, page_name: str, file_name: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(errors="ignore")
    except OSError:
        return f"""
        <!doctype html>
        <html lang="zh-CN">
        <head><meta charset="utf-8" /><title>页面加载失败</title></head>
        <body>
          <h2>{page_name}加载失败</h2>
          <p>未找到 <code>{file_name}</code> 文件，请检查项目文件是否完整。</p>
        </body>
        </html>
        """


def _inject_analysis_button(html: str) -> str:
    if _ANALYSIS_BTN_MARKER in html:
        return html

    button_html = """
    <a class="analysis-entry-btn" data-role="analysis-entry-btn" href="/analysis-ui">数据分析</a>
    <style>
      .analysis-entry-btn {
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 100000;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        text-decoration: none;
        background: #0f5ef7;
        color: #fff !important;
        border: 2px solid #ffffffcc;
        border-radius: 14px;
        padding: 14px 24px;
        font-size: 18px;
        line-height: 1;
        font-weight: 800;
        letter-spacing: .5px;
        box-shadow: 0 12px 28px rgba(15, 30, 74, 0.28);
      }
      .analysis-entry-btn:hover {
        background: #0a44b7;
      }
      @media (max-width: 768px) {
        .analysis-entry-btn {
          top: 12px;
          right: 12px;
          padding: 12px 18px;
          font-size: 16px;
        }
      }
    </style>
    """

    lowered = html.lower()
    body_open_idx = lowered.find("<body")
    if body_open_idx >= 0:
        body_tag_end = html.find(">", body_open_idx)
        if body_tag_end >= 0:
            return html[: body_tag_end + 1] + button_html + html[body_tag_end + 1 :]
    return button_html + html


def _load_checkin_ui_html() -> str:
    html = _load_html_page(
        _CHECKIN_UI_PATH,
        page_name="签到页面",
        file_name="checkin-ui-standalone.html",
    )
    return _inject_analysis_button(html)


def _load_analysis_ui_html() -> str:
    html = _load_html_page(
        _ANALYSIS_UI_PATH,
        page_name="数据分析页面",
        file_name="checkinexcel/test.html",
    )
    return html.replace("http://localhost:8080/api/excel/generate", "/api/excel/generate")


@router.get("/", response_class=HTMLResponse, summary="首页", description="默认进入人脸识别签到页面。")
async def root_page():
    return _load_checkin_ui_html()


@router.get(
    "/checkin-ui",
    response_class=HTMLResponse,
    summary="签到界面",
    description="用于签到、拍照签到、历史签到记录等完整页面。",
)
async def checkin_page():
    return _load_checkin_ui_html()


@router.get(
    "/analysis-ui",
    response_class=HTMLResponse,
    summary="数据分析界面",
    description="用于查看与导出签到分析数据的页面。",
)
async def analysis_page():
    return _load_analysis_ui_html()


@router.get("/checkinexcel", response_class=HTMLResponse, include_in_schema=False)
async def analysis_page_legacy():
    return _load_analysis_ui_html()


@router.get(
    "/tester",
    response_class=HTMLResponse,
    summary="在线测试页",
    description="兼容旧入口，已切换为完整签到界面。",
)
async def tester_page():
    return _load_checkin_ui_html()
