/* paceghost WebUI 前端 — vanilla JS, 无构建链 */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const fmtTime = (s) => {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return (h ? h + ":" : "") + String(m).padStart(2, "0") + ":" + String(sec).padStart(2, "0");
};
const fmtAgo = (ts) => {
  if (!ts) return "未知";
  const d = Math.floor(Date.now() / 1000 - ts);
  if (d < 60) return "刚刚";
  if (d < 3600) return Math.floor(d / 60) + " 分钟前";
  if (d < 86400) return Math.floor(d / 3600) + " 小时前";
  return Math.floor(d / 86400) + " 天前";
};
const fmtDist = (m) => (m >= 1000 ? (m / 1000).toFixed(2) + " km" : Math.round(m) + " m");

async function api(path, body) {
  const opt = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const d = await r.json().catch(() => ({ error: "bad json" }));
  if (!r.ok) throw new Error(d.error || r.status);
  return d;
}

/* ---------- toasts ---------- */
function toast(msg, cls = "") {
  const el = document.createElement("div");
  el.className = "toast " + cls;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

/* ---------- confirm dialog ---------- */
const dlgConfirm = $("#dlg-confirm");
let confirmResolve = null;
function askConfirm(title, text) {
  $("#confirm-title").textContent = title;
  $("#confirm-text").textContent = text;
  dlgConfirm.showModal();
  return new Promise((res) => { confirmResolve = res; });
}
$("#confirm-ok").onclick = () => { dlgConfirm.close(); confirmResolve?.(true); };
$("#confirm-cancel").onclick = () => { dlgConfirm.close(); confirmResolve?.(false); };

/* ---------- registry dialog ---------- */
const dlgReg = $("#dlg-registry");
let regMode = "edit"; // edit | new
function openRegistry(dev) {
  regMode = dev ? "edit" : "new";
  $("#reg-title").textContent = dev ? "编辑设备: " + dev.alias : "登记新设备";
  $("#reg-alias").value = dev ? dev.alias : "";
  $("#reg-alias").disabled = !!dev;
  $("#reg-serial").value = dev ? dev.serial : "";
  $("#reg-wifi").value = dev ? (dev.wifi || "") : "";
  $("#reg-port").value = dev ? dev.port : "";
  $("#reg-mode").value = dev ? dev.mode : "testprovider";
  $("#reg-cadence").value = dev ? dev.cadence : 131;
  $("#reg-speed").value = dev ? dev.speed_kmh : 13.33;
  $("#reg-face").value = dev ? (dev.face || "") : "";
  $("#reg-del").style.display = dev ? "" : "none";
  dlgReg.showModal();
}
$("#reg-save").onclick = async () => {
  try {
    const doc = (await api("/api/registry")).devices;
    const alias = $("#reg-alias").value.trim();
    if (!alias) throw new Error("别名必填");
    const entry = {
      serial: $("#reg-serial").value.trim(),
      wifi: $("#reg-wifi").value.trim(),
      port: parseInt($("#reg-port").value, 10),
      mode: $("#reg-mode").value,
      cadence: parseInt($("#reg-cadence").value, 10) || 131,
      speed_kmh: parseFloat($("#reg-speed").value) || 13.33,
      face: $("#reg-face").value.trim(),
    };
    if (!entry.port) throw new Error("端口必填");
    if (regMode === "edit") doc[alias] = entry;
    else {
      if (doc[alias]) throw new Error("别名已存在");
      doc[alias] = entry;
    }
    await api("/api/registry", doc);
    dlgReg.close();
    toast("devices.json 已保存 (自动备份)", "ok");
    refresh(true);
  } catch (e) { toast("保存失败: " + e.message, "err"); }
};
$("#reg-del").onclick = async () => {
  const alias = $("#reg-alias").value.trim();
  if (!(await askConfirm("删除设备条目", `将把 [${alias}] 从 devices.json 移除 (自动备份保留原文件)。确认?`))) return;
  try {
    const doc = (await api("/api/registry")).devices;
    delete doc[alias];
    await api("/api/registry", doc);
    dlgReg.close();
    toast("已删除 " + alias, "ok");
    refresh(true);
  } catch (e) { toast("删除失败: " + e.message, "err"); }
};
$("#reg-cancel").onclick = () => dlgReg.close();

/* ---------- face upload ---------- */
let faceTarget = null;
function uploadFace(alias) {
  faceTarget = alias;
  $("#face-file").click();
}
$("#face-file").onchange = async () => {
  const f = $("#face-file").files[0];
  $("#face-file").value = "";
  if (!f || !faceTarget) return;
  if (!/^[\w\-. ]+$/.test(f.name.replace(/\.(png|jpe?g)$/i, ""))) {
    toast("文件名须为 ASCII, 请先重命名", "err"); return;
  }
  const buf = await f.arrayBuffer();
  let bin = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000)
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  toast("上传人脸中: " + faceTarget);
  try {
    const r = await api("/api/face", { alias: faceTarget, filename: f.name, data_b64: btoa(bin) });
    toast(r.detail, r.ok ? "ok" : "err");
    refresh(true);
  } catch (e) { toast("上传失败: " + e.message, "err"); }
};

