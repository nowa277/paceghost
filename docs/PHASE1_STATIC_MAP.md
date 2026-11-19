# 悦跑世界 阶段一·静态检测点地图
生成: 2026-10-22 · 来源: base.apk (sha256 7b237f35d554f1be3ba7ca3ee2eecefa1a648ed4196e527b32dfab95cac8fcf3)

## 0. 基本盘
- 包名 com.joyrunworld.app · v1.1.21 (versionCode 2021) · 单 base.apk 123.8MB · **无 split**
- **Flutter** (embedding v2, Dart AOT): libapp.so 15.4MB, snapshot_hash 78da37fed6bf1489361a312568249f3f
  - libflutter.so build-id 0d216f3f630e1105257f8a3f74e22c9b43c22a51 (clang 19, +pgo+bolt+lto+mlgo)
  - Dart 内部包名 **`school_run`** (pages/sunshine_run_page/running_page.dart, native_running_page.dart)
- 设备: vivo V2278A · Android 13 / SDK 33 · arm64-v8a · user/release-keys · ro.debuggable=0
- min_sdk 28 · target_sdk 36 · 装自 com.bbk.appstore (vivo 商店)
- API 根: **https://apiapp.joyrunworld.cn** · 版本检查: joyrunworld-ad.oss-cn-qingdao.aliyuncs.com/app-static/version.json
- 地图: 高德 AMap (libAMapSDK_MAP_v11_2_000.so, key=84001c7b4eacc04887d4398a1b463762)
- 广告: 穿山甲 TTMediation (混淆包 com.byazt) + GDT (com.qq.e) + 快手 (com.kwad) + 百度 (com.baidu.mobads)

## 1. 本地检测点（静态确认）

### 1.1 自定义 Flutter 插件 `security_plus` (smali 类 k/a) — 主闸
MethodChannel "security_plus"，Dart 侧调用，四个探针:
| 探针 | 手段 | 细节 |
|---|---|---|
| isRooted | su 路径 + RootBeer(libtoolChecker.so) + **/proc/self/maps 扫 frida** | 扫字符串: frida-gadget / frida-agent / frida-server / frida-helper / magisk / magiskd (含小写归一); su 路径: /sbin/su, /system/bin/su, /su/bin/su, /data/local/su, /data/local/bin/su, /system/xbin/su, /system/xbin/daemonsu, /system/bin/failsafe/su, /system/sd/xbin/su, /data/local/xbin/su; 文件: /system/app/Superuser.apk, /system/etc/init.d/99SuperSUDaemon; 目录: /dev/com.koushikdutta.superuser.daemon/ |
| isEmulator | Build 指纹 | FINGERPRINT/BRAND/MODEL 含 generic/unknown/google_sdk/Emulator/"Android SDK built for x86" → 判模拟 |
| isMockLocationEnabled | **LocationManager provider 属性** + AppOps | 遍历 getAllProviders，检查 "gps" 与 "network" provider 的 `android:mock_location` 属性; 另查 appops |
| isDevelopmentModeEnable | ro.debuggable + development_settings_enabled | 开发者选项开着就报 |

⚠ 免 root 关键: 它查 mock 走 **provider 属性** 而非 settings secure 的 allowed_mock_location_apps
   (Android 12+ 新 API)。选中的 mock 应用若给 provider 打了 mock_location 标记 → 直接暴露。
   影梭/GoGoGo 走 LocationProvider.setMockProvider (旧 API) 时 gps provider 会带此属性。
   参考: Acooldog/fuckschoolrun(影梭) 在 12+ 的行为需实测。

### 1.2 device_trust 插件 (com.mikoloy.device_trust → libdevice_trust_native.so)
Dart 字符串: `DeviceTrustReport{rooted=`, `getDeviceTrustReport`, `device_trust: getReport timeout`
→ 第二路 root 检测, 结果回 Dart。

### 1.3 高德反作弊 (libapssdk.so, com.autonavi.jni.location.security.NativeCore)
- 加载点: com/amap/location/f/a.smali
- 高德定位 SDK 自带设备采集+上报高德服务器, 服务器端算作弊分 (mock 特征/速度跳变/加速度)
- Dart 侧模式: AMapLocationMode (gps_only / gps_network) + `forceLocationManager`
  → 若跑 gps_only, mock 位置直接进 GPS provider; gps_network 则混合
- 本地字符串 **`gps-cheat`** → Dart 侧有本地 cheat 标记逻辑 [待验证: 触发条件]

### 1.4 签名/完整性
- **无** 经典易盾 appkey meta-data (manifest 全部 meta-data 已列, 无 yidun/sgmain)
- libsgcore.so (88KB) 由快手广告 Kuaishou addfp Orange 加载 → 广告 SDK 自带, 非主风控
- 签名校验: byazt(穿山甲) 取 **App 自身** 签名 → base64 → 请求字段 `appsign`+`apppackage` 上服务器比 (smali_classes2/com/byazt/az/f.smali:1191)
  → 重签名后 appsign 变, **是否致命取决于服务器策略** [待验证: 抓包看业务请求是否也带签名]
- Dart 侧 `buildSignature` + fast_rsa (FFI → librsa_bridge.so 5.3MB, RSA) → 业务请求疑似 RSA 签名
- AMap key 绑定签名? 高德默认绑包名+签名 → 重签名后地图/定位可能降级 [待验证]

