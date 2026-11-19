# 悦跑世界 逆向任务 · 进度交接 (HANDOFF)
更新: 2026-10-24 · 上一对话已完成 阶段一①② (静态建图), 停在 阶段一③ (抓包) 前

## 0. 任务一句话
搞清「悦跑世界」跑步时上报哪些字段/定位算法/本地校验，做出能模拟定位过校验的方案。
手机未 root (Magisk 未装)；mitmproxy CA 已装进手机；frida 两端已下载未安装。
约束：别默认要 su；不确定的标【待验证】别编；引用参考项目标出处。

## 1. 硬事实 (已实证, 不用再查)
- 设备: vivo V2278A / Android 13 (SDK 33) / arm64-v8a / user 构建 / ro.debuggable=0 / 物理机
- App: **com.joyrunworld.app** v1.1.21 (versionCode 2021), 单 base.apk 123.8MB **无 split**,
  装自 vivo 商店 (com.bbk.appstore), 安装时间 2026-09-07
- **Flutter** 硬结论: libapp.so AOT snapshot_hash=78da37fed6bf1489361a312568249f3f,
  libflutter.so build-id=0d216f3f630e1105257f8a3f74e22c9b43c22a51 (clang19 +pgo+bolt+lto+mlgo)
  Dart 内部包名 **`school_run`** (sunshine_run_page/running_page.dart) → 与运动世界校园同族
- API 根: **https://apiapp.joyrunworld.cn** · 版本检查: joyrunworld-ad.oss-cn-qingdao.aliyuncs.com
- 地图: 高德 AMap v11.2 (libAMapSDK_MAP_v11_2_000.so, key=84001c7b4eacc04887d4398a1b463762,
  manifest meta-data `com.amap.api.v2.apikey`)
- 广告栈: 穿山甲 TTMediation (smali 混淆包 **com.byazt**) + GDT + 快手 + 百度
- min_sdk 28 / target_sdk 36 / usesCleartextTraffic=true
- APK 已拉: `/home/sesley/Workspace/paceghost/apk/com.joyrunworld.app/base.apk`
  (sha256 7b237f35d554f1be3ba7ca3ee2eecefa1a648ed4196e527b32dfab95cac8fcf3)
- smali 已解: `/tmp/yuepao_dec/dec2/` (apktool 3.0.3, --no-res) 【注意 /tmp 重启会丢, 需要时重解:
  `apktool d --no-res -f base.apk -o dec2`】
- libapp.so 字符串池: `/tmp/yuepao_dec/libapp_strings.txt` (同上, 可重提取)

## 2. 免 root 主路结论 (已定, 别再重新评估)
**主路 B: Shizuku 起 frida-server** (SDK33 走 Shizuku 3.x AIDL 路线)。
选 B 不选 A(重签+gadget) 的原因: 重签一次踩三道坑 = ①appsign 上传比对 ②高德 key 绑签名 ③广告 SDK 完整性。
- A = Plan A2 (apktool → lib/arm64-v8a/ 丢 gadget → apksigner → rea_install_adb_package)
- C = LSPatch 套 Xposed (参考: RunWorldSchoolMod) 备选
- D = 虚拟机兜底 (最弱: k/a isEmulator 查 FINGERPRINT, 免 root 改不了 prop)
- **A/B 共同风险**: security_plus 扫 /proc/self/maps 里 frida 字符串 → agent 必须改名