/* ---------- device card ---------- */
function cardHtml(d) {
  const ch = d.channel, rs = d.rs;
  const chCls = ch.via === "USB" ? "usb" : ch.via.startsWith("WiFi") ? "wifi" : "off";
  const chText = ch.via === "offline" ? "离线" : ch.via;
  const st = rs.state;
  const stCls = "state-" + (["idle", "ready", "playing", "error", "paused", "unreachable"].includes(st) ? st : "idle");
  const cur = rs.current;
  const playing = st === "playing";
  const guardOn = !!d.guard.running, bridgeOn = !!d.bridge.running;
  const guardTip = d.guard.adopted ? " (收养的孤儿进程, pid " + d.guard.pid + ")" : "";
  return `
  <div class="card ${playing ? "playing" : ""} ${st === "error" ? "errorstate" : ""}" id="card-${d.alias}">
    <div class="card-head">
      <div class="title-wrap">
        <span class="alias">${d.alias}</span>
        <span class="model">${ch.model || ""}</span>
      </div>
      <span class="head-right">
        <span class="badge mode">${rs.mode || d.mode}</span>
        <span class="badge ${chCls}">${chText}</span>
        <span class="state-pill ${stCls}">${st}</span>
      </span>
    </div>
    <div class="meta-grid">
      <span class="mk">端口</span><span class="mv">${d.port}</span>
      <span class="mk">守卫</span><span class="mv ${guardOn ? "on" : ""}" title="${guardTip}">${guardOn ? "运行中" : "停止"}</span>
      <span class="mk">serial</span><span class="mv mono">${d.serial}</span>
      <span class="mk">jrpos桥</span><span class="mv ${bridgeOn ? "on" : ""}">${bridgeOn ? "运行中" : "停止"}</span>
    </div>
    <div class="stats">
      <div class="stat"><div class="v">${fmtDist(rs.distance_m)}</div><div class="k">本次里程</div></div>
      <div class="stat"><div class="v">${fmtTime(rs.elapsed_s)}</div><div class="k">用时</div></div>
      <div class="stat"><div class="v">${rs.laps || 0}</div><div class="k">圈数</div></div>
      <div class="stat"><div class="v route" title="${rs.route_name || ""}">${rs.route_name || "—"}</div><div class="k">路线</div></div>
      <div class="coords"><span class="ck">坐标</span><span>${cur ? `${cur.lat.toFixed(6)}, ${cur.lng.toFixed(6)}` : "—"}</span></div>
    </div>
    ${rs.error ? `<div class="errline">RS: ${rs.error}</div>` : ""}
    <div class="face-chip">
      <span class="fk">人脸</span>
      <span class="fname" title="${d.face || ""}">${d.face ? d.face.split("/").pop() : "未配置"}</span>
      <span class="fmtime" title="${d.face || ""}">${fmtAgo(d.face_mtime)}</span>
      <button class="small" data-act="face">换图</button>
    </div>
    <div class="btnrow primary-row">
      <button class="primary" data-act="run" ${d.busy ? "disabled" : ""}>一键开跑</button>
      <button class="danger" data-act="stop">停止</button>
      <button data-act="guard" class="${guardOn ? "toggled" : ""}">${guardOn ? "守卫停止" : "守卫启动"}</button>
      <button data-act="bridge" class="${bridgeOn ? "toggled" : ""}">${bridgeOn ? "桥停止" : "jrpos桥"}</button>
    </div>
    <div class="btnrow secondary-row">
      <button class="small" data-act="edit">编辑</button>
      <button class="small" data-act="log">日志</button>
      <a class="rs-link" href="http://127.0.0.1:${d.port}/" target="_blank"><button class="small">RS 页面 ↗</button></a>
    </div>
    <div class="pipe-slot"></div>
  </div>`;
}