## 2. 上报端点全集 (libapp.so 字符串池, 静态)
跑步核心:
- /sch/run/start, /sch/run/finish, /sch/run/after, /sch/run/clock (打卡点)
- /sch/run/asyncDetection ← **异步检测(服务器端反作弊回查)**
- /sch/run/asyncPaceData ← 配速数据回传
- /sch/run/checkRunUpperLimit, /sch/run/checkUnFinish
- /sch/run/faceDetect, /sch/run/uploadFaceImg ← 人脸
- /sch/runPlan/myPlan|progress|rules, /sch/runRecord/details|page|summary
- /sch/runAppeal/page|submit, /sch/runRewardApply/*, /sch/runReward/page
- /run/sunshine, /run/sunshine/start (阳光跑), /run-records, /run-appeal, /run-guidance
地理围栏:
- /fence, /sch/fence/list
其他: /init, /login(/sms|/pwd|/forgot-pwd|/change/verifyAndChangePhone), /sms/send,
  /oss/policy, /oss/unauth/policy, /upload/log(/check|/file), /attendance,
  /sch/student/*, /sys/school/list, /sys/semester/list, /bulletin/*, /captcha/*,
  /venue/booking/*, /fitness-test/*, /ai-exercise

## 3. 上报字段 (静态侧已见, 动态抓包补全)
定位/运动学: latitude, longitude, accuracy, altitude, altitude_accuracy, bearing,
  speed, speed_accuracy, satellite, provider, step_count, avgPace, maxPace,
  minAvgPace, avgStride, segmentAvgStride, totalAvgStride, segmentAvgStrideErrorTimes,
  customDistance, dayMaxDistance, dayRunDistance, distanceTotal,
  distanceToTriggerSync (距离触发同步!), dataIntervalByDistance (按距离分片),
  distanceFilter, elevation, environmentalCheckInterval,
  faceUploadDistance, faceDistanceArrive, faceDistanceArriveTime
围栏: inFenceFlag, fenceCode, fenceName, runFence
设备上下文 (HTTP 头): X-device-id, X-device-name, X-os-version, X-app-version, X-client-type, authorization/token
其他: androidId, channel, deviceId, userId, timestamp/timeStamp, signature/buildSignature
加密: AES/ECB (PaddingAES) [待验证: 用在哪]

## 4. 免 root 主路结论 (A→D 评估, Android 13 / vivo user 构建 / arm64)
- **B (Shizuku) 主路** ✅: SDK33 满足 Shizuku 3.x (AIDL 13+), adb 链路已在 →
  `adb shell sh /sdcard/shizuku-setup.sh` 装 Shizuku, 再 `shizuku start frida-server`。
  免重签名 → 不碰 appsign/高德绑定/易盾完整性三道签名坑。
  风险: ① security_plus 扫 /proc/self/maps 里的 frida 字符串 — 无论 A/B 注入都会扫到
  (gadget 和 server 注入的 agent 都映射进目标进程) → **两条路都要把 agent 改名**
  (frida-gadget 重命名 lib*.so; frida-server 的 agent 用 Gadget 同款改名思路或
  `--agent` 自定义)。② Shizuku 自身是系统应用, 若 App 查"其他已装应用"才暴露,
  目前 manifest queries 里没列 shizuku 包名 → 暂安全。
- **A (frida-gadget 重签名) 备选** ✅ 可行但坑多: 重签名 → appsign 变 + AMap key 可能
  失效 + 穿山甲/快手广告 SDK 完整性。作为 B 失败后的 Plan A2。
  参考: LangQi99/dlut-FakeRun (免 root 主路, 重签名+悬浮窗)。
- **C (LSPatch) 备选**: 免 root 套 Xposed 模块 (参考: LiuYiGL/RunWorldSchoolMod 改点位/
  夜间限制)。适合"只改值不想挂 frida"的场景; 但 LSPatch 重打包同样破坏签名。
- **D (虚拟机) 兜底**: 雷电/夜神; vivo 真机 + 易盾同查模拟器 (k/a 的 isEmulator 查指纹),
  需改 FINGERPRINT/ro.kernel.qemu → 免 root 难改 prop → D 是最后兜底。
  参考: tianxingleo/school-runing-dut。

## 5. 抓包前置 (阶段一③ 开抓前确认)
- usesCleartextTraffic="true" (但业务大概率仍走 https)
- Dart 侧未见明显 TLS pinning 字符串 [待验证: mitmproxy 直接试]
- AMap 自有域名 (amap 定位上报) 可能独立 pinning → 只关心业务域名 apiapp.joyrunworld.cn
- mitmproxy 过滤: --set confdir, 或 flowfilter `~d apiapp.joyrunworld.cn`
- 需要 ≥2 次真实跑步请求对比 (start/finish/clock/asyncPaceData)

## 6. 待验证清单
1. [抓包] 业务请求是否带签名头/字段 (appsign 是否业务侧也用)
2. [抓包] 跑步中上报频率/分片 (distanceToTriggerSync 阈值)
3. [动态] AMapLocationMode 实际取值 (gps_only 还是 gps_network)
4. [动态] gps-cheat 本地触发条件 (速度阈值?)
5. [动态] security_plus 四探针实际返回值 (frida 只读 hook)
6. [动态] asyncDetection 服务器回查什么 (需要两次抓包对比)
7. [静态→动态] AES/ECB 加密用在哪 (上传日志? 定位分片?)
8. [重签名实验] AMap key 是否绑签名 (装 A 路重签包看地图是否降级)
