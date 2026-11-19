# paceghost WebUI — Route Studio 多机管理控制台

RS (Route Studio) 之上的管理层: 多机总览、一键开跑、人脸守卫/桥进程管理、设备登记。
**零第三方依赖** (纯 Python stdlib + vanilla JS), 不改 mockrunning 注入逻辑, 不碰 systemd。

## 启动

```bash
cd /home/sesley/Workspace/paceghost
python3 -m webui.main --port 8800        # 默认 8800, 仅监听 127.0.0.1
# 浏览器打开 http://127.0.0.1:8800
```

前提: RS 实例已在跑 (`systemctl --user enable --now route-studio@<别名>`), PC 上 adb 可用
(`~/.local/bin/adb`, 换路径改 `webui/adbtools.py` 的 `ADB` 或设 `WEBUI_ADB` 环境变量)。

## RS 页面内嵌卡片 (refs/mockrunning static 的最小改动, RS 后端零改动)

「手机回放」侧栏现有两张 paceghost 卡片 (连接方式 fieldset 已隐藏, 默认平台改为
android —— 隐藏而非删除以保 RS app.js 的 DOM 引用不崩):

- `static/pg_scan.js`: **USB 设备扫描卡** — adb 在线设备 (绿/黄/红状态点), 型号+序列号+
  devices.json 别名 chip+通道; 本页端口登记的设备行高亮并标「本实例」。
  「连接」= **预置→连接→自愈** 三步: 先 `POST /api/prepare` 做设备预置 (appops mock_location/
  定位总开关/jrstep/jrface/清残留 —— 换机后必须, 否则无法开始跑步), 再调本实例 /api/connect;
  连接失败且实例绑着别的死设备 (playback.py connect 只向旧绑定重发坐标) 时, 自动
  `POST /api/rs-restart` 重启该 systemd 实例 (playing 态拒绝) 并重连一次。「人脸」上传新图
  (magick 裁 1080x1920 推送, 已登记自动归档, 未登记按序列号直推)
- `static/pg_sensor.js`: **传感器配置卡** — 由运动参数自动推导:
  `cadence = 速度m/min ÷ (身高m/100) × (1 + 左右波动m/50)`
  锚点: 13.33km/h@175cm+1.5m摆动 → 127→131 (RUNBOOK 实测)。步幅恒为 身高/(1+增益)。
  「应用步频到设备」写 jrstep_cadence+jrstep_on=1 并同步 devices.json.cadence;
  运动参数表单任一输入变化自动重算; 定位测试源显示 RS 当前 options。
- `static/index.html` (+4 处): 两张卡容器 + 2 个 script 标签 + fieldset hidden
- `static/app.css` (追加两段): 卡片样式, 复用 RS 设计变量

## 控制台 (多机总览) 与 RS 卡片的分工 — 去重后

| 能力 | RS 扫描卡片 (单机页) | paceghost 控制台 (8800, 多机) |
|---|---|---|
| 设备扫描/识别 | ✓ (主动扫描+自动轮询) | 被动展示 (未登记设备列表) |
| 连接/断开单实例 | ✓ | ✗ (已删, 与 RS 卡片重复) |
| 人脸上传 | ✓ (按设备) | ✓ (换图按钮) |
| 一键开跑全流程 (预置→人脸→connect→settings→start→守卫) | ✗ | ✓ |
| 一键停止 / 守卫 / jrpos 桥 | ✗ | ✓ |
| devices.json 登记/编辑 | ✗ | ✓ |
| 模块日志 (jrpatch.log) 查看 | ✗ | ✓ |

控制台每张设备卡: 通道(USB/WiFi/离线+型号) / RS state / 实时坐标·里程·用时·圈数 /
注入模式 / 人脸图版本 / 守卫·桥状态 / 错误信息 / 流水线步骤结果。
一键开跑 = 通道解析(USB 优先) → 预置(appop/cadence/jrface_on/清残留/jrdevice opt-in) →
magick 推人脸 → RS connect → settings 整包 → 起守卫 → start。**只动目标端口**。
devices.json 每次保存自动备份 `devices.json.bak-<时间戳>` (留最近 10 份)。

## API (全部 127.0.0.1, Host/Origin 校验同 RS)

