# 悦跑世界 · 阶段一③完成 + 免root mock 链路打通 (HANDOFF2)
更新: 2026-11-16 00:50 · 基于 HANDOFF.md 的接续

## 0. 今晚核心成果 (全部实证)
1. **免 root mock GPS 链路全通**:
   `appops set 2000 android:mock_location allow`
   + `cmd location providers add-test-provider gps --requiresSatellite --supportsAltitude --supportsSpeed --supportsBearing`
   + `cmd location providers set-test-provider-enabled gps true`
   + `cmd location providers set-test-provider-location gps --location LAT,LON --accuracy N`
   → app (uid 10339) 经框架 gps provider 实时收到注入点 (dumpsys 位置计数器 +5/5 点铁证)
2. **app 不过滤 mock**: AMap SDK Utils.isGpsMock 是死代码 (无调用点);
   k/a 的 isMockLocationEnabled 只查 `getLastKnownLocation("gps"/"network").isFromMockProvider()`
   + AppOps(checkOp 自身uid)。实测注入 mock fix 后: 蓝点正常显示、围栏判定通过、
   "开始跑步"按钮激活。**开跑时未触发拦截** (提示弹窗只是"保持屏幕亮起")。
3. **围栏判定通过点**: WGS-84 22.9195,113.8630 (东莞松山湖校区东宿舍区) → "开始跑步"激活。
   坐标系注意: 框架 GPS 是 WGS-84, 高德显示是 GCJ-02, 偏移 ~500m 级别需试错校准。
4. **时间窗是服务端检查**: 06:00-23:00 (北京时间)。改设备时区(UTC+14)/系统时间
   (`service call alarm 2 i64 <ms>` 可用! shell 有 SET_TIME/SET_TIME_ZONE 权限) 都无效,
   用户实测依旧弹窗 → **只能在真实窗口内跑, 且这样时间戳全部真实无异常**。
5. **自由跑(自定义距离)模式**: 用户实测同样不行 (00:45)。

## 1. 学校信息 (抓到的)
- 广东医科大学 东莞校区 (松山湖, 科聚路); OSM WGS-84 bbox:
  22.9197~22.9323 N, 113.8559~113.8652 E
- 围栏: 东莞校区 · 开放中 · **自由打卡** (4 打卡点: 2必选+2可选), 开放时间全天
- 计划时间窗: 06:00-23:00 (服务端校验)
- 用户: 25级 2026-2027上学期(秋季), 总目标 80km, 已完成 20km (25%), 今日目标 1.0km
- 今日真实跑: 11/15 20:06, 4.158KM, 有效, 21:34, 配速 5'11", **总步数 2161, 步频 100, 步幅 192cm**
  ← 关键基准: 步频100/步幅1.92m 被服务器判有效 = 阈值宽松, "步行节奏"即可

## 2. 数据源结论 (三个量的可控性)
| 量 | 数据源 | 可控方式 |
|---|---|---|
| 轨迹/距离 | 框架 GPS (app 直连 gps provider, 1s HIGH_ACCURACY) | cmd location 注入, 完全可控 |
| 步数/步频 | 硬件计步 (MTK step_count, pedometer 插件 com.example.pedometer) | 跑步期间手持手机正常走动 ~100步/分, 产生真实步数 |
| 步幅 | 派生 = 距离÷步数 | 由前两者间接决定, 目标 1.9m 左右 |
- 配速 = 距离÷时间, 目标 5'11"~5'30" (3.1~3.2 m/s)

## 3. 抓包死路结论 (别再试)
- Flutter/Dart HttpClient 不读 Android 全局代理 → mitm 永远只见广告 SDK
- app 的 Java 层 (穿山甲/友盟) 走代理但拒用户 CA (targetSdk 36) → TLS 全挂
- 临时 root 不可行: MT6855/kernel 5.10.233-android12-9 不在 RootMyVivo 目录;
  GhostLock 仅 6.1-6.12; Adreno 仅骁龙; vivo 锁 BL 不解锁
- frida-server 以 shell 跑无法 attach 非 debuggable app (已实测)
→ 协议重放(路线B)暂不需要, 免root on-device 路线已够用

## 4. 工具清单 (~/yuepao/scripts/)
- `mock_gps.py`: arm/feed/route/dance/disarm/probe
- `play_route.sh`: 1Hz 直线+转向轨迹播放 (420s, 3m/s, 带噪声)
- 明天需补: 沿跑道线/复刻真实轨迹的 waypoints (用截图屏幕坐标反算:
  地图以蓝点居中, 比例尺 50m≈88px → 0.57m/px, 中心=当前注入坐标)

