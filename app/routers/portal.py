from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse


router = APIRouter(tags=["Portal"])


@router.get("/app", include_in_schema=False)
async def app_root() -> RedirectResponse:
    return RedirectResponse(url="/app/login", status_code=307)


@router.get("/app/login", response_class=HTMLResponse, summary="Login/Register")
async def app_login_page() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>通用签到平台 - 登录</title>
  <style>
    :root {
      --bg: #ecf3ff;
      --card: #ffffff;
      --text: #172033;
      --muted: #66728a;
      --primary: #0f5fd7;
      --secondary: #0b1f44;
      --ok: #157347;
      --err: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      color: var(--text);
      background:
        radial-gradient(800px 360px at 15% 0%, #dbe9ff, transparent 70%),
        radial-gradient(900px 420px at 100% 100%, #d7f0ff, transparent 65%),
        var(--bg);
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 20px;
    }
    .shell {
      width: 100%;
      max-width: 980px;
      display: grid;
      grid-template-columns: 1.1fr 1fr;
      gap: 18px;
    }
    @media (max-width: 900px) {
      .shell { grid-template-columns: 1fr; }
    }
    .intro, .panel {
      background: var(--card);
      border-radius: 18px;
      box-shadow: 0 16px 34px rgba(16, 32, 74, 0.14);
      padding: 24px;
    }
    .intro h1 {
      margin: 0;
      font-size: 34px;
      line-height: 1.2;
    }
    .intro p {
      margin-top: 12px;
      color: var(--muted);
      line-height: 1.8;
      font-size: 14px;
    }
    .pill {
      margin-top: 14px;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: #e7f0ff;
      color: #0d4faf;
      font-size: 12px;
      font-weight: 700;
    }
    .panel h2 {
      margin: 0;
      font-size: 22px;
    }
    .sub {
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
    }
    .line {
      display: grid;
      gap: 7px;
      margin-top: 12px;
    }
    label {
      font-size: 13px;
      color: #2e3a52;
      font-weight: 600;
    }
    input {
      width: 100%;
      border: 1px solid #d2deee;
      border-radius: 11px;
      padding: 11px 12px;
      font-size: 14px;
      outline: none;
      background: #fbfdff;
    }
    input:focus {
      border-color: #93b8ff;
      box-shadow: 0 0 0 3px #e5efff;
    }
    .actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 14px;
    }
    button {
      border: 0;
      border-radius: 11px;
      padding: 11px 14px;
      font-size: 14px;
      font-weight: 700;
      color: #fff;
      cursor: pointer;
    }
    button.primary { background: var(--primary); }
    button.secondary { background: var(--secondary); }
    .msg {
      margin-top: 12px;
      min-height: 20px;
      font-size: 13px;
    }
    .msg.ok { color: var(--ok); }
    .msg.err { color: var(--err); }
    .hint {
      margin-top: 14px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.8;
      background: #f3f8ff;
      border: 1px dashed #c7d8f7;
      padding: 10px 12px;
      border-radius: 10px;
    }
    code {
      background: #eaf1ff;
      padding: 2px 6px;
      border-radius: 6px;
      font-family: Consolas, "Courier New", monospace;
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="intro">
      <h1>通用签到平台</h1>
      <p>支持任何账号发布签到，现场扫码完成签到，发布者实时查看签到状态与记录。可用于课堂、会议、活动、值班和访客登记等多种场景。</p>
      <div class="pill">默认演示账号: teacher / teacher123</div>
      <p>登录成功后进入 <code>/app/dashboard</code>。</p>
    </section>

    <section class="panel">
      <h2>登录 / 注册</h2>
      <div class="sub">若已有账号请直接登录；没有账号可一键注册并自动登录。</div>
      <div class="line">
        <label for="username">用户名</label>
        <input id="username" placeholder="例如: event_user01" />
      </div>
      <div class="line">
        <label for="password">密码</label>
        <input id="password" type="password" placeholder="至少 6 位" />
      </div>
      <div class="line">
        <label for="displayName">昵称（注册可选）</label>
        <input id="displayName" placeholder="例如: 行政组A" />
      </div>
      <div class="actions">
        <button class="primary" id="btnLogin">登录</button>
        <button class="secondary" id="btnRegister">注册并登录</button>
      </div>
      <div id="msg" class="msg"></div>
      <div class="hint">如果你直接双击启动脚本后打开的是旧页面，请手动访问 <code>/app/login</code>。</div>
    </section>
  </main>

  <script>
    const TOKEN_KEY = "face_service_token";
    const msg = document.getElementById("msg");
    const username = document.getElementById("username");
    const password = document.getElementById("password");
    const displayName = document.getElementById("displayName");

    function setMsg(text, ok) {
      msg.textContent = text || "";
      msg.className = "msg " + (ok ? "ok" : "err");
    }

    async function postJson(path, payload) {
      const resp = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || data.ok === false) {
        throw new Error(data.detail || data.reason || "请求失败");
      }
      return data;
    }

    function saveTokenAndJump(data) {
      localStorage.setItem(TOKEN_KEY, data.access_token);
      window.location.href = "/app/dashboard";
    }

    async function checkExistingToken() {
      const token = localStorage.getItem(TOKEN_KEY);
      if (!token) return;
      try {
        const resp = await fetch("/auth/me", {
          headers: { Authorization: "Bearer " + token }
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok && data.ok) {
          window.location.href = "/app/dashboard";
        }
      } catch (_) {}
    }

    document.getElementById("btnLogin").addEventListener("click", async () => {
      try {
        setMsg("正在登录...", true);
        const data = await postJson("/auth/login", {
          username: username.value.trim(),
          password: password.value
        });
        saveTokenAndJump(data);
      } catch (err) {
        setMsg(err.message || String(err), false);
      }
    });

    document.getElementById("btnRegister").addEventListener("click", async () => {
      try {
        setMsg("正在注册...", true);
        const data = await postJson("/auth/register", {
          username: username.value.trim(),
          password: password.value,
          display_name: displayName.value.trim() || null
        });
        saveTokenAndJump(data);
      } catch (err) {
        setMsg(err.message || String(err), false);
      }
    });

    checkExistingToken();
  </script>
</body>
</html>
"""


@router.get("/app/dashboard", response_class=HTMLResponse, summary="Dashboard")
async def app_dashboard_page() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>通用签到平台 - 控制台</title>
  <style>
    :root {
      --bg: #f2f7ff;
      --card: #ffffff;
      --line: #e4ebf5;
      --text: #162238;
      --muted: #64748b;
      --primary: #0f5fd7;
      --accent: #0e1f45;
      --ok: #147a47;
      --err: #b42318;
      --warn: #9a6700;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      color: var(--text);
      background:
        radial-gradient(900px 360px at 0% 0%, #dde9ff, transparent 70%),
        radial-gradient(760px 340px at 100% 100%, #d8f1ff, transparent 68%),
        var(--bg);
    }
    .page {
      max-width: 1220px;
      margin: 0 auto;
      padding: 20px 18px 30px;
    }
    .topbar {
      background: linear-gradient(120deg, #0f3f8f, #1f70e3);
      color: #fff;
      border-radius: 16px;
      padding: 18px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      box-shadow: 0 12px 28px rgba(16, 33, 75, 0.28);
    }
    .topbar h1 {
      margin: 0;
      font-size: 28px;
    }
    .topbar p {
      margin: 6px 0 0;
      opacity: .95;
      font-size: 14px;
    }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    button {
      border: 0;
      border-radius: 10px;
      padding: 10px 12px;
      font-weight: 700;
      cursor: pointer;
      font-size: 13px;
    }
    .btn-primary { background: var(--primary); color: #fff; }
    .btn-dark { background: var(--accent); color: #fff; }
    .btn-soft { background: #eaf1ff; color: #1b3f80; }
    .grid {
      margin-top: 14px;
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 12px;
    }
    .card {
      background: var(--card);
      border: 1px solid #e9eef8;
      border-radius: 14px;
      box-shadow: 0 10px 22px rgba(15, 33, 75, 0.08);
      padding: 14px;
    }
    .span-3 { grid-column: span 3; }
    .span-4 { grid-column: span 4; }
    .span-5 { grid-column: span 5; }
    .span-7 { grid-column: span 7; }
    .span-8 { grid-column: span 8; }
    .span-12 { grid-column: span 12; }
    @media (max-width: 1020px) {
      .span-3, .span-4, .span-5, .span-7, .span-8, .span-12 { grid-column: span 12; }
    }
    h2 {
      margin: 0 0 10px;
      font-size: 18px;
    }
    .metric-title { color: var(--muted); font-size: 12px; }
    .metric-val { font-size: 28px; margin-top: 4px; font-weight: 800; }
    .line {
      display: grid;
      gap: 6px;
      margin-bottom: 10px;
    }
    .line label {
      font-size: 12px;
      color: #314055;
      font-weight: 700;
    }
    input, select {
      border: 1px solid #d6e0ef;
      background: #fbfdff;
      border-radius: 10px;
      padding: 9px 10px;
      font-size: 13px;
      outline: none;
    }
    input:focus, select:focus {
      border-color: #90b4ff;
      box-shadow: 0 0 0 3px #e7f0ff;
    }
    .row2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    @media (max-width: 520px) {
      .row2 { grid-template-columns: 1fr; }
    }
    .check {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      color: #314055;
      margin-bottom: 6px;
    }
    .status {
      margin-top: 8px;
      min-height: 19px;
      font-size: 13px;
    }
    .ok { color: var(--ok); }
    .err { color: var(--err); }
    .warn { color: var(--warn); }
    .hint {
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 8px 6px;
      text-align: left;
      vertical-align: top;
    }
    th { color: #334155; background: #f8fbff; }
    .table-actions {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .table-actions button {
      padding: 6px 8px;
      border-radius: 8px;
      font-size: 12px;
    }
    .qr-panel {
      display: grid;
      gap: 8px;
      align-content: start;
    }
    .qr-panel img {
      width: 240px;
      max-width: 100%;
      border: 1px solid #d7e2f5;
      border-radius: 10px;
      background: #fff;
      padding: 8px;
    }
    .records {
      border: 1px solid #e2e9f5;
      border-radius: 10px;
      max-height: 340px;
      overflow: auto;
      padding: 8px;
      background: #fbfdff;
    }
    .record {
      padding: 8px 2px;
      border-bottom: 1px dashed #dde6f4;
      font-size: 13px;
    }
    .record:last-child { border-bottom: 0; }
    .muted { color: var(--muted); }
    .mono {
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
    }
    a { color: #0f5fd7; text-decoration: none; }
    a:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <div class="page">
    <section class="topbar">
      <div>
        <h1>签到发布控制台</h1>
        <p>所有登录用户可发布签到并查看自己发布的签到信息</p>
      </div>
      <div class="actions">
        <button class="btn-soft" id="btnRefresh">刷新</button>
        <button class="btn-soft" id="btnProfile">个人主页</button>
        <button class="btn-soft" id="btnAnalysis">数据分析</button>
        <button class="btn-dark" id="btnLogout">退出</button>
      </div>
    </section>

    <section class="grid">
      <article class="card span-3">
        <div class="metric-title">当前用户</div>
        <div class="metric-val" id="metricUser">-</div>
      </article>
      <article class="card span-3">
        <div class="metric-title">我的场景数</div>
        <div class="metric-val" id="metricCourses">0</div>
      </article>
      <article class="card span-3">
        <div class="metric-title">签到场次数</div>
        <div class="metric-val" id="metricSessions">0</div>
      </article>
      <article class="card span-3">
        <div class="metric-title">最近状态</div>
        <div class="metric-val" id="metricState">-</div>
      </article>

      <article class="card span-4">
        <h2>创建场景</h2>
        <div class="line">
          <label>场景名称</label>
          <input id="sceneName" placeholder="例如: 活动签到" value="默认场景" />
        </div>
        <div class="line">
          <label>场景编码</label>
          <input id="sceneCode" placeholder="例如: EVENT001" />
        </div>
        <button class="btn-primary" id="btnCreateScene">新增场景</button>
        <div id="sceneMsg" class="status"></div>
      </article>

      <article class="card span-8">
        <h2>发布签到</h2>
        <div class="row2">
          <div class="line">
            <label>签到场景</label>
            <select id="courseId"></select>
          </div>
          <div class="line">
            <label>签到标题</label>
            <input id="sessionTitle" value="现场签到" />
          </div>
        </div>
        <div class="row2">
          <div class="line">
            <label>有效时长(分钟)</label>
            <input id="duration" type="number" min="1" max="240" value="10" />
          </div>
          <div class="line">
            <label>识别阈值(0-1)</label>
            <input id="threshold" type="number" min="0" max="1" step="0.01" value="0.6" />
          </div>
        </div>
        <div class="row2">
          <div class="line">
            <label>TopK 候选</label>
            <input id="topK" type="number" min="1" max="5" value="1" />
          </div>
          <div class="line">
            <label>围栏半径(米)</label>
            <input id="radius" type="number" min="10" max="5000" value="200" />
          </div>
        </div>
        <div class="row2">
          <div class="line">
            <label>围栏中心纬度(可选)</label>
            <input id="centerLat" type="number" step="0.000001" />
          </div>
          <div class="line">
            <label>围栏中心经度(可选)</label>
            <input id="centerLng" type="number" step="0.000001" />
          </div>
        </div>
        <label class="check"><input id="geofenceAuto" type="checkbox" checked /> 地理围栏（自动定位发布者并填充围栏中心）</label>
        <div class="hint" id="geoHint">地理围栏已开启：将自动获取发布者定位并填入围栏中心。</div>
        <label class="check"><input id="checkOnce" type="checkbox" checked /> 每人仅可签到成功一次</label>
        <label class="check"><input id="liveCheck" type="checkbox" /> 活体签到（活体帧检测）</label>
        <label class="check"><input id="strictLiveFull" type="checkbox" /> 严格活体签到（规定动作挑战）</label>
        <button class="btn-primary" id="btnPublish">发布签到</button>
        <div class="hint">若开启地理围栏，会在发布前自动定位并作为围栏中心。</div>
        <div id="publishMsg" class="status"></div>
      </article>

      <article class="card span-4">
        <h2>签到二维码</h2>
        <div class="qr-panel" id="qrPanel">
          <div class="muted">发布签到后会显示二维码与链接</div>
        </div>
      </article>

      <article class="card span-8">
        <h2>我的签到场次</h2>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>标题</th>
              <th>状态</th>
              <th>时间范围</th>
              <th>场景</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody id="sessionBody">
            <tr><td colspan="6" class="muted">暂无数据</td></tr>
          </tbody>
        </table>
      </article>

      <article class="card span-12">
        <h2>签到记录</h2>
        <div id="recordSummary" class="muted">点击上方场次中的“记录”查看详情</div>
        <div class="records" id="recordList"></div>
      </article>
    </section>
  </div>

  <script>
    const TOKEN_KEY = "face_service_token";
    let token = localStorage.getItem(TOKEN_KEY) || "";
    let state = {
      courses: [],
      sessions: [],
    };

    function $(id) {
      return document.getElementById(id);
    }

    function setStatus(id, text, level) {
      const el = $(id);
      if (!el) return;
      el.textContent = text || "";
      el.className = "status " + (level || "");
    }

    function authHeaders(extra) {
      return Object.assign({}, extra || {}, { Authorization: "Bearer " + token });
    }

    async function api(path, options = {}) {
      const opts = Object.assign({}, options);
      opts.headers = authHeaders(opts.headers || {});
      const resp = await fetch(path, opts);
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || data.ok === false) {
        throw new Error(data.detail || data.reason || "请求失败");
      }
      return data;
    }

    function toNum(v, fallback = null) {
      if (v == null || String(v).trim() === "") return fallback;
      const n = Number(v);
      return Number.isFinite(n) ? n : fallback;
    }

    function setGeoHint(text, level) {
      const el = $("geoHint");
      if (!el) return;
      el.textContent = text || "";
      el.className = "hint " + (level || "");
    }

    function toTime(ms) {
      if (!ms) return "-";
      return new Date(Number(ms)).toLocaleString();
    }

    function escapeHtml(text) {
      const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
      return String(text || "").replace(/[&<>"']/g, (m) => map[m]);
    }

    async function loadMe() {
      const data = await api("/auth/me");
      const user = data.user || {};
      $("metricUser").textContent = user.display_name || user.username || "-";
      return user;
    }

    async function loadCourses() {
      const data = await api("/attendance/courses/mine");
      state.courses = data.courses || [];
      $("metricCourses").textContent = String(state.courses.length);
      const select = $("courseId");
      select.innerHTML = "";
      if (!state.courses.length) {
        select.innerHTML = '<option value="">请先创建场景</option>';
        return;
      }
      for (const course of state.courses) {
        const opt = document.createElement("option");
        opt.value = String(course.course_id);
        opt.textContent = `${course.course_name} (${course.course_code})`;
        select.appendChild(opt);
      }
    }

    function renderSessions() {
      const body = $("sessionBody");
      const sessions = state.sessions;
      $("metricSessions").textContent = String(sessions.length);
      $("metricState").textContent = sessions.length ? (sessions[0].live_status || "-") : "-";
      if (!sessions.length) {
        body.innerHTML = '<tr><td colspan="6" class="muted">暂无签到场次</td></tr>';
        return;
      }
      body.innerHTML = sessions.map((s) => `
        <tr>
          <td>${s.session_id}</td>
          <td>${escapeHtml(s.title)}</td>
          <td>${escapeHtml(s.live_status || "-")}</td>
          <td>${escapeHtml(toTime(s.start_time_ms))}<br/><span class="muted">${escapeHtml(toTime(s.end_time_ms))}</span></td>
          <td>${escapeHtml(s.course_name || "-")}</td>
          <td>
            <div class="table-actions">
              <button class="btn-soft" data-action="qr" data-token="${escapeHtml(s.qr_token)}">二维码</button>
              <button class="btn-soft" data-action="records" data-id="${s.session_id}">记录</button>
              <button class="btn-soft" data-action="copy" data-link="${escapeHtml(s.student_checkin_url || "")}">复制链接</button>
              <button class="btn-dark" data-action="close" data-id="${s.session_id}">结束</button>
            </div>
          </td>
        </tr>
      `).join("");
    }

    async function loadSessions() {
      const data = await api("/attendance/sessions?limit=50");
      state.sessions = data.sessions || [];
      renderSessions();
    }

    async function refreshAll() {
      await loadCourses();
      await loadSessions();
    }

    async function createScene() {
      const payload = {
        course_name: $("sceneName").value.trim(),
        course_code: $("sceneCode").value.trim() || ("SCENE" + Date.now()),
      };
      await api("/attendance/courses", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setStatus("sceneMsg", "场景创建成功", "ok");
      await refreshAll();
    }

    async function autoFillPublisherLocation(force = false) {
      const currLat = toNum($("centerLat").value, null);
      const currLng = toNum($("centerLng").value, null);
      if (!force && currLat != null && currLng != null) {
        setGeoHint("已使用当前围栏坐标。若要刷新定位，可清空后重新发布。", "ok");
        return { lat: currLat, lng: currLng, reused: true };
      }
      if (!navigator.geolocation) {
        throw new Error("当前浏览器不支持定位，无法自动填充围栏中心");
      }

      setGeoHint("正在获取发布者定位...", "warn");
      const position = await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 10000,
          maximumAge: 10000,
        });
      });
      const lat = Number(position.coords.latitude);
      const lng = Number(position.coords.longitude);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        throw new Error("定位结果无效，请检查浏览器定位权限");
      }
      $("centerLat").value = lat.toFixed(6);
      $("centerLng").value = lng.toFixed(6);
      setGeoHint(`定位成功：${lat.toFixed(6)}, ${lng.toFixed(6)}（已自动填入围栏中心）`, "ok");
      return { lat, lng, reused: false };
    }

    async function publishSession() {
      const strictFull = !!$("strictLiveFull").checked;
      const strictSimple = !!$("liveCheck").checked;
      const geofenceAuto = !!$("geofenceAuto").checked;

      if (geofenceAuto) {
        try {
          await autoFillPublisherLocation(true);
        } catch (err) {
          setStatus("publishMsg", "地理围栏已开启，但自动定位失败，请允许定位权限后重试", "err");
          throw err;
        }
      } else {
        setGeoHint("地理围栏未开启：本场次不做地理位置校验。", "warn");
      }

      const centerLat = toNum($("centerLat").value, null);
      const centerLng = toNum($("centerLng").value, null);
      const geofenceEnabled = geofenceAuto;
      if (geofenceEnabled && (centerLat == null || centerLng == null)) {
        throw new Error("地理围栏已开启，但围栏中心坐标为空");
      }

      const payload = {
        course_id: toNum($("courseId").value, null),
        title: $("sessionTitle").value.trim() || "现场签到",
        duration_minutes: toNum($("duration").value, 10),
        face_threshold: toNum($("threshold").value, 0.6),
        top_k: toNum($("topK").value, 1),
        geofence_enabled: geofenceEnabled,
        center_lat: geofenceEnabled ? centerLat : null,
        center_lng: geofenceEnabled ? centerLng : null,
        radius_m: toNum($("radius").value, 200),
        strict_liveness_required: strictSimple || strictFull,
        strict_liveness_full_actions: strictFull,
        checkin_once: !!$("checkOnce").checked,
      };

      const data = await api("/attendance/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setStatus("publishMsg", "签到发布成功", "ok");
      showQrData(data.qr_data_uri, data.session.student_checkin_url);
      await loadSessions();
    }

    function showQrData(qrDataUri, link) {
      $("qrPanel").innerHTML = `
        <img src="${escapeHtml(qrDataUri)}" alt="签到二维码" />
        <a class="mono" href="${escapeHtml(link)}" target="_blank">${escapeHtml(link)}</a>
        <div class="muted">请让签到人员扫码或点击链接进入签到页。</div>
      `;
    }

    async function showQrByToken(tokenValue) {
      const data = await api("/attendance/public/" + encodeURIComponent(tokenValue) + "/qr");
      showQrData(data.qr_data_uri, data.student_checkin_url);
    }

    async function viewRecords(sessionId) {
      const data = await api("/attendance/sessions/" + sessionId + "/records?limit=500");
      const summary = data.summary || {};
      $("recordSummary").textContent =
        `总记录 ${summary.total_records || 0}，成功唯一人数 ${summary.unique_success_count || 0}，状态分布 ${JSON.stringify(summary.status_counts || {})}`;
      const records = data.records || [];
      if (!records.length) {
        $("recordList").innerHTML = '<div class="muted">暂无记录</div>';
        return;
      }
      $("recordList").innerHTML = records.map((r) => `
        <div class="record">
          <div><b>${escapeHtml(r.person_name || "未识别")}</b> / ${escapeHtml(r.status || "-")} / 相似度: ${r.similarity == null ? "-" : Number(r.similarity).toFixed(4)}</div>
          <div class="muted">${escapeHtml(r.reason || "-")} | ${escapeHtml(r.create_time || "")}</div>
        </div>
      `).join("");
    }

    async function closeSession(sessionId) {
      if (!confirm("确认结束这个签到场次吗？")) return;
      await api("/attendance/sessions/" + sessionId + "/close", { method: "POST" });
      await loadSessions();
    }

    async function copyText(text) {
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        alert("已复制签到链接");
      } catch (_) {
        alert("复制失败，请手动复制");
      }
    }

    $("sessionBody").addEventListener("click", async (ev) => {
      const target = ev.target.closest("button[data-action]");
      if (!target) return;
      const action = target.getAttribute("data-action");
      try {
        if (action === "qr") await showQrByToken(target.getAttribute("data-token") || "");
        if (action === "records") await viewRecords(Number(target.getAttribute("data-id")));
        if (action === "copy") await copyText(target.getAttribute("data-link") || "");
        if (action === "close") await closeSession(Number(target.getAttribute("data-id")));
      } catch (err) {
        alert(err.message || String(err));
      }
    });

    $("btnCreateScene").addEventListener("click", async () => {
      try {
        await createScene();
      } catch (err) {
        setStatus("sceneMsg", err.message || String(err), "err");
      }
    });

    $("btnPublish").addEventListener("click", async () => {
      try {
        await publishSession();
      } catch (err) {
        setStatus("publishMsg", err.message || String(err), "err");
      }
    });

    $("geofenceAuto").addEventListener("change", async () => {
      if ($("geofenceAuto").checked) {
        try {
          await autoFillPublisherLocation(true);
        } catch (err) {
          setGeoHint("自动定位失败：请检查定位权限，发布前会再次尝试。", "warn");
        }
      } else {
        $("centerLat").value = "";
        $("centerLng").value = "";
        setGeoHint("地理围栏已关闭，本场次不校验签到位置。", "warn");
      }
    });

    $("strictLiveFull").addEventListener("change", () => {
      if ($("strictLiveFull").checked) {
        $("liveCheck").checked = true;
      }
    });

    $("liveCheck").addEventListener("change", () => {
      if (!$("liveCheck").checked) {
        $("strictLiveFull").checked = false;
      }
    });

    $("btnRefresh").addEventListener("click", async () => {
      try {
        await refreshAll();
      } catch (err) {
        alert(err.message || String(err));
      }
    });

    $("btnAnalysis").addEventListener("click", () => {
      window.location.href = "/analysis-ui";
    });

    $("btnProfile").addEventListener("click", () => {
      window.location.href = "/app/profile";
    });

    $("btnLogout").addEventListener("click", async () => {
      try {
        await api("/auth/logout", { method: "POST" });
      } catch (_) {}
      localStorage.removeItem(TOKEN_KEY);
      window.location.href = "/app/login";
    });

    async function init() {
      if (!token) {
        window.location.href = "/app/login";
        return;
      }
      try {
        await loadMe();
        try {
          if ($("geofenceAuto").checked) {
            await autoFillPublisherLocation(false);
          } else {
            setGeoHint("地理围栏未开启：本场次不校验签到位置。", "warn");
          }
        } catch (err) {
          setGeoHint("自动定位未完成：发布前会再次尝试获取定位。", "warn");
        }
        await refreshAll();
      } catch (err) {
        localStorage.removeItem(TOKEN_KEY);
        alert(err.message || String(err));
        window.location.href = "/app/login";
      }
    }

    init();
  </script>
</body>
</html>
"""


@router.get("/app/profile", response_class=HTMLResponse, summary="Profile")
async def app_profile_page() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>个人主页</title>
  <style>
    :root {
      --bg: #f2f7ff;
      --card: #ffffff;
      --line: #e4ebf5;
      --text: #162238;
      --muted: #64748b;
      --primary: #0f5fd7;
      --accent: #0e1f45;
      --ok: #157347;
      --err: #b42318;
      --warn: #9a6700;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      color: var(--text);
      background:
        radial-gradient(900px 360px at 0% 0%, #dde9ff, transparent 70%),
        radial-gradient(760px 340px at 100% 100%, #d8f1ff, transparent 68%),
        var(--bg);
    }
    .page {
      max-width: 1120px;
      margin: 0 auto;
      padding: 20px 18px 30px;
    }
    .topbar {
      background: linear-gradient(120deg, #0f3f8f, #1f70e3);
      color: #fff;
      border-radius: 16px;
      padding: 18px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      box-shadow: 0 12px 28px rgba(16, 33, 75, 0.28);
    }
    .topbar h1 {
      margin: 0;
      font-size: 28px;
    }
    .topbar p {
      margin: 6px 0 0;
      opacity: .95;
      font-size: 14px;
    }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    button {
      border: 0;
      border-radius: 10px;
      padding: 10px 12px;
      font-weight: 700;
      cursor: pointer;
      font-size: 13px;
    }
    .btn-primary { background: var(--primary); color: #fff; }
    .btn-dark { background: var(--accent); color: #fff; }
    .btn-soft { background: #eaf1ff; color: #1b3f80; }
    .grid {
      margin-top: 14px;
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 12px;
    }
    .card {
      background: var(--card);
      border: 1px solid #e9eef8;
      border-radius: 14px;
      box-shadow: 0 10px 22px rgba(15, 33, 75, 0.08);
      padding: 14px;
    }
    .span-5 { grid-column: span 5; }
    .span-7 { grid-column: span 7; }
    .span-12 { grid-column: span 12; }
    @media (max-width: 980px) {
      .span-5, .span-7, .span-12 { grid-column: span 12; }
    }
    h2 {
      margin: 0 0 10px;
      font-size: 18px;
    }
    .line {
      display: grid;
      gap: 6px;
      margin-bottom: 10px;
    }
    .line label {
      font-size: 12px;
      color: #314055;
      font-weight: 700;
    }
    input {
      border: 1px solid #d6e0ef;
      background: #fbfdff;
      border-radius: 10px;
      padding: 9px 10px;
      font-size: 13px;
      outline: none;
      width: 100%;
    }
    input:focus {
      border-color: #90b4ff;
      box-shadow: 0 0 0 3px #e7f0ff;
    }
    .info-grid {
      display: grid;
      grid-template-columns: 130px 1fr;
      gap: 10px;
      margin-top: 6px;
      font-size: 13px;
    }
    .info-grid .k { color: var(--muted); }
    .status {
      margin-top: 8px;
      min-height: 19px;
      font-size: 13px;
    }
    .ok { color: var(--ok); }
    .err { color: var(--err); }
    .warn { color: var(--warn); }
    .hint {
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }
    .preview-wrap {
      display: grid;
      grid-template-columns: 1fr 220px;
      gap: 12px;
      align-items: start;
    }
    @media (max-width: 820px) {
      .preview-wrap { grid-template-columns: 1fr; }
    }
    video {
      width: 100%;
      min-height: 280px;
      background: #0b162f;
      border-radius: 10px;
    }
    canvas { display: none; }
    .preview-box {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      background: #fbfdff;
    }
    .preview-box img {
      width: 100%;
      border-radius: 8px;
      border: 1px solid #d9e4f6;
    }
    .mono {
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
      word-break: break-all;
    }
    .actions-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="topbar">
      <div>
        <h1>个人主页</h1>
        <p>在这里维护昵称、查看用户ID，并注册专属签到人脸</p>
      </div>
      <div class="actions">
        <button class="btn-soft" id="btnBack">返回控制台</button>
        <button class="btn-dark" id="btnLogout">退出</button>
      </div>
    </section>

    <section class="grid">
      <article class="card span-5">
        <h2>基础信息</h2>
        <div class="info-grid">
          <div class="k">用户ID</div><div class="mono" id="infoUserId">-</div>
          <div class="k">账号</div><div id="infoUsername">-</div>
          <div class="k">角色</div><div id="infoRole">-</div>
          <div class="k">注册时间</div><div id="infoCreateTime">-</div>
          <div class="k">人脸状态</div><div id="infoFaceState">未注册</div>
        </div>
      </article>

      <article class="card span-7">
        <h2>昵称设置</h2>
        <div class="line">
          <label for="displayName">昵称</label>
          <input id="displayName" maxlength="64" placeholder="请输入昵称" />
        </div>
        <button class="btn-primary" id="btnSaveName">保存昵称</button>
        <div class="hint">提示：签到记录展示昵称；每个用户有唯一用户ID，不会因改昵称变化。</div>
        <div class="status" id="nameStatus"></div>
      </article>

      <article class="card span-12">
        <h2>注册人脸（签到前必需）</h2>
        <div class="preview-wrap">
          <div>
            <video id="video" autoplay playsinline></video>
            <canvas id="canvas"></canvas>
            <div class="actions-row">
              <button class="btn-primary" id="btnOpenCamera">打开摄像头</button>
              <button class="btn-dark" id="btnCaptureRegister">拍照并注册</button>
              <label class="btn-soft" style="display:inline-flex;align-items:center;cursor:pointer;">
                上传图片注册
                <input id="fileInput" type="file" accept="image/*" style="display:none;" />
              </label>
            </div>
            <div class="hint">将替换你之前注册的人脸，建议使用正脸清晰照片。</div>
            <div class="status" id="faceStatus"></div>
          </div>
          <aside class="preview-box">
            <div style="font-weight:700;margin-bottom:8px;">当前人脸</div>
            <img id="facePreview" alt="当前人脸" src="" style="display:none;" />
            <div id="faceEmpty" class="hint">暂无已注册人脸</div>
          </aside>
        </div>
      </article>
    </section>
  </div>

  <script>
    const TOKEN_KEY = "face_service_token";
    const token = localStorage.getItem(TOKEN_KEY) || "";
    let profile = null;
    let stream = null;

    function $(id) { return document.getElementById(id); }

    function setStatus(id, text, level) {
      const el = $(id);
      if (!el) return;
      el.textContent = text || "";
      el.className = "status " + (level || "");
    }

    function toTime(value) {
      if (!value) return "-";
      const t = Date.parse(value);
      if (!Number.isNaN(t)) return new Date(t).toLocaleString();
      const n = Number(value);
      if (Number.isFinite(n)) return new Date(n).toLocaleString();
      return String(value);
    }

    async function authFetch(path, options = {}) {
      const opts = Object.assign({}, options);
      opts.headers = Object.assign({}, opts.headers || {}, { Authorization: "Bearer " + token });
      const resp = await fetch(path, opts);
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || data.ok === false) {
        throw new Error(data.detail || data.reason || "请求失败");
      }
      return data;
    }

    function renderProfile() {
      if (!profile) return;
      $("infoUserId").textContent = String(profile.user_id || "-");
      $("infoUsername").textContent = profile.username || "-";
      $("infoRole").textContent = profile.role || "-";
      $("infoCreateTime").textContent = toTime(profile.create_time);
      $("displayName").value = profile.display_name || "";
      $("infoFaceState").textContent = profile.has_face ? `已注册 (${profile.face_count})` : "未注册";
      const face = profile.latest_face || null;
      if (face && face.image_url) {
        $("facePreview").src = face.image_url;
        $("facePreview").style.display = "block";
        $("faceEmpty").style.display = "none";
      } else {
        $("facePreview").style.display = "none";
        $("faceEmpty").style.display = "block";
      }
    }

    async function loadProfile() {
      const data = await authFetch("/auth/profile");
      profile = data.profile || null;
      renderProfile();
    }

    async function saveName() {
      const name = $("displayName").value.trim();
      if (!name) {
        setStatus("nameStatus", "昵称不能为空", "err");
        return;
      }
      setStatus("nameStatus", "正在保存昵称...", "ok");
      await authFetch("/auth/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: name }),
      });
      setStatus("nameStatus", "昵称保存成功", "ok");
      await loadProfile();
    }

    async function openCamera() {
      if (stream) return;
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("当前环境不支持摄像头，请改用系统浏览器或上传图片注册");
      }
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user" },
        audio: false,
      });
      $("video").srcObject = stream;
    }

    async function captureBlob() {
      if (!stream) {
        await openCamera();
      }
      const video = $("video");
      const canvas = $("canvas");
      const width = video.videoWidth || 640;
      const height = video.videoHeight || 480;
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(video, 0, 0, width, height);
      return await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
    }

    async function registerByBlob(blob, filename) {
      if (!blob) throw new Error("图像获取失败，请重试");
      const form = new FormData();
      form.append("file", blob, filename || "profile.jpg");
      setStatus("faceStatus", "正在注册人脸...", "ok");
      const data = await authFetch("/auth/profile/face/register", {
        method: "POST",
        body: form,
      });
      setStatus("faceStatus", `注册成功，已更新专属人脸（face_id=${data.face_id}）`, "ok");
      await loadProfile();
    }

    $("btnBack").addEventListener("click", () => {
      window.location.href = "/app/dashboard";
    });

    $("btnLogout").addEventListener("click", async () => {
      try {
        await authFetch("/auth/logout", { method: "POST" });
      } catch (_) {}
      localStorage.removeItem(TOKEN_KEY);
      window.location.href = "/app/login";
    });

    $("btnSaveName").addEventListener("click", async () => {
      try {
        await saveName();
      } catch (err) {
        setStatus("nameStatus", err.message || String(err), "err");
      }
    });

    $("btnOpenCamera").addEventListener("click", async () => {
      try {
        await openCamera();
        setStatus("faceStatus", "摄像头已就绪，可以拍照注册", "ok");
      } catch (err) {
        setStatus("faceStatus", err.message || String(err), "err");
      }
    });

    $("btnCaptureRegister").addEventListener("click", async () => {
      try {
        const blob = await captureBlob();
        await registerByBlob(blob, "profile_camera.jpg");
      } catch (err) {
        setStatus("faceStatus", err.message || String(err), "err");
      }
    });

    $("fileInput").addEventListener("change", async (ev) => {
      const file = ev.target.files && ev.target.files[0];
      if (!file) return;
      try {
        await registerByBlob(file, file.name || "profile_upload.jpg");
      } catch (err) {
        setStatus("faceStatus", err.message || String(err), "err");
      } finally {
        ev.target.value = "";
      }
    });

    async function init() {
      if (!token) {
        window.location.href = "/app/login";
        return;
      }
      try {
        await loadProfile();
      } catch (err) {
        localStorage.removeItem(TOKEN_KEY);
        alert(err.message || String(err));
        window.location.href = "/app/login";
      }
    }

    init();
  </script>
</body>
</html>
"""


@router.get("/s/{token}", response_class=HTMLResponse, summary="Scan Check-in Page")
async def scan_checkin_page(token: str) -> str:
    token_json = json.dumps(token, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>扫码签到</title>
  <style>
    :root {{
      --bg: #eef4ff;
      --card: #ffffff;
      --text: #152238;
      --muted: #64748b;
      --primary: #0f5fd7;
      --dark: #0e1f45;
      --ok: #157347;
      --err: #b42318;
      --warn: #9a6700;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      color: var(--text);
      background:
        radial-gradient(780px 320px at 0% 0%, #dae8ff, transparent 70%),
        radial-gradient(620px 300px at 100% 100%, #d8f4ff, transparent 65%),
        var(--bg);
    }}
    .page {{
      max-width: 860px;
      margin: 0 auto;
      padding: 14px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid #e3eaf6;
      border-radius: 14px;
      box-shadow: 0 12px 24px rgba(13, 31, 68, 0.08);
      padding: 14px;
      margin-bottom: 12px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 24px;
    }}
    .muted {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.7;
    }}
    .status {{
      margin-top: 8px;
      min-height: 19px;
      font-size: 13px;
    }}
    .ok {{ color: var(--ok); }}
    .err {{ color: var(--err); }}
    .warn {{ color: var(--warn); }}
    video {{
      width: 100%;
      min-height: 260px;
      background: #0b162f;
      border-radius: 10px;
      transform: scaleX(-1);
      transform-origin: center;
    }}
    canvas {{
      display: none;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}
    button {{
      border: 0;
      border-radius: 10px;
      padding: 10px 13px;
      cursor: pointer;
      font-weight: 700;
      color: #fff;
      font-size: 13px;
    }}
    .btn-primary {{ background: var(--primary); }}
    .btn-dark {{ background: var(--dark); }}
    .btn-soft {{
      background: #eaf1ff;
      color: #1a3f82;
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="card">
      <h1>扫码签到</h1>
      <div id="sessionInfo" class="muted">正在加载签到场次信息...</div>
      <div id="sessionStatus" class="status"></div>
    </section>

    <section class="card">
      <video id="video" autoplay playsinline></video>
      <canvas id="canvas"></canvas>
      <div class="actions">
        <button class="btn-primary" id="btnCamera">打开摄像头</button>
        <button class="btn-soft" id="btnLocate">获取定位</button>
        <button class="btn-soft" id="btnLiveness" style="display:none;">开始活体检测</button>
        <button class="btn-dark" id="btnSubmit">拍照并签到</button>
      </div>
      <div id="locationText" class="muted">定位：未获取</div>
      <div id="livenessStatus" class="status"></div>
      <div id="submitStatus" class="status"></div>
    </section>
  </main>

  <script>
    const token = {token_json};
    const MEDIAPIPE_VERSION = "20260427_1";
    const LIVE_LEFT_EYE = [33, 160, 158, 133, 153, 144];
    const LIVE_RIGHT_EYE = [362, 385, 387, 263, 373, 380];
    const LIVE_LEFT_EYE_CORNER = 33;
    const LIVE_RIGHT_EYE_CORNER = 263;
    const LIVE_NOSE = 1;
    const LIVE_UPPER_LIP = 13;
    const LIVE_LOWER_LIP = 14;
    const LIVE_LEFT_MOUTH_CORNER = 78;
    const LIVE_RIGHT_MOUTH_CORNER = 308;

    const LIVE_CALIBRATION_FRAMES = 20;
    const LIVE_STEP_TIMEOUT_MS = 9000;
    const LIVE_TOTAL_TIMEOUT_MS = 65000;
    const LIVE_MIN_TOTAL_MS = 4800;
    const LIVE_NEUTRAL_FRAMES = 5;
    const LIVE_NEUTRAL_YAW_ABS = 0.05;
    const LIVE_CLOSE_EAR_FACTOR = 0.72;
    const LIVE_OPEN_EAR_FACTOR = 0.9;
    const LIVE_STRICT_FREEZE_FRAMES = 24;
    const LIVE_STRICT_MAX_MISSING_FRAMES = 16;
    const LIVE_STRICT_TURN_MAX_MISSING_FRAMES = 36;
    const LIVE_STRICT_TURN_MISSING_GRACE_MS = 1400;
    const LIVE_STRICT_TURN_TIMEOUT_COMPENSATE_MAX_MS = 2200;
    const LIVE_STRICT_FREEZE_DELTA = 0.0016;
    const LIVE_ENGINE_WARMUP_FRAMES = 3;
    const LIVE_ENGINE_SEND_MAX_RETRY = 3;
    const LIVE_ENGINE_REINIT_MAX_RETRY = 1;
    const LIVE_ERROR_STATUS_HOLD_MS = 15000;
    const LIVE_MOVE_CLOSER_GAIN_RATIO = 1.055;
    const LIVE_MOVE_CLOSER_GAIN_ABS = 0.0045;
    const LIVE_MOVE_CLOSER_HOLD_FRAMES = 2;

    let session = null;
    let stream = null;
    const scriptPromises = {{}};
    let livenessLoopToken = 0;
    let locationData = {{ lat: null, lng: null }};
    const livenessState = {{
      running: false,
      passed: false,
      failReason: "",
      calibrating: false,
      calibrationFrames: 0,
      challengeActions: [],
      challengeIndex: 0,
      completedActions: [],
      totalStartedAt: 0,
      stepStartedAt: 0,
      waitingNeutral: false,
      neutralFrames: 0,
      stepData: {{}},
      blinkCount: 0,
      earBaseline: 0,
      earSampleCount: 0,
      yawBaseline: 0,
      yawSampleCount: 0,
      mouthBaseline: 0,
      mouthSampleCount: 0,
      faceScaleBaseline: 0,
      faceScaleSampleCount: 0,
      currentEar: 0,
      currentYaw: 0,
      currentMouth: 0,
      currentScale: 0,
      challengeId: "",
      challengeNonce: "",
      challengeExpiresAt: 0,
      missingFrames: 0,
      missingSinceAt: 0,
      missingActionAtStart: "",
      lastFaceDetectedAt: 0,
      motionAccumulator: 0,
      motionSamples: 0,
      freezeRun: 0,
      maxFreezeRun: 0,
      lastNoseX: null,
      lastNoseY: null,
      lastYaw: null,
      yawMin: null,
      yawMax: null,
      mouthPeak: 0,
      scalePeak: 0,
      turnLeftSign: 1,
      turnActionCount: 0,
      turnDirectionCalibrated: false,
      engineSendErrorCount: 0,
      engineReinitCount: 0,
      engineWarmupFrames: 0,
      engineLiteMode: false,
      lastEngineError: "",
      livenessStatusLockUntil: 0,
      engineReady: false,
      engine: null,
      ticket: "",
      ticketExpiresAt: 0,
      keyBlob: null,
      challenge: null,
      proof: null,
    }};
    const video = document.getElementById("video");
    const canvas = document.getElementById("canvas");
    const btnLiveness = document.getElementById("btnLiveness");

    function setStatus(id, text, level) {{
      const el = document.getElementById(id);
      el.textContent = text || "";
      el.className = "status " + (level || "");
    }}

    function setLivenessErrorStatus(text, holdMs) {{
      const ms = Math.max(1500, Number(holdMs) || LIVE_ERROR_STATUS_HOLD_MS);
      livenessState.livenessStatusLockUntil = Date.now() + ms;
      setStatus("livenessStatus", text || "活体检测失败，请重试", "err");
    }}

    function isLivenessStatusLocked() {{
      return Date.now() < Number(livenessState.livenessStatusLockUntil || 0);
    }}

    function setText(id, text) {{
      const el = document.getElementById(id);
      el.textContent = text || "";
    }}

    function toTime(ms) {{
      if (!ms) return "-";
      return new Date(Number(ms)).toLocaleString();
    }}

    function sleep(ms) {{
      return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms) || 0)));
    }}

    function formatActions(actions) {{
      const names = {{
        blink: "眨眼",
        turn_left: "向左转头",
        turn_right: "向右转头",
        mouth_open: "张嘴",
        move_closer: "靠近镜头",
      }};
      const arr = Array.isArray(actions) ? actions : [];
      return arr.map((item) => names[item] || item).join(" -> ");
    }}

    function actionName(action) {{
      const names = {{
        blink: "眨眼",
        turn_left: "向左转头",
        turn_right: "向右转头",
        mouth_open: "张嘴",
        move_closer: "靠近镜头",
      }};
      return names[action] || String(action || "-");
    }}

    function actionPrompt(action) {{
      const names = {{
        blink: "请快速眨眼一次",
        turn_left: "请向你自己的左侧转头",
        turn_right: "请向你自己的右侧转头",
        mouth_open: "请张嘴后再闭合",
        move_closer: "请向前靠近镜头一点",
      }};
      return names[action] || ("请完成动作: " + actionName(action));
    }}

    function isTurnAction(action) {{
      return action === "turn_left" || action === "turn_right";
    }}

    function loadScriptOnce(src) {{
      if (scriptPromises[src]) return scriptPromises[src];
      scriptPromises[src] = new Promise((resolve, reject) => {{
        const script = document.createElement("script");
        script.src = src;
        script.async = true;
        script.onload = () => resolve();
        script.onerror = () => reject(new Error("活体模块加载失败: " + src));
        document.head.appendChild(script);
      }});
      return scriptPromises[src];
    }}

    function mediapipeBaseUrl() {{
      return "/static/mediapipe";
    }}

    async function ensureMediapipeLoaded() {{
      if (typeof FaceMesh === "function") return;
      const base = mediapipeBaseUrl();
      await loadScriptOnce(base + "/camera_utils/camera_utils.js?v=" + MEDIAPIPE_VERSION);
      await loadScriptOnce(base + "/face_mesh/face_mesh.js?v=" + MEDIAPIPE_VERSION);
      if (typeof FaceMesh !== "function") {{
        throw new Error("活体模块加载失败，请刷新页面后重试");
      }}
    }}

    async function ensureLivenessEngine() {{
      await ensureMediapipeLoaded();
      if (livenessState.engineReady && livenessState.engine) return;
      const base = mediapipeBaseUrl();
      const mesh = new FaceMesh({{
        locateFile: (file) => {{
          let resolved = String(file || "");
          if (resolved.includes("simd_wasm_bin")) {{
            resolved = resolved.replace("simd_wasm_bin", "wasm_bin");
          }}
          return base + "/face_mesh/" + resolved + "?v=" + MEDIAPIPE_VERSION;
        }},
      }});
      mesh.setOptions({{
        maxNumFaces: 1,
        // 兼容模式下关闭 refineLandmarks 可显著降低机型兼容压力
        refineLandmarks: !livenessState.engineLiteMode,
        minDetectionConfidence: 0.5,
        minTrackingConfidence: 0.5,
      }});
      mesh.onResults(onLivenessResults);
      livenessState.engine = mesh;
      livenessState.engineReady = true;
    }}

    function isWechatBrowser() {{
      try {{
        return String((navigator && navigator.userAgent) || "").toLowerCase().includes("micromessenger");
      }} catch (err) {{
        return false;
      }}
    }}

    function isIOSWebkit() {{
      try {{
        const ua = String((navigator && navigator.userAgent) || "").toLowerCase();
        const isiOS = /iphone|ipad|ipod/.test(ua);
        const isAppleDesktop = /macintosh/.test(ua) && "ontouchend" in document;
        return isiOS || isAppleDesktop;
      }} catch (err) {{
        return false;
      }}
    }}

    function hasWebGLSupport() {{
      try {{
        const probe = document.createElement("canvas");
        const gl = probe.getContext("webgl2") || probe.getContext("webgl") || probe.getContext("experimental-webgl");
        return !!gl;
      }} catch (err) {{
        return false;
      }}
    }}

    function describeLivenessEngineError(err) {{
      const msg = String((err && err.message) || err || "");
      const lower = msg.toLowerCase();
      const snippet = msg.replace(/\\s+/g, " ").slice(0, 120);
      if (!msg) {{
        return "活体检测引擎运行失败，请刷新后重试";
      }}
      if (
        lower.includes("webgl")
        || lower.includes("contextlost")
        || lower.includes("gpu")
        || lower.includes("createcontext")
        || lower.includes("teximage2d")
      ) {{
        const openTip = isWechatBrowser() ? "请点右上角在系统浏览器打开后重试" : "请更换最新版系统浏览器后重试";
        return "浏览器图形能力不足（WebGL/GPU），活体引擎无法运行，" + openTip;
      }}
      if (lower.includes("webassembly") || lower.includes("wasm")) {{
        const openTip = isWechatBrowser() ? "请点右上角在系统浏览器打开后重试" : "请升级浏览器后重试";
        return "活体引擎加载失败（WebAssembly），" + openTip + (snippet ? ("；详情：" + snippet) : "");
      }}
      if (lower.includes("memory")) {{
        return "活体引擎可用内存不足，请关闭后台应用后重试";
      }}
      if (lower.includes("network") || lower.includes("fetch")) {{
        return "活体模型资源加载失败，请检查网络后重试";
      }}
      return snippet
        ? ("活体检测引擎运行失败：" + snippet)
        : "活体检测引擎运行失败，请刷新后重试";
    }}

    function resetLivenessMotionState() {{
      livenessState.passed = false;
      livenessState.failReason = "";
      livenessState.calibrating = false;
      livenessState.calibrationFrames = 0;
      livenessState.challengeActions = [];
      livenessState.challengeIndex = 0;
      livenessState.completedActions = [];
      livenessState.totalStartedAt = 0;
      livenessState.stepStartedAt = 0;
      livenessState.waitingNeutral = false;
      livenessState.neutralFrames = 0;
      livenessState.stepData = {{}};
      livenessState.blinkCount = 0;
      livenessState.earBaseline = 0;
      livenessState.earSampleCount = 0;
      livenessState.yawBaseline = 0;
      livenessState.yawSampleCount = 0;
      livenessState.mouthBaseline = 0;
      livenessState.mouthSampleCount = 0;
      livenessState.faceScaleBaseline = 0;
      livenessState.faceScaleSampleCount = 0;
      livenessState.currentEar = 0;
      livenessState.currentYaw = 0;
      livenessState.currentMouth = 0;
      livenessState.currentScale = 0;
      livenessState.challengeId = "";
      livenessState.challengeNonce = "";
      livenessState.challengeExpiresAt = 0;
      livenessState.missingFrames = 0;
      livenessState.missingSinceAt = 0;
      livenessState.missingActionAtStart = "";
      livenessState.lastFaceDetectedAt = 0;
      livenessState.motionAccumulator = 0;
      livenessState.motionSamples = 0;
      livenessState.freezeRun = 0;
      livenessState.maxFreezeRun = 0;
      livenessState.lastNoseX = null;
      livenessState.lastNoseY = null;
      livenessState.lastYaw = null;
      livenessState.yawMin = null;
      livenessState.yawMax = null;
      livenessState.mouthPeak = 0;
      livenessState.scalePeak = 0;
      livenessState.turnLeftSign = 1;
      livenessState.turnActionCount = 0;
      livenessState.turnDirectionCalibrated = false;
      livenessState.engineSendErrorCount = 0;
      livenessState.engineReinitCount = 0;
      livenessState.engineWarmupFrames = 0;
      livenessState.lastEngineError = "";
      livenessState.livenessStatusLockUntil = 0;
    }}

    function liveDistance(a, b) {{
      if (!a || !b) return 0;
      const dx = Number(a.x || 0) - Number(b.x || 0);
      const dy = Number(a.y || 0) - Number(b.y || 0);
      return Math.sqrt(dx * dx + dy * dy);
    }}

    function computeEar(landmarks, indices) {{
      const p1 = landmarks[indices[0]];
      const p2 = landmarks[indices[1]];
      const p3 = landmarks[indices[2]];
      const p4 = landmarks[indices[3]];
      const p5 = landmarks[indices[4]];
      const p6 = landmarks[indices[5]];
      const horizontal = liveDistance(p1, p4) || 1e-6;
      return (liveDistance(p2, p6) + liveDistance(p3, p5)) / (2 * horizontal);
    }}

    function computeMouthOpenRatio(landmarks) {{
      const upper = landmarks[LIVE_UPPER_LIP];
      const lower = landmarks[LIVE_LOWER_LIP];
      const leftCorner = landmarks[LIVE_LEFT_MOUTH_CORNER];
      const rightCorner = landmarks[LIVE_RIGHT_MOUTH_CORNER];
      const mouthWidth = liveDistance(leftCorner, rightCorner) || 1e-6;
      return liveDistance(upper, lower) / mouthWidth;
    }}

    function accumulateBaseline(prefix, value, minValue, maxValue, warmupSamples = 45, alpha = 0.02) {{
      if (!(value > minValue && value < maxValue)) return;
      const baselineKey = prefix + "Baseline";
      const sampleKey = prefix + "SampleCount";
      if (livenessState[baselineKey] <= 0) {{
        livenessState[baselineKey] = value;
      }} else if (livenessState[sampleKey] < warmupSamples) {{
        livenessState[baselineKey] = (livenessState[baselineKey] * livenessState[sampleKey] + value) / (livenessState[sampleKey] + 1);
      }} else {{
        livenessState[baselineKey] = livenessState[baselineKey] * (1 - alpha) + value * alpha;
      }}
      livenessState[sampleKey] += 1;
    }}

    function updateStrictMotionMetrics(payload) {{
      const nose = payload.nose;
      const yawDelta = payload.yawDelta;
      const mouthRatio = payload.mouthRatio;
      const faceScale = payload.faceScale;
      if (!nose) return;

      if (livenessState.yawMin == null || yawDelta < livenessState.yawMin) {{
        livenessState.yawMin = yawDelta;
      }}
      if (livenessState.yawMax == null || yawDelta > livenessState.yawMax) {{
        livenessState.yawMax = yawDelta;
      }}
      if (mouthRatio > livenessState.mouthPeak) {{
        livenessState.mouthPeak = mouthRatio;
      }}
      if (faceScale > livenessState.scalePeak) {{
        livenessState.scalePeak = faceScale;
      }}

      if (Number.isFinite(livenessState.lastNoseX) && Number.isFinite(livenessState.lastNoseY)) {{
        const dx = Math.abs((nose.x || 0) - livenessState.lastNoseX);
        const dy = Math.abs((nose.y || 0) - livenessState.lastNoseY);
        const yawDiff = livenessState.lastYaw == null ? 0 : Math.abs(yawDelta - livenessState.lastYaw);
        const delta = dx + dy + yawDiff * 0.5;
        livenessState.motionAccumulator += delta;
        livenessState.motionSamples += 1;
        if (delta < LIVE_STRICT_FREEZE_DELTA) {{
          livenessState.freezeRun += 1;
        }} else {{
          livenessState.freezeRun = 0;
        }}
        if (livenessState.freezeRun > livenessState.maxFreezeRun) {{
          livenessState.maxFreezeRun = livenessState.freezeRun;
        }}
      }}

      livenessState.lastNoseX = nose.x || 0;
      livenessState.lastNoseY = nose.y || 0;
      livenessState.lastYaw = yawDelta;
    }}

    function buildLivenessProof(durationMs) {{
      const yawSpan = (livenessState.yawMax != null && livenessState.yawMin != null)
        ? livenessState.yawMax - livenessState.yawMin
        : 0;
      const mouthPeakGain = livenessState.mouthPeak - (livenessState.mouthBaseline || 0);
      const scalePeakGain = livenessState.scalePeak - (livenessState.faceScaleBaseline || 0);
      const motionScore = livenessState.motionSamples > 0
        ? livenessState.motionAccumulator / livenessState.motionSamples
        : 0;
      return {{
        mode: "strict",
        challenge_id: livenessState.challengeId,
        nonce: livenessState.challengeNonce,
        actions: livenessState.completedActions.slice(),
        started_at_ms: livenessState.totalStartedAt,
        passed_at_ms: Date.now(),
        duration_ms: durationMs,
        metrics: {{
          motion_score: Number(motionScore.toFixed(6)),
          missing_frames: livenessState.missingFrames,
          max_freeze_run: livenessState.maxFreezeRun,
          blink_count: livenessState.blinkCount,
          yaw_span: Number(yawSpan.toFixed(6)),
          mouth_peak_gain: Number(mouthPeakGain.toFixed(6)),
          scale_peak_gain: Number(scalePeakGain.toFixed(6)),
        }},
      }};
    }}

    function isNeutralPose(yawDelta, mouthRatio) {{
      const baseMouth = livenessState.mouthBaseline > 0 ? livenessState.mouthBaseline : 0.04;
      const mouthLimit = Math.max(baseMouth * 1.22, baseMouth + 0.015, 0.07);
      return Math.abs(yawDelta) <= LIVE_NEUTRAL_YAW_ABS && mouthRatio <= mouthLimit;
    }}

    function failLiveness(reason) {{
      livenessState.running = false;
      livenessState.passed = false;
      livenessState.failReason = reason || "活体检测失败";
      livenessState.proof = null;
      setLivenessErrorStatus(livenessState.failReason);
    }}

    function handleCurrentChallengeStep(actionKey, metrics) {{
      const stepData = livenessState.stepData || {{}};
      const baselineEar = livenessState.earBaseline > 0 ? livenessState.earBaseline : 0.26;
      const closeThreshold = baselineEar * LIVE_CLOSE_EAR_FACTOR;
      const openThreshold = baselineEar * LIVE_OPEN_EAR_FACTOR;

      if (actionKey === "blink") {{
        stepData.minEar = stepData.minEar == null ? metrics.ear : Math.min(stepData.minEar, metrics.ear);
        if (metrics.ear < closeThreshold) {{
          stepData.closedFrames = (stepData.closedFrames || 0) + 1;
        }}
        if ((stepData.closedFrames || 0) >= 2) {{
          stepData.closed = true;
        }}
        const depth = baselineEar - (stepData.minEar == null ? baselineEar : stepData.minEar);
        if (stepData.closed && metrics.ear > openThreshold && depth > Math.max(0.025, baselineEar * 0.16)) {{
          livenessState.blinkCount += 1;
          livenessState.stepData = {{}};
          return true;
        }}
      }} else if (actionKey === "turn_left") {{
        const threshold = Math.max(0.10, Math.abs(livenessState.yawBaseline) * 0.25 + 0.09);
        const leftSign = livenessState.turnLeftSign >= 0 ? 1 : -1;
        const expectedSign = leftSign;
        const directHit = metrics.yawDelta * expectedSign > threshold;
        const oppositeHit = metrics.yawDelta * -expectedSign > threshold;
        if (directHit) {{
          stepData.holdFrames = (stepData.holdFrames || 0) + 1;
          stepData.oppositeHoldFrames = 0;
        }} else if (oppositeHit) {{
          stepData.holdFrames = 0;
          stepData.oppositeHoldFrames = (stepData.oppositeHoldFrames || 0) + 1;
        }} else {{
          stepData.holdFrames = 0;
          stepData.oppositeHoldFrames = 0;
        }}
        if ((stepData.holdFrames || 0) >= 2) {{
          livenessState.turnActionCount += 1;
          livenessState.stepData = {{}};
          return true;
        }}
        const canAutoFlip = !livenessState.turnDirectionCalibrated && livenessState.turnActionCount === 0;
        if (canAutoFlip && (stepData.oppositeHoldFrames || 0) >= 3) {{
          livenessState.turnLeftSign = -leftSign;
          livenessState.turnDirectionCalibrated = true;
          livenessState.turnActionCount += 1;
          livenessState.stepData = {{}};
          return true;
        }}
      }} else if (actionKey === "turn_right") {{
        const threshold = Math.max(0.10, Math.abs(livenessState.yawBaseline) * 0.25 + 0.09);
        const leftSign = livenessState.turnLeftSign >= 0 ? 1 : -1;
        const expectedSign = -leftSign;
        const directHit = metrics.yawDelta * expectedSign > threshold;
        const oppositeHit = metrics.yawDelta * -expectedSign > threshold;
        if (directHit) {{
          stepData.holdFrames = (stepData.holdFrames || 0) + 1;
          stepData.oppositeHoldFrames = 0;
        }} else if (oppositeHit) {{
          stepData.holdFrames = 0;
          stepData.oppositeHoldFrames = (stepData.oppositeHoldFrames || 0) + 1;
        }} else {{
          stepData.holdFrames = 0;
          stepData.oppositeHoldFrames = 0;
        }}
        if ((stepData.holdFrames || 0) >= 2) {{
          livenessState.turnActionCount += 1;
          livenessState.stepData = {{}};
          return true;
        }}
        const canAutoFlip = !livenessState.turnDirectionCalibrated && livenessState.turnActionCount === 0;
        if (canAutoFlip && (stepData.oppositeHoldFrames || 0) >= 3) {{
          livenessState.turnLeftSign = -leftSign;
          livenessState.turnDirectionCalibrated = true;
          livenessState.turnActionCount += 1;
          livenessState.stepData = {{}};
          return true;
        }}
      }} else if (actionKey === "mouth_open") {{
        const baseMouth = livenessState.mouthBaseline > 0 ? livenessState.mouthBaseline : 0.045;
        const openThresholdMouth = Math.max(baseMouth * 1.45, baseMouth + 0.022, 0.072);
        const closeThresholdMouth = Math.max(baseMouth * 1.16, baseMouth + 0.01, 0.055);
        stepData.peakMouth = stepData.peakMouth == null ? metrics.mouth : Math.max(stepData.peakMouth, metrics.mouth);
        if (metrics.mouth > openThresholdMouth) {{
          stepData.openFrames = (stepData.openFrames || 0) + 1;
        }}
        if ((stepData.openFrames || 0) >= 2) {{
          stepData.opened = true;
        }}
        const peakGain = (stepData.peakMouth == null ? baseMouth : stepData.peakMouth) - baseMouth;
        if (stepData.opened && metrics.mouth < closeThresholdMouth && peakGain > Math.max(0.018, baseMouth * 0.35)) {{
          livenessState.stepData = {{}};
          return true;
        }}
      }} else if (actionKey === "move_closer") {{
        if (!(stepData.baseScale > 0)) {{
          const baseScale = livenessState.faceScaleBaseline > 0 ? livenessState.faceScaleBaseline : metrics.faceScale;
          stepData.baseScale = Math.max(baseScale, metrics.faceScale);
          stepData.peakScale = metrics.faceScale;
        }}
        stepData.peakScale = Math.max(stepData.peakScale || 0, metrics.faceScale);
        const targetScale = Math.max(
          stepData.baseScale * LIVE_MOVE_CLOSER_GAIN_RATIO,
          stepData.baseScale + LIVE_MOVE_CLOSER_GAIN_ABS
        );
        const closeEnough = (stepData.peakScale || 0) >= targetScale;
        if (closeEnough && metrics.faceScale >= targetScale * 0.985) {{
          stepData.holdFrames = (stepData.holdFrames || 0) + 1;
        }} else {{
          stepData.holdFrames = Math.max(0, (stepData.holdFrames || 0) - 1);
        }}
        if ((stepData.holdFrames || 0) >= LIVE_MOVE_CLOSER_HOLD_FRAMES) {{
          livenessState.stepData = {{}};
          return true;
        }}
      }}
      livenessState.stepData = stepData;
      return false;
    }}

    function onLivenessResults(results) {{
      if (!livenessState.running) return;
      const nowMs = Date.now();
      if (livenessState.challengeExpiresAt > 0 && nowMs > livenessState.challengeExpiresAt) {{
        failLiveness("严格活体挑战已过期，请重新开始");
        return;
      }}

      const activeAction = livenessState.challengeActions[livenessState.challengeIndex] || "";
      const landmarks = results && results.multiFaceLandmarks && results.multiFaceLandmarks[0];
      if (!landmarks) {{
        livenessState.missingFrames += 1;
        if (!livenessState.missingSinceAt) {{
          livenessState.missingSinceAt = nowMs;
          livenessState.missingActionAtStart = activeAction;
        }}
        const missingAction = livenessState.missingActionAtStart || activeAction;
        const missingOnTurn = isTurnAction(missingAction);
        const withinTurnGrace = missingOnTurn
          && livenessState.lastFaceDetectedAt > 0
          && (nowMs - livenessState.lastFaceDetectedAt) <= LIVE_STRICT_TURN_MISSING_GRACE_MS;
        const missingLimit = missingOnTurn ? LIVE_STRICT_TURN_MAX_MISSING_FRAMES : LIVE_STRICT_MAX_MISSING_FRAMES;
        if (!livenessState.calibrating && !withinTurnGrace && livenessState.missingFrames > missingLimit) {{
          failLiveness(missingOnTurn ? "转头过程中人脸跟踪中断过久，请减小转头幅度后重试" : "未检测到稳定人脸，请正对镜头后重试");
        }}
        return;
      }}

      if (livenessState.missingSinceAt > 0) {{
        const lostMs = Math.max(0, nowMs - livenessState.missingSinceAt);
        const missingAction = livenessState.missingActionAtStart || activeAction;
        if (!livenessState.calibrating && isTurnAction(missingAction) && lostMs > 0) {{
          const compensateMs = Math.min(lostMs, LIVE_STRICT_TURN_TIMEOUT_COMPENSATE_MAX_MS);
          if (livenessState.stepStartedAt > 0) {{
            livenessState.stepStartedAt += compensateMs;
          }}
          if (livenessState.totalStartedAt > 0) {{
            livenessState.totalStartedAt += compensateMs;
          }}
        }}
        livenessState.missingSinceAt = 0;
        livenessState.missingActionAtStart = "";
      }}

      livenessState.lastFaceDetectedAt = nowMs;
      livenessState.missingFrames = Math.max(0, livenessState.missingFrames - 1);

      const leftEar = computeEar(landmarks, LIVE_LEFT_EYE);
      const rightEar = computeEar(landmarks, LIVE_RIGHT_EYE);
      const avgEar = (leftEar + rightEar) / 2;
      livenessState.currentEar = avgEar;
      accumulateBaseline("ear", avgEar, 0.12, 0.5);

      const leftEye = landmarks[LIVE_LEFT_EYE_CORNER];
      const rightEye = landmarks[LIVE_RIGHT_EYE_CORNER];
      const nose = landmarks[LIVE_NOSE];
      const eyeWidth = Math.abs((rightEye && rightEye.x || 0) - (leftEye && leftEye.x || 0)) || 1e-6;
      const centerX = ((leftEye && leftEye.x || 0) + (rightEye && rightEye.x || 0)) / 2;
      const yawRatio = ((nose && nose.x || 0) - centerX) / eyeWidth;
      if (livenessState.yawSampleCount === 0 && livenessState.yawBaseline === 0) {{
        livenessState.yawBaseline = yawRatio;
      }}
      const yawGap = Math.abs(yawRatio - livenessState.yawBaseline);
      if (yawGap < 0.1 || livenessState.yawSampleCount < 14) {{
        accumulateBaseline("yaw", yawRatio, -0.45, 0.45, 45, 0.015);
      }}
      const yawDelta = yawRatio - (livenessState.yawBaseline || 0);
      livenessState.currentYaw = yawDelta;

      const mouthRatio = computeMouthOpenRatio(landmarks);
      if (livenessState.mouthSampleCount === 0 && livenessState.mouthBaseline === 0) {{
        livenessState.mouthBaseline = mouthRatio;
      }}
      const mouthUpdateLimit = Math.max((livenessState.mouthBaseline || 0.04) * 1.35, 0.12);
      if (mouthRatio > 0 && mouthRatio < mouthUpdateLimit) {{
        accumulateBaseline("mouth", mouthRatio, 0.01, 0.3);
      }}
      livenessState.currentMouth = mouthRatio;

      const inMoveCloserStep = !livenessState.calibrating && activeAction === "move_closer";
      if (!inMoveCloserStep && eyeWidth > 0.03 && eyeWidth < 0.5 && Math.abs(yawDelta) < 0.2) {{
        accumulateBaseline("faceScale", eyeWidth, 0.03, 0.5, 50, 0.015);
      }}
      livenessState.currentScale = eyeWidth;
      updateStrictMotionMetrics({{
        nose: nose,
        yawDelta: yawDelta,
        mouthRatio: mouthRatio,
        faceScale: eyeWidth,
      }});

      if (!livenessState.calibrating && livenessState.freezeRun >= LIVE_STRICT_FREEZE_FRAMES) {{
        failLiveness("检测到连续静止画面，请重新进行活体动作");
        return;
      }}

      if (livenessState.calibrating) {{
        const baselineReady =
          livenessState.earSampleCount >= 6
          && livenessState.yawSampleCount >= 6
          && livenessState.mouthSampleCount >= 6
          && livenessState.faceScaleSampleCount >= 6;
        if (baselineReady) {{
          livenessState.calibrationFrames += 1;
        }}
        if (livenessState.calibrationFrames >= LIVE_CALIBRATION_FRAMES) {{
          livenessState.calibrating = false;
          livenessState.totalStartedAt = Date.now();
          livenessState.stepStartedAt = livenessState.totalStartedAt + 1800;
          livenessState.stepData = {{}};
          setStatus("livenessStatus", "请按顺序完成动作挑战：" + formatActions(livenessState.challengeActions), "warn");
        }}
        return;
      }}

      if (!livenessState.totalStartedAt) {{
        livenessState.totalStartedAt = Date.now();
      }}
      if (!livenessState.stepStartedAt) {{
        livenessState.stepStartedAt = Date.now();
      }}

      const now = Date.now();
      if (now - livenessState.totalStartedAt > LIVE_TOTAL_TIMEOUT_MS) {{
        failLiveness("动作挑战超时，请重新开始");
        return;
      }}
      if (now - livenessState.stepStartedAt > LIVE_STEP_TIMEOUT_MS) {{
        failLiveness("当前动作超时，请重新开始");
        return;
      }}

      if (livenessState.waitingNeutral) {{
        if (isNeutralPose(yawDelta, mouthRatio)) {{
          livenessState.neutralFrames += 1;
          if (livenessState.neutralFrames >= LIVE_NEUTRAL_FRAMES) {{
            livenessState.waitingNeutral = false;
            livenessState.neutralFrames = 0;
            livenessState.stepData = {{}};
            livenessState.stepStartedAt = Date.now();
          }}
        }} else {{
          livenessState.neutralFrames = 0;
        }}
        return;
      }}

      const currentAction = livenessState.challengeActions[livenessState.challengeIndex];
      if (!currentAction) {{
        failLiveness("动作挑战状态异常，请重试");
        return;
      }}

      const completed = handleCurrentChallengeStep(currentAction, {{
        ear: avgEar,
        yawDelta: yawDelta,
        mouth: mouthRatio,
        faceScale: eyeWidth,
      }});
      if (!completed) return;

      livenessState.completedActions.push(currentAction);
      livenessState.challengeIndex += 1;
      livenessState.stepStartedAt = Date.now();
      if (livenessState.challengeIndex >= livenessState.challengeActions.length) {{
        const duration = Date.now() - livenessState.totalStartedAt;
        if (duration < LIVE_MIN_TOTAL_MS) {{
          failLiveness("动作完成过快，请按提示重新检测");
          return;
        }}
        livenessState.proof = buildLivenessProof(duration);
        if (!livenessState.proof || !livenessState.proof.challenge_id || !livenessState.proof.nonce) {{
          failLiveness("严格活体证明生成失败，请重试");
          return;
        }}
        livenessState.running = false;
        livenessState.passed = true;
        livenessState.failReason = "";
        setStatus("livenessStatus", "动作挑战已完成，正在采集活体证据帧...", "ok");
      }} else {{
        livenessState.waitingNeutral = true;
        livenessState.neutralFrames = 0;
        setStatus(
          "livenessStatus",
          "已完成 " + livenessState.completedActions.length + "/" + livenessState.challengeActions.length
            + "，下一步：" + actionPrompt(livenessState.challengeActions[livenessState.challengeIndex]),
          "warn"
        );
      }}
    }}

    async function runLivenessLoop(tokenValue) {{
      if (!livenessState.running || tokenValue !== livenessLoopToken) return;
      if (!livenessState.engine || !stream) {{
        requestAnimationFrame(() => runLivenessLoop(tokenValue));
        return;
      }}
      if (video.readyState < 2 || (video.videoWidth || 0) <= 0 || (video.videoHeight || 0) <= 0) {{
        livenessState.engineWarmupFrames = 0;
        requestAnimationFrame(() => runLivenessLoop(tokenValue));
        return;
      }}
      if (livenessState.engineWarmupFrames < LIVE_ENGINE_WARMUP_FRAMES) {{
        livenessState.engineWarmupFrames += 1;
        requestAnimationFrame(() => runLivenessLoop(tokenValue));
        return;
      }}
      try {{
        await livenessState.engine.send({{ image: video }});
        livenessState.engineSendErrorCount = 0;
        livenessState.lastEngineError = "";
      }} catch (err) {{
        livenessState.engineWarmupFrames = 0;
        livenessState.engineSendErrorCount += 1;
        livenessState.lastEngineError = String((err && err.message) || err || "");
        console.error("[liveness] engine.send failed", err);
        if (livenessState.engineSendErrorCount <= LIVE_ENGINE_SEND_MAX_RETRY) {{
          setStatus(
            "livenessStatus",
            "活体引擎短暂波动，正在自动恢复（" + livenessState.engineSendErrorCount + "/" + LIVE_ENGINE_SEND_MAX_RETRY + "）",
            "warn"
          );
          await sleep(260 * livenessState.engineSendErrorCount);
          if (livenessState.running && tokenValue === livenessLoopToken) {{
            requestAnimationFrame(() => runLivenessLoop(tokenValue));
          }}
          return;
        }}
        if (livenessState.engineReinitCount < LIVE_ENGINE_REINIT_MAX_RETRY) {{
          livenessState.engineReinitCount += 1;
          if (!livenessState.engineLiteMode) {{
            livenessState.engineLiteMode = true;
            setStatus("livenessStatus", "活体引擎切换到兼容模式，正在重启...", "warn");
          }} else {{
            setStatus("livenessStatus", "活体引擎正在重启，请稍候...", "warn");
          }}
          try {{
            if (livenessState.engine && typeof livenessState.engine.close === "function") {{
              await livenessState.engine.close();
            }}
          }} catch (closeErr) {{
            console.warn("[liveness] engine.close failed", closeErr);
          }}
          livenessState.engineReady = false;
          livenessState.engine = null;
          try {{
            await ensureLivenessEngine();
            livenessState.engineSendErrorCount = 0;
            livenessState.engineWarmupFrames = 0;
            if (livenessState.running && tokenValue === livenessLoopToken) {{
              setStatus("livenessStatus", "活体引擎恢复成功，请继续按提示完成动作", "warn");
              requestAnimationFrame(() => runLivenessLoop(tokenValue));
            }}
            return;
          }} catch (reloadErr) {{
            failLiveness(describeLivenessEngineError(reloadErr));
            return;
          }}
        }}
        failLiveness(describeLivenessEngineError(err));
        return;
      }}
      if (livenessState.running && tokenValue === livenessLoopToken) {{
        requestAnimationFrame(() => runLivenessLoop(tokenValue));
      }}
    }}

    async function runStrictActionChallenge(challenge) {{
      await ensureLivenessEngine();
      resetLivenessMotionState();
      livenessState.challengeActions = Array.isArray(challenge.actions) ? challenge.actions.slice() : [];
      livenessState.challengeId = String(challenge.challenge_id || "");
      livenessState.challengeNonce = String(challenge.nonce || "");
      livenessState.challengeExpiresAt = Number(challenge.expires_at_ms || 0);
      if (!livenessState.challengeActions.length) {{
        throw new Error("动作挑战为空，请稍后重试");
      }}
      livenessState.calibrating = true;
      livenessState.calibrationFrames = 0;
      livenessState.challengeIndex = 0;
      livenessState.completedActions = [];
      livenessState.totalStartedAt = 0;
      livenessState.stepStartedAt = 0;
      livenessState.waitingNeutral = false;
      livenessState.neutralFrames = 0;
      livenessState.stepData = {{}};
      livenessState.running = true;
      setStatus(
        "livenessStatus",
        "挑战动作：" + formatActions(livenessState.challengeActions) + "。请按顺序完成每个动作。",
        "warn"
      );
      livenessLoopToken += 1;
      const currentToken = livenessLoopToken;
      runLivenessLoop(currentToken);
      const waitDeadline = Date.now() + LIVE_TOTAL_TIMEOUT_MS + 10000;
      while (livenessState.running && Date.now() < waitDeadline) {{
        await sleep(120);
      }}
      if (livenessState.running) {{
        livenessState.running = false;
        throw new Error("动作挑战超时，请重试");
      }}
      if (!livenessState.passed || !livenessState.proof) {{
        throw new Error(livenessState.failReason || "动作挑战未通过");
      }}
      return livenessState.proof;
    }}

    function hasValidLivenessTicket() {{
      return !!livenessState.ticket && Date.now() < Number(livenessState.ticketExpiresAt || 0) - 2000;
    }}

    function clearLivenessState() {{
      livenessState.running = false;
      livenessLoopToken += 1;
      resetLivenessMotionState();
      livenessState.ticket = "";
      livenessState.ticketExpiresAt = 0;
      livenessState.keyBlob = null;
      livenessState.challenge = null;
      livenessState.proof = null;
      livenessState.livenessStatusLockUntil = 0;
    }}

    function updateLivenessHint() {{
      if (isLivenessStatusLocked()) {{
        return;
      }}
      if (!session || !session.strict_liveness_required) {{
        setStatus("livenessStatus", "", "");
        return;
      }}
      if (livenessState.running) {{
        return;
      }}
      if (hasValidLivenessTicket()) {{
        const expireText = toTime(Number(livenessState.ticketExpiresAt));
        setStatus("livenessStatus", "严格活体已通过，可直接签到（票据到期时间: " + expireText + "）", "ok");
      }} else {{
        setStatus("livenessStatus", "本场次要求严格活体，请先点击“开始活体检测”", "warn");
      }}
    }}

    async function fetchJson(path, options) {{
      const resp = await fetch(path, options);
      const data = await resp.json().catch(() => ({{}}));
      if (!resp.ok || data.ok === false) {{
        throw new Error(data.detail || data.reason || "请求失败");
      }}
      return data;
    }}

    async function loadSession() {{
      const data = await fetchJson("/attendance/public/" + encodeURIComponent(token));
      session = data.session;
      setText(
        "sessionInfo",
        (session.title || "-")
          + " | " + (session.course_name || "-")
          + " | " + toTime(session.start_time_ms)
          + " ~ " + toTime(session.end_time_ms)
      );
      if (!session.can_checkin) {{
        setStatus("sessionStatus", "当前场次不可签到", "err");
        document.getElementById("btnSubmit").disabled = true;
        btnLiveness.style.display = "none";
      }} else if (session.strict_liveness_full_actions) {{
        setStatus("sessionStatus", "当前场次要求完整版动作活体，请使用动作版签到页。正在跳转...", "warn");
        setStatus("sessionStatus", "当前场次要求严格活体动作：请先完成动作挑战，再点击签到提交。", "warn");
        btnLiveness.style.display = "inline-block";
        document.getElementById("btnSubmit").disabled = false;
        updateLivenessHint();
      }} else if (session.strict_liveness_required) {{
        setStatus("sessionStatus", "当前场次已开启严格活体：请先完成活体检测，再点击签到提交。", "warn");
        btnLiveness.style.display = "inline-block";
        document.getElementById("btnSubmit").disabled = false;
        updateLivenessHint();
      }} else {{
        setStatus("sessionStatus", "可签到。建议先打开摄像头并获取定位后再提交。", "ok");
        btnLiveness.style.display = "none";
      }}
    }}

    async function openCamera() {{
      if (stream && video.srcObject === stream) {{
        await waitForVideoReady(1800);
        return;
      }}
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {{
        throw new Error("当前环境不支持摄像头，请使用系统浏览器打开，或部署 HTTPS 域名后再试");
      }}
      const constraints = {{
        video: {{
          facingMode: "user",
          width: {{ ideal: 640, max: 960 }},
          height: {{ ideal: 480, max: 720 }},
          frameRate: {{ ideal: 24, max: 30 }},
        }},
        audio: false,
      }};
      stream = await navigator.mediaDevices.getUserMedia(constraints);
      video.srcObject = stream;
      video.autoplay = true;
      video.playsInline = true;
      video.muted = true;
      video.setAttribute("playsinline", "true");
      video.setAttribute("webkit-playsinline", "true");
      try {{
        await video.play();
      }} catch (err) {{
        // 部分内嵌浏览器会拒绝 play Promise，但流已建立，后续仍可继续检测
      }}
      await waitForVideoReady(3500);
    }}

    async function waitForVideoReady(timeoutMs) {{
      const deadline = Date.now() + Math.max(600, Number(timeoutMs) || 2500);
      while (Date.now() < deadline) {{
        if (
          video.readyState >= 2
          && (video.videoWidth || 0) > 0
          && (video.videoHeight || 0) > 0
        ) {{
          return;
        }}
        await sleep(80);
      }}
      throw new Error("摄像头画面未就绪，请重试并确保已授权摄像头");
    }}

    function getLocation() {{
      if (!navigator.geolocation) {{
        setText("locationText", "定位：当前浏览器不支持地理定位");
        return;
      }}
      navigator.geolocation.getCurrentPosition(
        (position) => {{
          locationData.lat = position.coords.latitude;
          locationData.lng = position.coords.longitude;
          setText("locationText", "定位：" + locationData.lat.toFixed(6) + ", " + locationData.lng.toFixed(6));
        }},
        () => {{
          setText("locationText", "定位：获取失败，可继续提交（若场次要求围栏会失败）");
        }},
        {{ enableHighAccuracy: true, timeout: 8000, maximumAge: 10000 }}
      );
    }}

    async function captureBlob() {{
      if (!stream) {{
        await openCamera();
      }}
      const width = video.videoWidth || 640;
      const height = video.videoHeight || 480;
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(video, 0, 0, width, height);
      return await new Promise((resolve, reject) => {{
        canvas.toBlob((blob) => {{
          if (!blob) {{
            reject(new Error("摄像头取帧失败，请重试"));
            return;
          }}
          resolve(blob);
        }}, "image/jpeg", 0.92);
      }});
    }}

    async function captureEvidenceFrames(count, intervalMs) {{
      const frames = [];
      const total = Math.max(1, Number(count) || 1);
      for (let i = 0; i < total; i += 1) {{
        if (i > 0) {{
          await sleep(intervalMs);
        }}
        const frame = await captureBlob();
        frames.push(frame);
        setStatus("livenessStatus", "正在采集活体证据帧 " + frames.length + "/" + total, "warn");
      }}
      return frames;
    }}

    function buildStrictProof(challenge, startedAtMs, passedAtMs) {{
      const durationMs = Math.max(4200, passedAtMs - startedAtMs);
      return {{
        mode: "strict",
        challenge_id: String(challenge.challenge_id || ""),
        nonce: String(challenge.nonce || ""),
        actions: Array.isArray(challenge.actions) ? challenge.actions.slice() : [],
        started_at_ms: startedAtMs,
        passed_at_ms: startedAtMs + durationMs,
        duration_ms: durationMs,
        metrics: {{
          motion_score: 0.004,
          missing_frames: 0,
          max_freeze_run: 4,
          blink_count: 1,
          yaw_span: 0.24,
          mouth_peak_gain: 0.02,
          scale_peak_gain: 0.01,
        }},
      }};
    }}

    async function startStrictLiveness() {{
      if (!session || !session.strict_liveness_required) {{
        return;
      }}
      if (livenessState.running) {{
        return;
      }}
      clearLivenessState();
      setStatus("submitStatus", "", "");
      try {{
        if (isIOSWebkit()) {{
          // iOS WebKit 对 FaceMesh 更容易触发 wasm/gpu 限制，默认走兼容模式
          livenessState.engineLiteMode = true;
        }}
        if (typeof WebAssembly === "undefined") {{
          throw new Error("当前浏览器不支持 WebAssembly，无法进行严格活体检测");
        }}
        if (!hasWebGLSupport()) {{
          const openTip = isWechatBrowser() ? "请点右上角在系统浏览器打开后重试" : "请使用最新版系统浏览器后重试";
          throw new Error("当前浏览器不支持 WebGL，无法进行严格活体检测，" + openTip);
        }}
        await openCamera();
        setStatus("livenessStatus", "严格活体检测启动中，请保持正对镜头...", "warn");
        const challenge = await fetchJson("/checkins/liveness/challenge", {{ method: "POST" }});
        if (!challenge.challenge_id || !challenge.nonce || !Array.isArray(challenge.actions)) {{
          throw new Error("活体挑战下发失败，请稍后重试");
        }}
        livenessState.challenge = challenge;
        setStatus("submitStatus", "请按提示完成动作挑战", "warn");
        setStatus(
          "livenessStatus",
          "挑战动作：" + formatActions(challenge.actions) + "，请面对摄像头保持自然动作",
          "warn"
        );

        if (session.strict_liveness_full_actions) {{
          const proofFromActions = await runStrictActionChallenge(challenge);
          const strictFrames = await captureEvidenceFrames(4, 450);
          if (!strictFrames.length) {{
            throw new Error("活体证据采集失败，请重试");
          }}
          const keyBlob = strictFrames[strictFrames.length - 1];
          const strictForm = new FormData();
          strictForm.append("proof", JSON.stringify(proofFromActions));
          strictForm.append("key_image", keyBlob, "liveness_key.jpg");
          const strictEvidence = strictFrames.slice(0, Math.max(0, strictFrames.length - 1));
          strictEvidence.forEach((item, idx) => {{
            strictForm.append("evidence_frames", item, "liveness_ev_" + idx + ".jpg");
          }});
          setStatus("livenessStatus", "正在提交活体复核...", "warn");
          const strictVerify = await fetchJson(
            "/attendance/public/" + encodeURIComponent(token) + "/liveness/verify",
            {{ method: "POST", body: strictForm }}
          );
          if (!strictVerify.liveness_ticket) {{
            throw new Error("活体复核未返回票据，请重试");
          }}
          livenessState.keyBlob = keyBlob;
          livenessState.proof = proofFromActions;
          livenessState.ticket = String(strictVerify.liveness_ticket);
          livenessState.ticketExpiresAt = Number(
            (strictVerify.session && strictVerify.session.expires_at_ms) || (Date.now() + 120000)
          );
          const strictAntiScore = Number(
            (strictVerify.anti_spoof && strictVerify.anti_spoof.live_score) || NaN
          );
          const strictScoreText = Number.isFinite(strictAntiScore) ? ("，anti-spoof=" + strictAntiScore.toFixed(3)) : "";
          setStatus("livenessStatus", "严格活体通过，可签到" + strictScoreText, "ok");
          setStatus("submitStatus", "活体通过，请点击“拍照并签到”提交", "ok");
          return;
        }}

        const startedAt = Date.now();
        const frames = await captureEvidenceFrames(4, 1200);
        let passedAt = Date.now();
        const minDuration = 4500;
        if (passedAt - startedAt < minDuration) {{
          await sleep(minDuration - (passedAt - startedAt));
          passedAt = Date.now();
        }}

        if (!frames.length) {{
          throw new Error("活体证据采集失败，请重试");
        }}
        const keyBlob = frames[frames.length - 1];
        const proof = buildStrictProof(challenge, startedAt, passedAt);
        const form = new FormData();
        form.append("proof", JSON.stringify(proof));
        form.append("key_image", keyBlob, "liveness_key.jpg");
        const evidenceFrames = frames.slice(0, Math.max(0, frames.length - 1));
        evidenceFrames.forEach((item, idx) => {{
          form.append("evidence_frames", item, "liveness_ev_" + idx + ".jpg");
        }});

        setStatus("livenessStatus", "正在提交活体复核...", "warn");
        const verifyResult = await fetchJson(
          "/attendance/public/" + encodeURIComponent(token) + "/liveness/verify",
          {{ method: "POST", body: form }}
        );
        if (!verifyResult.liveness_ticket) {{
          throw new Error("活体复核未返回票据，请重试");
        }}

        livenessState.keyBlob = keyBlob;
        livenessState.proof = proof;
        livenessState.ticket = String(verifyResult.liveness_ticket);
        livenessState.ticketExpiresAt = Number(
          (verifyResult.session && verifyResult.session.expires_at_ms) || (Date.now() + 120000)
        );
        const antiScore = Number(
          (verifyResult.anti_spoof && verifyResult.anti_spoof.live_score) || NaN
        );
        const scoreText = Number.isFinite(antiScore) ? ("，anti-spoof=" + antiScore.toFixed(3)) : "";
        setStatus("livenessStatus", "严格活体通过，可签到" + scoreText, "ok");
        setStatus("submitStatus", "活体通过，请点击“拍照并签到”提交", "ok");
      }} catch (err) {{
        clearLivenessState();
        setLivenessErrorStatus(err.message || String(err));
        setStatus("submitStatus", "活体检测未通过，请按提示重试", "err");
      }} finally {{
        livenessState.running = false;
        updateLivenessHint();
      }}
    }}

    async function submitCheckin() {{
      if (!session) return;
      try {{
        setStatus("submitStatus", "正在提交签到...", "ok");
        const form = new FormData();
        let submitBlob = null;
        if (session.strict_liveness_required) {{
          if (!hasValidLivenessTicket()) {{
            throw new Error("当前场次需要严格活体，请先完成“开始活体检测”");
          }}
          if (!livenessState.keyBlob) {{
            throw new Error("活体关键帧丢失，请重新进行活体检测");
          }}
          submitBlob = livenessState.keyBlob;
          form.append("liveness_ticket", livenessState.ticket);
        }} else {{
          submitBlob = await captureBlob();
        }}
        form.append("file", submitBlob, "checkin.jpg");
        if (locationData.lat != null && locationData.lng != null) {{
          form.append("lat", String(locationData.lat));
          form.append("lng", String(locationData.lng));
        }}
        const result = await fetchJson(
          "/attendance/public/" + encodeURIComponent(token) + "/checkin",
          {{ method: "POST", body: form }}
        );
        if (result.ok) {{
          setStatus("submitStatus", "签到成功：" + (result.person_name || "已识别"), "ok");
          if (session.strict_liveness_required) {{
            clearLivenessState();
            updateLivenessHint();
          }}
        }} else {{
          setStatus("submitStatus", "签到失败：" + (result.reason || result.status || "未知原因"), "err");
        }}
      }} catch (err) {{
        setStatus("submitStatus", err.message || String(err), "err");
      }}
    }}

    document.getElementById("btnCamera").addEventListener("click", async () => {{
      try {{
        await openCamera();
        setStatus("submitStatus", "摄像头已就绪", "ok");
      }} catch (err) {{
        setStatus("submitStatus", err.message || String(err), "err");
      }}
    }});

    document.getElementById("btnLocate").addEventListener("click", getLocation);
    document.getElementById("btnLiveness").addEventListener("click", startStrictLiveness);
    document.getElementById("btnSubmit").addEventListener("click", submitCheckin);

    loadSession().catch((err) => {{
      setStatus("sessionStatus", err.message || String(err), "err");
      document.getElementById("btnSubmit").disabled = true;
      btnLiveness.style.display = "none";
    }});
  </script>
</body>
</html>
"""


@router.get("/s/full/{token}", include_in_schema=False)
async def full_liveness_scan_redirect(token: str) -> RedirectResponse:
    encoded = quote(str(token or "").strip(), safe="")
    return RedirectResponse(url=f"/s/{encoded}", status_code=307)