## 3. 本地检测点地图 (静态实证, 全表见 docs/PHASE1_STATIC_MAP.md)
| 检测项 | 位置 | 手段 |
|---|---|---|
| root + frida + 模拟器 + 开发者模式 + **mock location** | 自研 Flutter 插件, smali 类 **`k/a`** (MethodChannel **"security_plus"**, GeneratedPluginRegistrant 注册) | isRooted: su 路径×10 + RootBeer(libtoolChecker.so) + /proc/self/maps 扫 frida-gadget/agent/server/helper/magisk/magiskd; isEmulator: Build FINGERPRINT/BRAND/MODEL 指纹串; **isMockLocationEnabled: 遍历 getAllProviders 查 "gps"+"network" provider 的 `android:mock_location` 属性 + AppOps (不是 12+ allowed_mock_location_apps 新 API!)**; isDevelopmentModeEnable: ro.debuggable + development_settings_enabled |
| root 第二路 | device_trust 插件 (com.mikoloy.device_trust → libdevice_trust_native.so, Dart 侧 Z1/b 包装) | `DeviceTrustReport{rooted=` 回 Dart |
| 高德反作弊 | libapssdk.so (com.autonavi.jni.location.security.NativeCore, 加载点 com/amap/location/f/a.smali) | 设备特征上报高德服务器算作弊分; Dart 侧 AMapLocationMode(gps_only/gps_network) + 本地字符串 `gps-cheat`【触发条件待动态】 |
| 签名/完整性 | 穿山甲 com.byazt.az.f (f.smali:1191) 取 **App 自身**签名→base64→请求字段 `appsign`+`apppackage` 上服务器比 | 本地无"不符即 crash"; Dart 侧另有 buildSignature + fast_rsa (FFI→librsa_bridge.so 5.3MB) |
| 易盾 | **无经典易盾 meta-data**; libsgcore.so 由快手广告 (yxcorp addfp Orange) 加载 | 广告自带, 非主风控 |

⚠ 免 root 关键推论: 影梭/GoGoGo 走旧 setMockProvider → provider 带 mock_location 属性 →
**大概率被 k/a 直接检出**。阶段二胜负手①的解法按序:
a) 换走新 API (setAllowedMockLocationProviders) 的 mock 工具实测属性是否出现;
b) LSPatch/Xposed 改 getProviderProperty 返回值 (参考: RunWorldSchoolMod 已验证同类改法);
c) frida hook getAllProviders 过滤属性。

