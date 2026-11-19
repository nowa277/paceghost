# 机型兼容矩阵

目的: 让工具链在尽量多的机型/ROM 上开箱即用, 消除"每换一台新机就要人工重调"。
维护规则: 每台新机接入后回填矩阵行; 坑条目随修随更; 引用一律给 文件:行 号或出处 URL; 查不到公开佐证标【待验证】, 不编造。
更新: 2026-11-17 (首批 3 机 + 8 条会话实测坑 + 外部资料佐证)

## 1. 已登记机型

| 别名 | 机型 / ROM | Android | USB 序列号 | 注入模式 | 分辨率 | RS 端口 | WiFi adb | 状态 |
|---|---|---|---|---|---|---|---|---|
| vivo | vivo V2278A / Funtouch OS 13 | 13 (SDK 33) | 10CD9D0FR0001JD | testprovider | 1080x2388 | 8765 | 192.168.1.137:5555 | 可用 |
| huawei | 华为 CDY-AN00 / EMUI 10 | 10 (SDK 29) | MKB4C20611016287 | settings | 1080x2400 | 8766 | 192.168.1.173:5555 | 可用 |
| honor | 荣耀 DNP-AN00 / MagicOS | 16 (SDK 36) | AHHSUT5519008815 | testprovider (实测确认) | 1264x2736 | 8767 | **WiFi adb 已开通** (家里 192.168.1.144:5555; 校园网仍不通, 坑 #6c) | **端到端已验证** (定位中→开始跑步亮蓝, USB/WiFi 双通道) |

登记事实源: devices.json:3-29。

- **注入模式自动探测**: mockrunning 的 android.py 探测 `cmd location help` 是否含 set-test-provider-location → 有则 mode=testprovider (ADB 路径), 无则 mode=settings (写 Settings.Global.jrpos, LSPatch 模块 GpsFeed 进程内 addTestProvider)。会话事实, 无仓库内文件行可引。
- **honor 全程 USB-only**: 该机连校园网 GDMU-UNICOM (172.17.x), 与 PC (192.168.1.x) 异网段, WiFi adb 永远不可达, devices.json:23 wifi=null。
- **huawei**: `cmd location` 整个被裁 (`No shell command implementation`), 定位总开关用 `settings put secure location_mode 3` (RUNBOOK.md:138-143)。
- honor 行待实机跑通 `scripts/joyrun_switch.sh honor --start` 后回填 mode 实测值并改"可用"。
- 已知小现象: route-studio@honor (8767) 空闲态 status 返回 platform=ios (实例状态文件残留); connect 时显式发 platform=android, 自纠, 无需处理。

## 2. 已知坑清单

状态定义: **已修复**=脚本已固化; **已固化**=实测结论/操作规范, 无需改码; **待修复**=坑已确认但脚本未固化; **待验证**=未经实机复现或无外部佐证。

### #1 vivo: WiFi adb 重连后 `cmd location` 定位总开关被重置 — 已修复
- 现象: WiFi adb 断开重连后, testprovider 注入失效, 因为定位总开关被重置。
- 修复: 设备预置段**无条件**补开, 幂等且对全机型无害 (`|| true` 吞掉华为 cmd location 被裁剪的非零退出, 防止 set -e 中断):
  - scripts/joyrun_switch.sh:45-46
  - scripts/joyrun_new_device.sh:53-54
- 外部佐证: 未查到公开资料描述该现象, 以本机实测为准【待验证-机型特异性】(见 §3)。

### #2 截图坐标是缩放渲染图, `input tap` 必须用真机物理像素 — 已固化
- 规范: 用 `uiautomator dump` 的 bounds, 或在原始 PNG 里按颜色定位。
- 已知锚点: vivo 开始卡片蓝块 bbox 96 924 496 1380。

### #3 `adb tcpip 5555` 会杀掉 USB transport — 待修复 (操作规避)
- 恢复: `adb kill-server && adb start-server`。
- scripts/joyrun_wifi.sh:13,46 只做 tcpip+connect, 未固化该自愈; 需要保留 USB 通道时手动执行。

### #4 LSPatch 签名冲突 INSTALL_FAILED_UPDATE_INCOMPATIBLE — 已固化
- 目标机已有同包名 stock 签名应用时, `install -r` 必失败; 必须先 uninstall (会丢登录态)。
- 装完校验: `dumpsys package com.joyrunworld.app` 的 signatures 与 sha256。

### #5 `run-as` 在非 debuggable 包上失败 — 已固化
- 看 app 私有目录用 v8 Diag 模块: `settings put global jrdiag 1` + 重启 app → 读 /sdcard/Android/data/com.joyrunworld.app/files/diag.txt。

### #6 荣耀 DNP-AN00 / Android 16 (SDK 36) 四项实测 — 已固化
- (a) logcat 反复报 com.bytedance.apm `protocol TLSv1 is not supported`, 无害。外部机制佐证: Android 15 起 Conscrypt 对 targetSdk>=35 应用禁用 TLS 1.0/1.1 (source.android.com/docs/core/ota/modular-system/conscrypt; developer.android.com/about/versions/15/behavior-changes-15), Android 16 行为变更无新增 TLS 条目 (developer.android.com/about/versions/16/behavior-changes-all) → 归因置信度中。
- (b) 「系统繁忙」是服务端 msg 原样弹出, 非客户端 bug: base.apk 2129 entry 0 命中, v9 补丁包 0 命中, libapp.so UTF-8/UTF-16 0 命中; 对照组 加载失败=33 / 网络异常=11 / 重试=47。
- (c) 在学校连校园网 GDMU-UNICOM (172.17.x) 与 PC (192.168.1.x) 异网段 → WiFi adb 不可达, 只能 USB (devices.json:23)。**仅限学校场景**: 在家已实测开通 WiFi adb (2026-11-18, tcpip 5555 + kill-server 自愈 + connect 192.168.1.144:5555, devices.json wifi 已登记, RS 经 WiFi 地址 connect mode=testprovider 成功); 回学校后此通道失效, 恢复 USB-only。
- (e) 2026-11-18 凌晨实测: 注入链路全通 (connect → mode=testprovider → state=playing, gps provider 收到 mock 坐标)。~~「加载失败+系统繁忙」为窗口外拒绝~~ **修正**: 真实根因是该机 app 从未登录 (见坑 #10); 用户完成登录后数据全部恢复, 注入开启后运动页 GPS 亮三格、蓝点落操场、「开始跑步」亮蓝 (02:10 截图确认)。「定位中」灰按钮在注入停止时是预期状态, 非故障。
- (d) 首次拉起时运动页「定位中」是 jrpos/jrgps_feed 均为 null (注入未配置), 不是故障。
- 附加 (官方资料, 置信度高): MagicOS 省电策略会停掉后台运动类定位, 需对该 app 关闭电池优化/多任务加锁 (honor.com 官方支持文档 honor.com/cn/support/content/zh-cn00428704/) → 荣耀长跑前检查此项【待验证-实机必要性】。

### #7 目标 app 接口清单 (从 libapp.so 抠出) — 已固化
- base https://apiapp.joyrunworld.cn; 核心端点: /sch/run/checkUnFinish、/sch/run/checkRunUpperLimit、/sch/run/start、/sch/run/finish、/sch/run/faceDetect、/sch/student/baseInfo、/sch/student/local/query、/sch/student/bind、/sys/semester/list、/sys/school/list 等。
- 全集见 docs/HANDOFF.md:50-58。

### #8 app 本地持久化近乎为空 — 已固化
- 悦跑本体 shared_prefs 仅一个 65B 空 `<map/>` (3687895362eff697723e1121c5aa9355.xml) + 大量广告 SDK prefs; 「累计跑步 xx 公里」等数据均为服务端返回, 本地无状态可改。

### #9 MagicOS 自动拆除 adb test provider, mockrunning 注入循环无容错 — 待修复
- 2026-11-18 凌晨 honor 实测两次拆除: 01:11:43 (add 后 17s) 与 01:27:04 (add 后 168s); 两次拆除均伴随 com.hihonor.lbs (uid 1000, 荣耀系统 LBS) 的「模拟位置」告警通知在 3-5ms 后被撤销 (notification_canceled reason=8, 通知 flags=ONGOING|AUTO_CANCEL|actions=1, 发出时刻=add 后 ~30ms)。
- 拆除方是系统侧, 排除法: GpsFeed 未激活 (jrgps_feed=null, jrpatch.log 无 gpsfeed 行, GpsFeed.java:85 条件不满足); mockrunning 自身 clear 只在 stop/close 路径 (android.py:233); shell 注入循环只调 set-test-provider-location。
- 触发条件未钉死【待验证】: 两次拆除都发生在「app 进入新的定位场景」时 (启动 onResume 后 0.3s / 切运动页地图后 0.1s); 对照组: app 停留在已渲染页面时 provider 存活 40s~5min+ (受控实验: 重连后不碰手机 40s 无拆除; adb input tap 后也无拆除 —— 注入式输入不是触发条件); LBS 服务自身持续消费 mock 位置 (HnNLPPositionManager update gps location ... mock) 却不拆除。无固定周期, 非纯定时器。
- 后果: mockrunning testprovider 注入循环 (playback.py:251-256) 遇 `gps provider is not a test provider` 即 state=error → _close_device → 断开, 整条链路死。
- 缓解/修复选项 (按推荐序):
  1. PC 侧看门狗: 轮询 8767 status, state=error 时自动重新 connect+start (零 mockrunning 改动, 对任何拆除原因都兜底, 代价是每次拆除有几秒注入空窗)。
  2. 强制 settings 模式: GpsFeed 每拍 `!gpsReady && ensureProvider()` 自愈重挂 (GpsFeed.java:153), 被拆 200ms 内恢复; 但 mockrunning connect() 只按 `cmd location help` 探测无强制入口 (android.py:151), 需加 env 开关或 connect 参数 (改 mockrunning ~3 行); MagicOS 是否同样清理 app 进程内 provider 未知【待验证】。
- 无害观察: 注入的 Location 的 et 显示为设备 uptime (+17d), 是 shell 构造 Location 的 elapsedRealtimeNanos 缺省 0 所致, vivo 同代码路径端到端已验证不受影响。

### #10 新机装完补丁包 ≠ 有登录态: 未登录时全页面「加载失败+系统繁忙」— 已固化 (onboarding 检查项)
- 2026-11-18 荣耀实锤: app 全新安装后未完成登录 → 首页/运动页数据请求全被服务端拒 (加载失败 + toast 系统繁忙), 我的页顶部用户信息永久转圈, 跑步记录看不到; 与跑步窗口无关 (同账号同时刻在 vivo 上一切正常)。
- 取证方法 (可复用): `settings put global jrdiag 1` + 重启 app → pull diag.txt → 检查 **FlutterSharedPreferences / FlutterSecureStorage 是否存在** (160 个 prefs 全是广告 SDK = 未登录), cookieStore 无 joyrunworld.cn 会话。登录后这些文件生成, 数据恢复。取证完记得 `jrdiag 0`。
- 注意: app 的 Dart 层网络不走系统代理, mitm 抓不到 joyrunworld API (vivo 时代 150 条 flow 亦无 joyrunworld), 别再走抓包弯路。
- 待固化: joyrun_new_device.sh 应加登录校验步骤 (diag 法查 Flutter prefs), 未登录时提示用户先登录。

## 3. 资料佐证 (外部检索, 2026-11-17)

- tcpip 5555 非持久化, 手机重启后复位; Android 11+ 无线调试开关随 WiFi 断开自动关 (置信度高) → 与 joyrun_wifi.sh:44-51 的 USB 自愈逻辑吻合。
- `location_providers_allowed` 自 API 30 失效; `location_mode` (0=关/3=高精度) 是现行定位主开关, shell 可写 (置信度中高) → 与 RUNBOOK.md:140 华为做法一致; EMUI 上写入与 UI/服务的联动未实测【待验证】。
- vivo 长时间 adb 连接可能自动关闭开发者选项 (Airtest 官方 FAQ, 置信度中) → vivo 长跑前确认开发者选项仍开【待验证-机型特异性】; 另有三方称 Funtouch OS 13 模拟位置入口藏得很深 (置信度低中, 仅作提示)。
- Android 14/15/16 官方行为变更列表均无 adb mock location / test provider 平台级收紧条目 (置信度高)。
- 通用: 部分自定义 `settings put global` 值重启后回滚 (置信度中); shell 写自定义 global key 的能力未查到版本收紧记录【待验证】。
- 荣耀近年收紧 adb 面 (CVE-2025-57840 修复公告, honor.com 安全公告) 【待验证-对本工具链影响】。

## 4. 待办

1. honor 真跑验证: 06:00 窗口后真跑一段确认记录有效 (端到端按钮验证已于 02:10 完成); 同时观察坑 #9 的拆除是否再现。
2. 决策坑 #9 修复路线: PC 看门狗 (推荐, 零改动) vs 强制 settings 模式 (需改 mockrunning ~3 行)。
3. joyrun_new_device.sh 增加登录校验步骤 (坑 #10)。
4. ~~honor 开 WiFi adb~~ 已完成 (2026-11-18, 家里 192.168.1.144:5555, RS WiFi 通道实测通过); 回学校后恢复 USB-only。
5. joyrun_wifi.sh 视需要固化坑 #3 的 kill-server 自愈。
6. 新机型接入统一走 scripts/joyrun_new_device.sh, 接入后回填本矩阵。
