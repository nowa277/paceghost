/* paceghost USB 设备扫描卡片 — 嵌入 Route Studio 页面.
   扫描数据来自 paceghost WebUI (127.0.0.1:8800, 只读跨源);
   "连接"直接调本实例 RS /api/connect, 复用 RS 自身的注入模式探测. */
(() => {
  "use strict";
  const WEBUI = "http://127.0.0.1:8800";
  const $ = (id) => document.getElementById(id);
  const list = $("pg-scan-list"), status = $("pg-scan-status"), btn = $("pg-scan-btn");
  if (!list || !status || !btn) return;

  let registry = {};      // alias -> dev (从 WebUI 拉, 用于显示别名 chip)
  let timer = null;
  let busy = false;

  const dotCls = (state) => state === "device" ? "ok" : state === "unauthorized" ? "warn" : "err";
  const stateText = (state) =>
    state === "device" ? "在线" : state === "unauthorized" ? "待授权" : state === "offline" ? "离线" : state;
  const isWifi = (serial) => serial.includes(":");
  const aliasOf = (serial, devices) => {
    for (const [alias, dev] of Object.entries(registry || {})) {
      if (dev.serial === serial) return alias;
      if (dev.wifi && serial.startsWith(dev.wifi.split(":")[0] + ":")) return alias;
    }
    // 未登记但 serial 能对上其他通道的也标 alias
    for (const [alias, dev] of Object.entries(registry || {})) {
      if (dev.serial === serial.replace(/:\d+$/, "")) return alias;
    }
    return "";
  };

  function setStatus(text) { status.textContent = text; }

  async function scan() {
    if (busy) return;
    busy = true;
    btn.disabled = true;
    try {
      const [devs, reg] = await Promise.all([
        fetch(WEBUI + "/api/adb-list", { cache: "no-store" }).then((r) => r.json()),
        fetch(WEBUI + "/api/registry", { cache: "no-store" }).then((r) => r.json()).catch(() => null),
      ]);
      registry = (reg && reg.devices) || {};
      render(devs.devices || []);
      setStatus("上次扫描 " + new Date().toLocaleTimeString());
    } catch (e) {
      list.innerHTML = '<li class="pg-empty">WebUI 未运行 — 先启动: python3 -m webui.main --port 8800</li>';
      setStatus("");
    } finally {
      btn.disabled = false;
      busy = false;
    }
  }

  function render(devices) {
    if (!devices.length) {
      list.innerHTML = '<li class="pg-empty">未发现设备 — 检查数据线 / 手机已开「USB 调试」/ 弹窗已允许授权</li>';
      return;
    }
    const selfPort = Number(location.port) || 0;
    list.innerHTML = devices.map((d) => {
      const wifi = isWifi(d.serial);
      const alias = aliasOf(d.serial, devices);
      const selfDev = alias && registry[alias] && Number(registry[alias].port) === selfPort;
      const conn = d.state === "device"
        ? `<button type="button" data-serial="${d.serial}">连接</button>` : "";
      const faceTip = aliasFace(alias) ? "当前: " + aliasFace(alias) : "上传新图 (magick 裁 1080x1920 后推送)";
      const face = d.state === "device"
        ? `<button type="button" data-face="${d.serial}" title="${faceTip}">人脸</button>` : "";
      return `<li${selfDev ? ' class="pg-self"' : ""}>
        <span class="pg-dot ${dotCls(d.state)}" title="${stateText(d.state)}"></span>
        <span class="pg-model" title="${d.serial}">${d.model || (wifi ? "Wi-Fi 设备" : "(未知型号)")}</span>
        <span class="pg-serial">${d.serial}</span>
        ${alias ? `<span class="pg-chip" title="devices.json 已登记">${alias}</span>` : ""}
        ${selfDev ? '<span class="pg-chip pg-self-chip" title="devices.json 里登记到本页端口的设备">本实例</span>' : ""}
        <span class="pg-via">${wifi ? "Wi-Fi" : "USB"}</span>
        ${conn}${face}
      </li>`;
    }).join("");
  }

  function aliasFace(alias) {
    return (registry && alias && registry[alias] && registry[alias].face) || "";
  }

  // ---- 人脸上传 (走 paceghost WebUI /api/face; 未登记设备按 serial 直推) ----
  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = "image/png,image/jpeg";
  fileInput.hidden = true;
  document.body.appendChild(fileInput);
  let faceSerial = null;

  fileInput.addEventListener("change", async () => {
    const f = fileInput.files[0];
    fileInput.value = "";
    if (!f || !faceSerial) return;
    if (!/^[\w\-. ]+$/.test(f.name.replace(/\.(png|jpe?g)$/i, ""))) {
      setStatus("上传取消: 文件名须为 ASCII, 请先重命名");
      return;
    }
    setStatus("人脸处理中 (" + faceSerial + ")…");
    try {
      const buf = new Uint8Array(await f.arrayBuffer());
      let bin = "";
      for (let i = 0; i < buf.length; i += 0x8000)
        bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
      const r = await fetch(WEBUI + "/api/face", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ serial: faceSerial, filename: f.name, data_b64: btoa(bin) }),
      }).then((x) => x.json());
      setStatus(r.detail || (r.ok ? "人脸已推送" : "上传失败"));
      scan();
    } catch (e) {
      setStatus("上传失败: " + e.message);
    }
  });

  list.addEventListener("click", (ev) => {
    const faceBtn = ev.target.closest("button[data-face]");
    if (faceBtn) {
      faceSerial = faceBtn.dataset.face;
      fileInput.click();
      return;
    }
    handleConnect(ev);
  });

  async function handleConnect(ev) {
    const b = ev.target.closest("button[data-serial]");
    if (!b) return;
    const serial = b.dataset.serial;
    b.disabled = true;
    // 1) 设备预置 (appops/定位开关/jrstep/jrface/清残留) — 换机后必须, WebUI 不可达则降级为裸连接
    b.textContent = "预置中…";
    let prep = null;
    try {
      prep = await fetch(WEBUI + "/api/prepare", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ serial, requester_port: Number(location.port) || 0 }),
      }).then((x) => x.json());
    } catch (e) {
      prep = { ok: false, error: "WebUI 不可达" };
    }
    if (prep && prep.ok === false && prep.error) {
      setStatus("预置失败: " + prep.error);
      b.textContent = "连接";
      b.disabled = false;
      return;
    }
    // 2) 本实例 connect
    b.textContent = "连接中…";
    const body = isWifi(serial)
      ? { platform: "android", address: serial }
      : { platform: "android", udid: serial };
    try {
      const r = await fetch("/api/connect", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then((x) => x.json());
      if (r.error) {
        // 自愈: 实例绑着别的 (已拔) 设备时, connect 只会向死设备重发坐标而失败
        const st = await fetch("/api/status", { cache: "no-store" }).then((x) => x.json()).catch(() => null);
        const selfAlias = Object.keys(registry || {}).find(
          (a) => Number(registry[a].port) === Number(location.port));
        if (st && st.connected && st.udid && st.udid !== serial
            && st.state !== "playing" && selfAlias) {
          setStatus(`实例绑着旧设备 ${st.udid}, 重启实例自愈…`);
          const rr = await fetch(WEBUI + "/api/rs-restart", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ alias: selfAlias }),
          }).then((x) => x.json());
          if (!rr.ok) { setStatus("自愈失败: " + rr.error); b.textContent = "连接"; b.disabled = false; return; }
          await new Promise((res) => setTimeout(res, 1500));
          b.textContent = "连接中…";
          const r2 = await fetch("/api/connect", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }).then((x) => x.json());
          if (r2.error) {
            setStatus("重连失败: " + r2.error);
            b.textContent = "连接"; b.disabled = false;
          } else {
            const mode = (r2.diagnostics || {}).mode || "?";
            setStatus((prep && prep.ok ? "预置✓ 自愈重连成功 · mode=" : "自愈重连成功 · mode=") + mode);
            b.textContent = "已连接 ✓";
            setTimeout(() => { b.textContent = "连接"; b.disabled = false; }, 4000);
          }
          return;
        }
        setStatus("连接失败: " + r.error + (prep && prep.ok ? " (预置已完成, 可重试)" : ""));
        b.disabled = false;
        b.textContent = "连接";
      } else {
        const mode = (r.diagnostics || {}).mode || "?";
        setStatus((prep && prep.ok ? "预置✓ 已连接 " : "已连接(未预置,WebUI未跑) ") + serial + " · mode=" + mode);
        b.textContent = "已连接 ✓";
        setTimeout(() => { b.textContent = "连接"; b.disabled = false; }, 4000);
      }
    } catch (e) {
      setStatus("连接失败: " + e.message);
      b.disabled = false;
      b.textContent = "连接";
    }
  }

  btn.addEventListener("click", scan);
  $("pg-scan-auto").addEventListener("change", (e) => {
    clearInterval(timer);
    if (e.target.checked) timer = setInterval(scan, 5000);
  });
  scan();
})();