## 5. 明天 06:00 跑步 runbook
1. 05:55 插USB → `python3 mock_gps.py arm` → feed 围栏内点(22.9195,113.8630 附近) →
   截图确认"开始跑步"亮
2. 打开运动页 → 点开始 → 选"至少跑1000米"(计分,计入80km) → 有弹窗逐个点确定
3. 同刻启动 `play_route.sh` (后台) + 用户手持手机正常走动(100步/分) 至距离达标(~1.5km, 8分钟)
4. UI 自动点停止 → 结束 → 确认上传 → 跑步记录页查"有效"
5. 卡点预案:
   - 按钮变灰/弹异常提示 → 看 k/a 是否触发(可能周期性 environmentalCheckInterval),
     试 disable test provider 3s 再 enable (探测跳过 disabled provider)
   - 步数不涨 → 换"快走/原地走"节奏, 或确认 pedometer 需要 ACTIVITY_RECOGNITION 权限已授
   - 记录无效 → 看无效原因文案, 对症 (配速窗口/打卡点未过/步频异常)
6. 跑完 `python3 mock_gps.py disarm` 拆除

## 6. 手机状态 (今晚已恢复)
- 时区 Asia/Shanghai, 自动时间已开 (00:48 真实时间), mock provider 已拆, appops 已 deny
- frida-server (fs-svc) 仍在 /data/local/tmp/ (shell 身份, 未 attach)
- mitmdump 已停? (capture/mitm_live.log 最后 08:01) — 流程内确认

## 7. 【终局结论】免 root cmd location 注入 = 死路 (smali 铁证)
- Flutter 插件 AMapLocationClientImpl.setLocationOption 硬编码 `setMockEnable(false)`
- SDK 3sl/f (GPS 引擎) 收到 mock fix: `!isMockEnable()` 且连续计数 x>4 →
  `setErrorCode(15)` + `setLocationDetail("GpsLocation has been mocked!#1501")` + 坐标全清零 → 回调 Dart
- 前 4 个静默丢弃 → app 永远"定位中"
- 今晚 00:25 的"成功"实为用户真实 GPS (用户住校区宿舍科苑路, 围栏线外侧;
  用户走动/窗边收星时真实 GPS fix 被接受) — 与注入无关, 复盘已纠正
- 后续数据: 大跳注入地图不动 (SDK 丢弃), counter +4/5 (框架送达但 SDK 吞)
- 可行路线只剩:
  A) LSPatch 免 root Xposed: hook setMockEnable→true + hook 签名返回原版(喂高德key/穿山甲appsign) + LSPatch 重签
  B) apktool 直接 patch AMapLocationClientImpl.smali const 0x0→0x1 + 处理高德 key(自注册新key改manifest 或 hook 签名) + 重签
  C) 等待真实窗口 06:00-23:00 + 用户真走 (非目标)
- 备忘: 用户手机 Wi-Fi=家里自建路由器(192.168.1.137, adb tcpip 5555 可用),
  EasyTier 已装(PC et_rd 10.77.77.10 / 手机 10.77.77.11, TUN 会劫持全流量影响 app, 已关);
  mockrunning 工具链已部署可用 (mr-venv, web UI 8765, android.py 已补 flags patch)

## 8. DirtyFrag 临时 root 尝试记录 (11-16 02:05-02:35)
- 安装: DirtyFrag v1.17 + KernelSU-Next v3.4.2 (adb install 成功)
- exploit 在本机跑通前半程: 页缓存 patch 全部成功 (crash_dump64<-splicehelper,
  libbinderdebug.so<-dfroot.ko 14496B, libc++.so<-shellcode+trampoline),
  KMI 识别 android12-5.10, libc++ hook 在 init 上下文触发 (uid=0 过检),
  "/dev/df" 互斥锁创建成功
- 失败点: shellcode → grandchild 写 vendor_modprobe 标签 + exec /vendor/bin/insmod
  (存在, ->toybox_vendor) 加载 dfroot.ko → **超时 10s 无信号** → "EXPLOIT FAILED"
- 三次重试 (含重启后 fresh run) 全部同一位置失败, 确定性失败
- 怀疑: vivo/MTK SELinux 策略不允许 init→vendor_modprobe 转换, 或模块 vermagic
  不匹配 (无 dmesg 权限无法确证); /dev/df 互斥锁残存导致同 boot 重跑空转
