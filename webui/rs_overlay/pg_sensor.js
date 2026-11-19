/* paceghost 传感器配置卡片 — 由运动参数自动推导计步配置.
   算法 (锚定 RUNBOOK 实测): cadence = 速度m/min ÷ (身高m) × (1 + 左右摆动增益)
   摆动增益 ≈ lateral_variation_m ÷ 50 (锚点: 1.5m → +3%, 13.33km/h@175cm → 127→131).
   应用到设备: 写 jrstep_cadence + jrstep_on=1 (走 paceghost WebUI), 已登记设备同步 devices.json. */
(() => {
  "use strict";
  const WEBUI = "http://127.0.0.1:8800";
  const $ = (id) => document.getElementById(id);
  const elCad = $("pg-cadence"), elStride = $("pg-stride"), elLp = $("pg-lp");
  const elHeight = $("pg-height"), btn = $("pg-cadence-apply"), status = $("pg-sensor-status");
  if (!elCad || !btn) return;

  const LS_KEY = "pg_height_cm";
  try {
    const saved = localStorage.getItem(LS_KEY);
    if (saved) elHeight.value = saved;
  } catch (e) { /* localStorage 不可用则用默认 175 */ }
  elHeight.addEventListener("change", () => {
    try { localStorage.setItem(LS_KEY, elHeight.value); } catch (e) {}
    recompute();
  });

  // 运动参数表单任一输入变化都触发重算
  const motionInputs = () => ["speed", "lateral_variation_m", "interval", "speed_variation_pct"]
    .map((id) => document.getElementById(id)).filter(Boolean);
  motionInputs().forEach((inp) => inp.addEventListener("input", recompute));
  const form = document.getElementById("settings");
  if (form) form.addEventListener("submit", () => setTimeout(recompute, 50));

  function params() {
    const num = (id, dflt) => {
      const el = document.getElementById(id);
      const v = el ? parseFloat(el.value) : NaN;
      return Number.isFinite(v) ? v : dflt;
    };
    return { speed: num("speed", 13.33), lateral: num("lateral_variation_m", 1.5) };
  }

  function compute() {
    const { speed, lateral } = params();
    const strideCm = parseFloat(elHeight.value) || 175;
    const lateralGain = Math.max(0, lateral) / 50;          // 1.5m -> +3% (实测锚点)
    const base = speed * 1000 / 60 / (strideCm / 100);      // stride_sync.py 原式
    const cadence = Math.max(80, Math.min(220, Math.round(base * (1 + lateralGain))));
    const strideM = cadence > 0 ? (speed * 1000 / 60) / cadence : 0;
    return { cadence, strideM, base: Math.round(base), gainPct: Math.round(lateralGain * 100) };
  }

  function recompute() {
    const { cadence, strideM, base, gainPct } = compute();
    elCad.textContent = `${cadence} 步/分 (基础 ${base} +${gainPct}%)`;
    elStride.textContent = `${strideM.toFixed(2)} m`;
  }

  async function refreshLp() {
    try {
      const st = await fetch("/api/status", { cache: "no-store" }).then((r) => r.json());
      const o = (st.diagnostics || {}).options || {};
      elLp.textContent = o.gps_accuracy ? `GPS ${o.gps_accuracy}m · network ${o.network_accuracy}m/${o.network_interval}s` : "GPS 5m · network 50m/5s (默认)";
      btn.disabled = !st.udid;
      btn.title = st.udid ? "写入 jrstep_cadence + jrstep_on=1" : "连接设备后可用";
    } catch (e) {
      elLp.textContent = "GPS 5m · network 50m/5s (默认)";
    }
  }

  btn.addEventListener("click", async () => {
    try {
      const st = await fetch("/api/status", { cache: "no-store" }).then((r) => r.json());
      if (!st.udid) { setStatus("设备未连接, 先在扫描卡连接"); return; }
      const { cadence } = compute();
      btn.disabled = true;
      setStatus(`写入 cadence=${cadence} → ${st.udid} …`);
      const r = await fetch(WEBUI + "/api/step-cadence", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ serial: st.udid, cadence }),
      }).then((x) => x.json());
      setStatus(r.detail || (r.ok ? "已写入" : "失败: " + (r.error || "")));
    } catch (e) {
      setStatus("失败: " + e.message);
    } finally {
      btn.disabled = false;
    }
  });

  function setStatus(text) { status.textContent = text; }

  recompute();
  refreshLp();
  setInterval(refreshLp, 4000);
})();

/* ---- 为什么点不动: 把 RS 的禁用原因显式化 (只读观察, 不改 RS 逻辑) ---- */
(() => {
  "use strict";
  const hint = document.getElementById("pg-locked-hint");
  const importBtn = document.getElementById("player-import");
  if (!hint || !importBtn) return;

  function refresh() {
    const iframeNone = null; // 占位, 保持结构
    let state = null;
    try {
      // 复用 RS 自己渲染到 #play-state 的文案做粗判, 再拉一次 status 更准
      state = document.querySelector("#play-state")?.textContent || "";
    } catch (e) { /* ignore */ }
    fetch("/api/status", { cache: "no-store" })
      .then((r) => r.json())
      .then((st) => {
        const playing = st.state === "playing", paused = st.state === "paused";
        if (playing || paused) {
          hint.textContent = `⚠ 正在${playing ? "播放" : "暂停"}中：导入/替换路线与修改运动参数被 Route Studio 锁定。`
            + `先点「${playing ? "停止并清除模拟" : "停止"}」再换路线。`;
          hint.classList.add("show");
        } else {
          hint.classList.remove("show");
        }
      })
      .catch(() => hint.classList.remove("show"));
  }
  refresh();
  setInterval(refresh, 2000);
})();
