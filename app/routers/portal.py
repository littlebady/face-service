from __future__ import annotations

import json

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
        <button class="btn-soft" id="btnLegacy">旧版首页</button>
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
        <label class="check"><input id="checkOnce" type="checkbox" checked /> 每人仅可成功签到一次</label>
        <label class="check"><input id="strictLive" type="checkbox" /> 启用严格活体（当前简版扫码页不建议开启）</label>
        <button class="btn-primary" id="btnPublish">发布签到</button>
        <div class="hint">若填写经纬度则自动启用地理围栏；不填则不校验定位。</div>
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

    async function publishSession() {
      const centerLat = toNum($("centerLat").value, null);
      const centerLng = toNum($("centerLng").value, null);
      const geofenceEnabled = centerLat != null && centerLng != null;

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
        strict_liveness_required: !!$("strictLive").checked,
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

    $("btnRefresh").addEventListener("click", async () => {
      try {
        await refreshAll();
      } catch (err) {
        alert(err.message || String(err));
      }
    });

    $("btnLegacy").addEventListener("click", () => {
      window.location.href = "/checkin-ui";
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
        <button class="btn-dark" id="btnSubmit">拍照并签到</button>
      </div>
      <div id="locationText" class="muted">定位：未获取</div>
      <div id="submitStatus" class="status"></div>
    </section>
  </main>

  <script>
    const token = {token_json};
    let session = null;
    let stream = null;
    let locationData = {{ lat: null, lng: null }};
    const video = document.getElementById("video");
    const canvas = document.getElementById("canvas");

    function setStatus(id, text, level) {{
      const el = document.getElementById(id);
      el.textContent = text || "";
      el.className = "status " + (level || "");
    }}

    function setText(id, text) {{
      const el = document.getElementById(id);
      el.textContent = text || "";
    }}

    function toTime(ms) {{
      if (!ms) return "-";
      return new Date(Number(ms)).toLocaleString();
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
        `${{session.title}} | ${{session.course_name || "-"}} | ${{toTime(session.start_time_ms)}} ~ ${{toTime(session.end_time_ms)}}`
      );
      if (!session.can_checkin) {{
        setStatus("sessionStatus", "当前场次不可签到", "err");
        document.getElementById("btnSubmit").disabled = true;
      }} else if (session.strict_liveness_required) {{
        setStatus("sessionStatus", "当前场次开启了严格活体，简版扫码页暂不支持，请联系发布者关闭严格活体后重试。", "warn");
        document.getElementById("btnSubmit").disabled = true;
      }} else {{
        setStatus("sessionStatus", "可签到。建议先打开摄像头并获取定位后再提交。", "ok");
      }}
    }}

    async function openCamera() {{
      if (stream) return;
      stream = await navigator.mediaDevices.getUserMedia({{
        video: {{ facingMode: "user" }},
        audio: false
      }});
      video.srcObject = stream;
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
          setText("locationText", `定位：${{locationData.lat.toFixed(6)}}, ${{locationData.lng.toFixed(6)}}`);
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
      return await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
    }}

    async function submitCheckin() {{
      if (!session) return;
      try {{
        setStatus("submitStatus", "正在提交签到...", "ok");
        const blob = await captureBlob();
        const form = new FormData();
        form.append("file", blob, "checkin.jpg");
        if (locationData.lat != null && locationData.lng != null) {{
          form.append("lat", String(locationData.lat));
          form.append("lng", String(locationData.lng));
        }}
        const result = await fetchJson(
          "/attendance/public/" + encodeURIComponent(token) + "/checkin",
          {{ method: "POST", body: form }}
        );
        if (result.ok) {{
          setStatus("submitStatus", `签到成功：${{result.person_name || "已识别"}}`, "ok");
        }} else {{
          setStatus("submitStatus", `签到失败：${{result.reason || result.status || "未知原因"}}`, "err");
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
    document.getElementById("btnSubmit").addEventListener("click", submitCheckin);

    loadSession().catch((err) => {{
      setStatus("sessionStatus", err.message || String(err), "err");
      document.getElementById("btnSubmit").disabled = true;
    }});
  </script>
</body>
</html>
"""