function renderPipe(card, pipe) {
  const slot = card.querySelector(".pipe-slot");
  if (!pipe) { slot.innerHTML = ""; return; }
  const ok = pipe.ok;
  const rows = (pipe.steps || []).map(s =>
    `<li class="${s.ok ? "" : "fail"}">${s.ok ? "✓" : "✗"} ${s.step} — ${s.detail}</li>`).join("");
  slot.innerHTML = `<div class="pipe-result">
    <span class="${ok ? "ok" : "bad"}">${ok ? "流水线完成" : "流水线失败"}</span>
    <span style="color:var(--dim)"> ${pipe.kind} @ ${new Date(pipe.started_at * 1000).toLocaleTimeString()}</span>
    ${pipe.error ? `<div class="bad">${pipe.error}</div>` : ""}
    <ul class="pipe-steps">${rows}</ul></div>`;
}

async function deviceAction(alias, act, extra = {}) {
  try {
    const out = await api(`/api/devices/${alias}/${act}`, extra);
    if (out.confirm_required) {
      const yes = await askConfirm("实例正在播放",
        `RS 实例 (端口) 处于 playing 状态。${act === "run" ? "将先停掉当前播放再重跑" : "将停止播放并断连"}。\n确认继续?`);
      if (!yes) return;
      return deviceAction(alias, act, { ...extra, confirm: true });
    }
    if (out.error && !out.ok) throw new Error(out.error);
    if (act === "run") toast(alias + ": " + (out.ok ? "一键开跑完成 ✓" : "开跑失败 ✗"), out.ok ? "ok" : "err");
    refresh(true);
  } catch (e) {
    toast(`${alias} ${act}: ${e.message}`, "err");
    refresh(true);
  }
}

function bindCardEvents(card, alias) {
  card.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === "face") return uploadFace(alias);
    if (act === "edit") return openRegistry(state.devices.find(d => d.alias === alias));
    if (act === "log") return openDrawer("modlog", alias);
    if (act === "run") {
      const d = state.devices.find(x => x.alias === alias);
      if (d && d.rs.state === "playing") {
        const yes = await askConfirm("一键开跑 (覆盖确认)",
          `${alias} 的 RS 实例正在播放 (state=playing)。继续将先停掉当前播放, 然后重新预置→连接→开跑。确认?`);
        if (!yes) return;
        return deviceAction(alias, "run", { confirm: true });
      }
      if (d && d.rs.state === "error") {
        const yes = await askConfirm("一键开跑 (error 恢复确认)",
          `${alias} 的 RS 实例处于 error (${d.rs.error || "未知错误"})。继续将重新预置并重连, 覆盖错误现场。确认?`);
        if (!yes) return;
        return deviceAction(alias, "run", { confirm: true });
      }
      return deviceAction(alias, "run");
    }
    if (act === "stop") {
      const d = state.devices.find(x => x.alias === alias);
      if (d && (d.rs.state === "playing" || d.rs.state === "paused")) {
        const yes = await askConfirm("停止播放",
          `${alias} 正在跑步 (state=${d.rs.state})。将停守卫→停注入→断连。\n确认停止?`);
        if (!yes) return;
        return deviceAction(alias, "stop", { confirm: true });
      }
      if (d && d.rs.state === "error") {
        const yes = await askConfirm("停止 (error 态)",
          `${alias} 的 RS 实例处于 error。未经确认不会动 RS (保留错误现场); 确认后将尽力 disconnect 重置实例。\n确认?`);
        if (!yes) return;
        return deviceAction(alias, "stop", { confirm: true });
      }
      return deviceAction(alias, "stop");
    }
    const map = { guard: null, bridge: null };
    if (act in map) {
      const d = state.devices.find(x => x.alias === alias);
      const running = act === "guard" ? d.guard.running : d.bridge.running;
      return deviceAction(alias, running ? `${act}-stop` : `${act}-start`);
    }
    return deviceAction(alias, act);
  });
}

/* ---------- main render ---------- */
const state = { devices: [], unregistered: [] };

async function refresh(force = false) {
  try {
    const ov = await api("/api/overview");
    state.devices = ov.devices;
    state.unregistered = ov.unregistered;
    $("#conn-dot").classList.remove("bad");
    $("#last-refresh").textContent = new Date().toLocaleTimeString();
    renderUnregistered();
    renderGrid(force);
    if ($("#drawer").classList.contains("open")) autoReloadDrawer();
  } catch (e) {
    $("#conn-dot").classList.add("bad");
    $("#last-refresh").textContent = "刷新失败: " + e.message;
  }
}