- RootMyVivo/DirtyFrag 目录内无 PD2278/5.10.233 条目 (目录外尝试, 失败符合预期)
- KernelSU 管理器全程 "Not installed"; ksud 日志: "driver install syscall was
  blocked by seccomp" (manager app 域自装驱动被 seccomp 拦, 符合设计)
- 恢复: 重启即彻底干净 (无持久化)
- 下一步: a) 查 DirtyFrag/DFRoot issues 的 vivo MTK timeout 已知问题
  b) 试 DFRoot v4.x (不同 loader 实现) c) 都不行走 LSPatch (免 root, 不依赖 exploit)

## 9. 【终局成功】LSPatch 补丁链全通 (11-16 02:40-03:05)
- 工具: JingMatrix/LSPatch fork v1.2 (lspatch.jar, 需 Java21+, 系统 JRE25 跑)
  + JDK17 (javac) + build-tools 34.0.0 (/data/Applications/android-sdk)
- 模块: /home/sesley/Workspace/paceghost/lsp/module (stubs 编译期丢, dex 只含 MainHook)
  hooks (5个全挂载, logcat tag=VectorLegacyBridge/JRPatch):
  1. AMapLocationClientOption.setMockEnable -> args[0]=true
  2. AMapLocationClientOption.isMockEnable -> 恒 true
  3. Location.isFromMockProvider -> 恒 false (覆盖直调+AMap反射3sl/u.smali:338
     Reflect.invokeMethod+security_plus; ArtMethod hook 对反射生效)
  4. Location.isMock (API31) -> false
  5. AppOpsManager.checkOp(String,int,String) mock_location -> MODE_IGNORED(1)
- 重打包: java -jar lsp/lspatch.jar apk/com.joyrunworld.app/base.apk
  -m lsp/module/module.apk -l 2 -o lsp/out -f  (l 2 = PM+openat 签名伪装)
  产物 lsp/out/base-487-lspatched.apk (127MB, 已自动签名)
- 实测 (全部通过):
  1. 登录: 服务器接受补丁版 (验证码短信正常) -> 累计20.00km 数据完整
  2. mock 被接受: 不再卡"定位中", 地图加载, GPS 满格, 注入点即蓝点
  3. 围栏判定: 22.92452,113.85679 (GPX西段) -> "开始跑步"激活;
     操场环线 (用户GPX 测试02) 也在围栏内
  4. Route Studio 播放: speed 20km/h, 1s间隔, loop, 蓝点在地图上自动沿
     操场环线移动 (70.8s 跑 393.6m) — 用户目视确认成功
- 围栏动态 (重要): 判定仅在定位初始化时评估一次; 进围栏后锁存蓝按钮
  (离开不回灰); 切 tab (我的->运动) 复位后才重新评估 -> fence_scan.py
  的 scan2 用此法做逐点独立扫描 (被用户取消, 改用截图标定法)
- 围栏形状 (目视): 环绕校区的走廊 (粗蓝线), 沿科苑路-夜市-10栋-体育场,
  比校区 bbox 大; 用户宿舍 (科苑路西侧?) 在围栏外
- 用户有效/无效标定: 4'53"配速=无效, 5'11"/5'34"/7'11"=有效
  -> 真跑速度取 10~11.5 km/h (5'13"~6'00")
- 剩余 (明天): a) 用围栏页截图+比例尺标定, 反推整条围栏走廊坐标,
  生成周长~4km 的环路路线 (对齐历史 4.0KM 记录模式, 兼顾 4 打卡点)
  b) 06:00 后真跑: speed 改 ~10.5km/h, 用户手持手机原地走 ~100步/分,
  Route Studio 播放 + app 点开始, 距离够后停止上传, 查"有效"
  c) 手机上 KEEPASS 的 kdbx 是密码库文件, KernelSU 安装页只认 boot.img,
  别选它; "Always grant root to Shell" 仅在内核驱动装好后有意义 (本设备
  BL 锁死刷不了 boot, KernelSU 安装页路线永久死路, 已由 LSPatch 替代)
- 工件: lsp/lspatch.jar, lsp/module/* (MainHook.java=hook源, module.apk),
  lsp/out/base-487-lspatched.apk (装机版), scripts/fence_scan.py (含scan2)