```
GET  /api/overview                     # 总览 (devices + unregistered + 各实例状态聚合)
GET  /api/adb-list                     # adb devices -l 解析 (只读, CORS 放行 localhost 源, RS 卡片用)
GET  /api/events                       # WebUI 事件流
GET  /api/registry                     # devices.json (GET 只读跨源; POST 整体保存, 自动备份)
POST /api/devices/<别名>/run            # 一键开跑; playing/error 时需 {"confirm":true}
POST /api/devices/<别名>/stop           # 停守卫+停注入+断连; playing/error 时需 {"confirm":true}
POST /api/devices/<别名>/guard-start|guard-stop|bridge-start|bridge-stop
POST /api/devices/<别名>/connect|disconnect|start|pause|stop   # RS 透传 (connect 自动选通道)
POST /api/devices/<别名>/settings       # 7 字段整包
POST /api/face                         # {"alias"|"serial","filename","data_b64"} (CORS: localhost 源)
POST /api/step-cadence                 # {"serial","cadence"} 写 jrstep_cadence+jrstep_on, 同步 registry (CORS: localhost 源)
POST /api/prepare                      # {"serial"} 设备预置 (换机后补虚拟定位条件; CORS: localhost 源)
POST /api/rs-restart                   # {"alias"} 重启 RS systemd 实例自愈死绑定; playing 拒绝 (CORS: localhost 源)
GET  /api/device-log?alias=<别名>       # 设备端 jrpatch.log tail
```

## 安全红线落实

- 只监听 127.0.0.1; Host/Origin 白名单; JSON Content-Type 强制
- state=playing **和 error** 的 stop/disconnect/connect/run 一律要求显式 confirm (前端确认框 + 后端 `confirm_required` 标志双保险)
- 流水线绝不触碰其他 RS 端口 (不会复刻 joyrun_switch.sh 的"停所有实例")
- devices.json 每次写入先备份; 别名/文件名强制 ASCII snake_case
- **jrdevice 写入是 opt-in**: 仅当 devices.json 显式配置 `jrdevice` 字段且设备当前值为空时才写;
  已有值绝不覆盖, 未配置绝不凭空生成 (否则等于改设备标识, 反噬坑 #11); `jrdevice_rand 0` 幂等归零
- WebUI 启动时**收养**上一轮遗留的守卫/桥孤儿进程 (按 --serial 归属设备, 卡片显示 adopted),
  stop 按 pid 杀进程组 —— 防止双守卫同时 tap
- 不 git commit; 不碰 systemd 单元与 mockrunning 代码

## 已知限制

- 坑 #9 (MagicOS 拆 test provider): UI 提供 jrpos 桥启停作为兜底, 但 RS 自身 error 后
  自动重连看门狗仍属主会话决策范围, 本 UI 不自动重连
- `cmd location` 被裁剪的机型 (华为) 预置自动改走 `settings put secure location_mode 3`
- 人脸上传依赖设备在线; 设备离线时仅落盘本地, 上线后用卡片 Connect + 重新"换图"补推
- 事件/流水线记录存内存, WebUI 重启后清空 (guard/桥日志落盘在 webui/logs/)
- 启动时收养不了的孤儿 (serial 不匹配任何登记设备) 记在 `guard:orphan` 键下,
  不显示在 UI 上, 只打印到启动日志 —— 重启 WebUI 前别手动杀它们, 会被自动接管

## 真机测试清单 (设备接入后逐项过)

1. **扫描**: 插 USB → 点"扫描设备" → 卡片通道徽章变 USB + 显示型号
2. **一键开跑 (vivo, testprovider)**: state idle → 一键开跑 → 流水线 9 步全绿 → RS state=playing,
   蓝点绕圈; 守卫显示运行中
3. **一键开跑 (huawei, settings)**: 同上, 确认 `settings get global jrpos` 在变化 (GpsFeed 读 jrpos);
   预置步含 `location_mode 3`
4. **人脸弹窗**: 开跑 ~3min 等弹窗 → 守卫日志出现"点确定" → jrpatch.log 出现 `face: substituted`
5. **停止**: 卡片停止 → 确认弹窗 → state 回 idle, 守卫停止, `jrpos` 已清
6. **人脸换图**: 换图 → `ls -l` 设备 face_use.jpg 大小变化 → 下次弹窗用新图
7. **registry 编辑**: 改 cadence → 设备 `settings get global jrstep_cadence` 跟随
8. **坑 #9 演练** (honor): 触发拆除 → RS state=error → 卡片红框显示错误 → error 态一键开跑
   弹确认 → 确认后自动恢复
9. **双守卫防护**: WebUI 重启 → 启动日志出现 "adopted orphan" → honor 卡片守卫 running(adopted)
