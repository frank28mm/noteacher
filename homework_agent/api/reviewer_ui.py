from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from homework_agent.utils.settings import get_settings

router = APIRouter(prefix="/reviewer", tags=["reviewer"])


_HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Reviewer Workbench</title>
    <style>
      body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 24px; }
      h1 { margin: 0 0 12px 0; }
      .row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }
      input, select, textarea, button { font: inherit; padding: 8px 10px; }
      input, select, textarea { border: 1px solid #ddd; border-radius: 8px; }
      button { border: 1px solid #111; background: #111; color: #fff; border-radius: 8px; cursor: pointer; }
      button.secondary { background: #fff; color: #111; }
      .meta { color: #666; }
      .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      .card { border: 1px solid #eee; border-radius: 12px; padding: 12px; }
      .list { max-height: 65vh; overflow: auto; }
      .item { padding: 10px; border-bottom: 1px solid #f0f0f0; cursor: pointer; }
      .item:hover { background: #fafafa; }
      code { background: #fafafa; border: 1px solid #eee; padding: 1px 6px; border-radius: 6px; }
      pre { background: #fafafa; border: 1px solid #eee; padding: 12px; border-radius: 10px; overflow: auto; }
      .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; border: 1px solid #eee; margin-right: 6px; font-size: 12px; }
    </style>
  </head>
  <body>
    <h1>Reviewer Workbench</h1>
    <div class="row">
      <input id="baseUrl" style="min-width: 280px" placeholder="Base URL (e.g. http://localhost:8000)" />
      <input id="token" style="min-width: 220px" placeholder="X-Admin-Token" />
      <select id="status">
        <option value="open">open</option>
        <option value="resolved">resolved</option>
      </select>
      <input id="limit" type="number" min="1" max="200" value="50" style="width: 90px" />
      <button onclick="reload()">Reload</button>
      <button class="secondary" onclick="saveCfg()">Save</button>
      <span class="meta" id="msg"></span>
    </div>

    <div class="grid">
      <div class="card">
        <div class="row"><strong>Items</strong></div>
        <div class="list" id="list"></div>
      </div>
      <div class="card">
        <div class="row"><strong>Details</strong><span class="meta" id="detailTitle"></span></div>
        <pre id="detail">Select an item…</pre>
        <div class="row">
          <input id="resolvedBy" placeholder="resolved_by" style="min-width: 180px" />
          <input id="note" placeholder="note (optional)" style="min-width: 240px" />
          <button onclick="resolve()">Resolve</button>
        </div>
      </div>
    </div>

    <script>
      let currentItem = null;

      function qs(id) { return document.getElementById(id); }
      function setMsg(t) { qs("msg").innerText = t || ""; }

      function saveCfg() {
        localStorage.setItem("reviewer.baseUrl", qs("baseUrl").value);
        localStorage.setItem("reviewer.token", qs("token").value);
        setMsg("saved");
      }
      function loadCfg() {
        qs("baseUrl").value = localStorage.getItem("reviewer.baseUrl") || "";
        qs("token").value = localStorage.getItem("reviewer.token") || "";
      }

      async function api(path, opts) {
        const base = qs("baseUrl").value || "";
        const token = qs("token").value || "";
        const headers = Object.assign({}, (opts && opts.headers) || {});
        if (token) headers["X-Admin-Token"] = token;
        if (!headers["Content-Type"] && opts && opts.body) headers["Content-Type"] = "application/json";
        const res = await fetch(base + path, Object.assign({}, opts || {}, { headers }));
        if (!res.ok) throw new Error(res.status + " " + (await res.text()));
        return await res.json();
      }

      function renderItem(it) {
        const div = document.createElement("div");
        div.className = "item";
        div.onclick = () => selectItem(it.item_id);
        const codes = (it.warning_codes || []).slice(0, 4).map(c => `<span class="pill">${c}</span>`).join("");
        div.innerHTML = `
          <div><code>${it.item_id}</code> <span class="meta">${it.subject || ""}</span></div>
          <div class="meta">req=${it.request_id} sess=${it.session_id}</div>
          <div>${codes}</div>
        `;
        return div;
      }

      async function reload() {
        setMsg("loading…");
        currentItem = null;
        qs("detailTitle").innerText = "";
        qs("detail").innerText = "Select an item…";
        qs("list").innerHTML = "";
        try {
          const status = qs("status").value;
          const limit = parseInt(qs("limit").value || "50", 10);
          const data = await api(`/api/v1/review/items?status_filter=${encodeURIComponent(status)}&limit=${limit}`, { method: "GET" });
          const items = data.items || [];
          items.forEach(it => qs("list").appendChild(renderItem(it)));
          setMsg(`loaded ${items.length}`);
        } catch (e) {
          setMsg("error: " + e.message);
        }
      }

      async function selectItem(itemId) {
        try {
          const obj = await api(`/api/v1/review/items/${encodeURIComponent(itemId)}`, { method: "GET" });
          currentItem = obj;
          qs("detailTitle").innerText = " " + itemId;
          qs("detail").innerText = JSON.stringify(obj, null, 2);
        } catch (e) {
          setMsg("error: " + e.message);
        }
      }

      async function resolve() {
        if (!currentItem) return;
        try {
          const payload = { resolved_by: qs("resolvedBy").value || "reviewer", note: qs("note").value || null };
          await api(`/api/v1/review/items/${encodeURIComponent(currentItem.item_id)}/resolve`, { method: "POST", body: JSON.stringify(payload) });
          setMsg("resolved");
          await reload();
        } catch (e) {
          setMsg("error: " + e.message);
        }
      }

      loadCfg();
    </script>
  </body>
</html>
"""


@router.get("")
async def reviewer_ui():
    settings = get_settings()
    if not getattr(settings, "review_ui_enabled", False):
        raise HTTPException(status_code=404, detail="review ui disabled")
    return HTMLResponse(_HTML)