function renderUnregistered() {
  const wrap = $("#unreg-wrap"), el = $("#unreg");
  if (!state.unregistered.length) { wrap.style.display = "none"; return; }
  wrap.style.display = "";
  el.innerHTML = state.unregistered.map(u =>
    `<div class="item">
      <span class="badge ${u.state === "device" ? "usb" : "off"}">${u.state === "device" ? "在线" : u.state}</span>
      <b>${u.model || u.serial}</b>
      <span style="color:var(--dim)">${u.serial}</span>
      <button class="small" data-serial="${u.serial}" data-model="${u.model || ""}">登记</button>
    </div>`).join("");
  el.querySelectorAll("button[data-serial]").forEach(b =>
    b.onclick = () => { openRegistry(null); $("#reg-serial").value = b.dataset.serial; $("#reg-port").value = ""; });
}

function renderGrid(force) {
  const grid = $("#grid");
  const old = new Map();
  grid.querySelectorAll(".card").forEach(c => old.set(c.id, c));
  state.devices.forEach(d => {
    let card = old.get("card-" + d.alias);
    const sig = [d.rs.state, d.channel.via, d.channel.model, d.guard.running, d.bridge.running,
                 d.busy, d.face, d.face_mtime, d.rs.route_name].join("|");
    if (!card || force || card._sig !== sig) {
      const tmp = document.createElement("div");
      tmp.innerHTML = cardHtml(d);
      const nc = tmp.firstElementChild;
      nc._sig = sig;
      if (card) grid.replaceChild(nc, card); else grid.appendChild(nc);
      bindCardEvents(nc, d.alias);
      card = nc;
    }
    renderPipe(card, d.pipeline);
  });
  // 移除已消失的卡片
  const aliases = new Set(state.devices.map(d => d.alias));
  grid.querySelectorAll(".card").forEach(c => {
    if (!aliases.has(c.id.replace("card-", ""))) c.remove();
  });
}

/* ---------- log drawer ---------- */
const drawer = $("#drawer"), logbox = $("#logbox"), tabsEl = $("#log-tabs");
let drawerTab = null, drawerAlias = null, logTimer = null;

async function openDrawer(tab, alias) {
  drawerTab = tab; drawerAlias = alias || null;
  drawer.classList.add("open");
  await loadLog();
}
$("#drawer-close").onclick = () => { drawer.classList.remove("open"); clearInterval(logTimer); };

function tabDefs() {
  const devTabs = state.devices.map(d => ({ key: "modlog:" + d.alias, label: `${d.alias} 模块日志` }));
  const guardTabs = state.devices.filter(d => d.guard.running || d.guard.log_path)
    .map(d => ({ key: "guard:" + d.alias, label: `${d.alias} 守卫` }));
  return [...devTabs, ...guardTabs, { key: "events", label: "WebUI 事件" }];
}

async function loadLog() {
  const defs = tabDefs();
  const activeKey = drawerTab === "modlog" && drawerAlias ? "modlog:" + drawerAlias
    : drawerTab === "events" ? "events" : drawerTab;
  tabsEl.innerHTML = defs.map(t =>
    `<button class="small ${t.key === activeKey ? "active" : ""}" data-k="${t.key}">${t.label}</button>`).join("");
  tabsEl.querySelectorAll("button").forEach(b => b.onclick = () => {
    const [kind, alias] = b.dataset.k.split(":");
    openDrawer(kind === "events" ? "events" : kind, alias);
  });
  try {
    if (activeKey === "events") {
      const d = await api("/api/events");
      logbox.textContent = d.events.map(e =>
        `[${new Date(e.ts * 1000).toLocaleTimeString()}] ${e.alias} ${e.kind}: ${e.text}`).join("\n") || "(空)";
    } else if (activeKey.startsWith("modlog:")) {
      const alias = activeKey.split(":")[1];
      const d = await api("/api/device-log?alias=" + encodeURIComponent(alias));
      logbox.textContent = d.log + `\n(通道: ${d.channel || "设备不在线"})`;
    } else {
      const ov = await api("/api/overview");
      const dev = ov.devices.find(x => x.alias === activeKey.split(":")[1]);
      const kind = activeKey.split(":")[0];
      logbox.textContent = (dev?.[kind]?.log_tail) || "(无日志)";
    }
  } catch (e) { logbox.textContent = "读取失败: " + e.message; }
}
function autoReloadDrawer() { if (drawer.classList.contains("open")) loadLog(); }

/* ---------- global buttons ---------- */
$("#btn-events").onclick = () => openDrawer("events");

let timer = null;
$("#auto-refresh").onchange = () => {
  clearInterval(timer);
  if ($("#auto-refresh").checked) timer = setInterval(() => refresh(), 2000);
};
timer = setInterval(() => refresh(), 2000);
refresh(true);