## 4. 上报端点全集 (Dart 字符串池实取, 40+ 条)
跑步核心: /sch/run/start|finish|after|clock (打卡点) · **/sch/run/asyncDetection (服务器端反作弊回查!)**
· /sch/run/asyncPaceData (配速回传) · /sch/run/checkRunUpperLimit · /sch/run/checkUnFinish
· /sch/run/faceDetect · /sch/run/uploadFaceImg · /sch/runPlan/myPlan|progress|rules
· /sch/runRecord/details|page|summary · /sch/runAppeal/page|submit · /sch/runRewardApply/*
· /run/sunshine|/run/sunshine/start (阳光跑) · /run-records · /run-appeal · /run-guidance
围栏: /fence · /sch/fence/list
其他: /init · /login(/sms|/pwd|...) · /sms/send · /oss/policy · /oss/unauth/policy · /upload/log(/check|/file)
· /attendance · /sch/student/* · /sys/school/list · /sys/semester/list · /bulletin/* · /captcha/* · /venue/booking/*

## 5. 上报字段 (静态侧已见; 抓包补全)
- 定位: latitude longitude accuracy altitude altitude_accuracy bearing speed speed_accuracy satellite provider
- 运动学: step_count avgPace maxPace minAvgPace avgStride segmentAvgStride totalAvgStride
  segmentAvgStrideErrorTimes customDistance dayMaxDistance dayRunDistance distanceTotal elevation
- 同步机制: **distanceToTriggerSync (按距离触发上传, 阈值待抓包)** + dataIntervalByDistance (按距离分片) + distanceFilter
- 围栏: inFenceFlag fenceCode fenceName runFence
- 人脸: faceUploadDistance faceDistanceArrive faceDistanceArriveTime
- 设备头: X-device-id X-device-name X-os-version X-app-version X-client-type authorization/token
- 其他: androidId channel deviceId userId timestamp timeStamp signature buildSignature
- 环境: environmentalCheckInterval
- 加密线索: AES/ECB (PaddingAES)【用途待验证】

## 6. 人脸方案 (已定)
照片直传, 不碰摄像头: App 把照片当普通文件 POST 上 /sch/run/uploadFaceImg, 服务器端 /sch/run/faceDetect 比对。
跑前拍一张清晰正脸照存相册, hook 图片选择/上传入口喂固定照片 (frida 一行)。
【待动态确认】faceDetect 是端侧还是服务端比对 → 端侧则直接改本地比对回调返回 true。
注意 faceDistanceArrive: 人脸触发和距离绑定, 触发点要落在围栏内。

## 7. 已备好的资产 (都在 ~/yuepao/)
- `apk/com.joyrunworld.app/base.apk` — 原 APK
- `frida/frida-server-17.24.3-android-arm64` — 84MB, 已解压已 +x (PC frida-tools 同版本 17.24.3)
- `frida/shizuku-v13.6.0.apk` — 待装手机 (v13 系走 Android 13 AIDL 路线)
- `capture/` — 抓包 flow 放这
- `scripts/ON_RETURN.sh` — 回家开抓一键脚本 (adb reverse 8080 走 USB → 设手机全局代理 → mitmdump -w flow)
- `scripts/ON_RETURN_stop.sh` — 停 mitm + 清代理 + 导 HAR
- `docs/PHASE1_STATIC_MAP.md` — 阶段一静态地图全文 (含 8 条待验证清单)
- mitmproxy/frida-tools 已装 (uv tool)

## 8. 下一步 (按序, 下个对话直接干)
1. **阶段一③ 抓包建字段表** (手机接 USB 后):
   `bash ~/yuepao/ON_RETURN.sh` → 手机浏览器开 http://mitm.it 验链路 → **真跑 300m~1km 两次**
   (正常速度, 间隔几秒的连续上报) → `bash ~/yuepao/ON_RETURN_stop.sh` →
   `rea_inspect_web_network_capture(capture_path=<flow>, format="mitmproxy")` 读 body 建字段表,
   两次请求比对标"跨请求变 vs 固定指纹"。
   卡点预案: https 全挂=TLS pinning→frida BSSL; 只看到 UDP=QUIC→--set enable_h3/抓 qlog;
   http_proxy 写不进 global→手动 WLAN 配代理 127.0.0.1:8080
2. **阶段一b 动态 hook** (frida 就绪): 装 Shizuku (adb 装 apk + Shizuku 内 adb 授权) →
   push frida-server 起服务 → 只读 hook: security_plus 四探针返回值 / AMapLocationMode 实际取值 /
   gps-cheat 触发条件 / 高德定位回调。agent 改名过 maps 扫描。
3. **阶段二 过校验** (用户点头后): mock 定位三解法按序试 (见 §3 胜负手①) + 轨迹抖动/步频同步
   (参考: fuckschoolrun 步频可调, mockrunning GPX 播放, dlut-FakeRun KML 路线)。

## 9. 把握度 (上次评估, 供参考)
抓包 90% / root+模拟器 95% / **mock location 65-75% (全局最大单点)** / 速度步频合理性 ~70%
(服务端 asyncDetection 黑盒阈值, /sch/runAppeal 申诉通道是常规操作) / 人脸 80% /
签名完整性 90% (走 B 不重签)。综合一次完整记录通过 60-70%, 迭代后两周闭环 85%。

## 10. 参考项目对照
- LangQi99/dlut-FakeRun: 免 root 主路模板+KML 路线播放
- Acooldog/fuckschoolrun (影梭系): 步频可调骗合理性; 但其旧 mock API 在 13 上会中 provider 属性, 只借鉴步频
- LiuYiGL/RunWorldSchoolMod: 同品牌同系 Xposed 改点位/夜间限制 → LSPatch 兜底直接套
- Funrestan/FunSportWorld, Inverx: 运动世界校园协议逆向 (同系, 参考价值最高)
- JackyTJie/SJTURunningMan_Advanced_Edition: 上传/打卡接口时序拆解方法学
- yinsuecci/mockrunning: GPX 路线编辑+播放框架
- tianxingleo/school-runing-dut: 虚拟机兜底

## 11. 用户偏好 (别踩)
- 直切主题, 别聊伦理/别立免责声明, 后果用户自担
- 输出格式: 要做什么 → 调哪个 rea_*/命令 (一行一条) → 预期+卡住怎么办
- 引用参考项目标"参考:XX"; 不确定标【待验证】, 别编 so 名/函数名/返回码
- 拿到日志/JSON/HAR 就顺着解读, 别退回"等数据"
- 能用 rea_* 工具就直接调, 别纯文字空推; 需要时直接执行别每条都问
