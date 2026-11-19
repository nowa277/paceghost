# 悦跑世界 · 复现 Runbook (2026-11-16 全链路已验证, 多实例版)

## 现状一句话
两台手机 (华为 USB 主力 / vivo 无线) 各挂一个 Route Studio 实例;
PC 上喂假 GPS (华为走 settings 通道, vivo 走 ADB testprovider);
计步由模块合成 (不用摇手机); 人脸由模块用预置图顶替 (不用真拍)。
**切换设备 = 一条命令, 零重新调试** (`joyrun_switch.sh`)。

## 0. 30 秒状态自检
```bash
adb devices                                                   # 在线设备
systemctl --user is-active route-studio@vivo route-studio@huawei
cat /home/sesley/Workspace/paceghost/devices.json                          # 别名→序列号→端口 (唯一事实源)
curl -s http://127.0.0.1:8765/api/status | python3 -c \
  "import json,sys;d=json.load(sys.stdin);print('vivo:',d['state'],d['connected'],d['udid'])"
curl -s http://127.0.0.1:8766/api/status | python3 -c \
  "import json,sys;d=json.load(sys.stdin);print('huawei:',d['state'],d['connected'],d['udid'])"
adb -s <序列号> shell "cat /sdcard/Android/data/com.joyrunworld.app/files/jrpatch.log | tail -8"
```
补丁版启动日志应含: `hook setMockEnable ok` / `hook takePicture ok` /
`gpsfeed: gps ready` / `face: selftest ok`。

## 0.5 切换设备 (核心入口)
```bash
/home/sesley/Workspace/paceghost/scripts/joyrun_switch.sh huawei         # 切到华为
/home/sesley/Workspace/paceghost/scripts/joyrun_switch.sh vivo --start   # 切到 vivo 并直接开跑
```
脚本做全套: 停所有实例播放 → 目标机预置 (appop / `jrstep_cadence=131` / 清 `jrgps_feed`+`jrpos` 残留) → 推人脸图 → 对应端口 `/api/connect` + settings 整包。设备不在线则不动任何东西。
输出 `mode=settings|testprovider` 即注入方式确认。
**多机同跑用 `joyrun_up.sh`** (见 §0.6), 不要用 `joyrun_switch.sh`。

## 0.6 整体链路一键启动 (推荐日常入口)
```bash
cd /home/sesley/Workspace/paceghost
scripts/joyrun_up.sh                  # 所有在线已登记设备: 起 WebUI + RS + 预置 + 连接 + 参数 + 守卫 + 注入
scripts/joyrun_up.sh huawei           # 只处理 nova7
scripts/joyrun_up.sh vivo huawei      # 多机同跑 (互不干扰)
scripts/joyrun_up.sh huawei --no-start   # 预置连接好, 但不开注入 (留给 RS 页手动点)
scripts/joyrun_down.sh [别名...]      # 对称停止: 守卫+注入+断连 (playing 时只停守卫)
```
自动处理: adb server 陈旧句柄 (`no permissions` 自愈) / WebUI 未启动 / RS 实例未 enable /
换机后预置缺失 / 实例绑着已拔死设备 (自动 rs-restart 重连) / 正在跑的实例 (跳过, 不动)。
启动后浏览器开 http://127.0.0.1:8800 看多机总览, 或直接进 RS 页点「开始移动」。

## 1. Route Studio (每设备一实例)
```bash
# systemd 模板单元: route-studio@<别名>.service → scripts/rs_instance.sh
systemctl --user is-active route-studio@vivo route-studio@huawei    # PC 重启后自动起 (linger 已开)
systemctl --user restart route-studio@<别名>                        # 卡死时重启, 需重新 connect
# 浏览器: vivo http://127.0.0.1:8765/  huawei http://127.0.0.1:8766/
# 各实例状态文件: ~/.ios-location-controller/session-<别名>.json, 路线参数自动恢复
# 新设备接入: devices.json 加条目 (serial/port/cadence/face) + enable --now route-studio@<别名>
```
- 两个实例同时活着互不干扰; **同账号别双机同时跑** (日额度互挤 + 服务端单跑步)
- mockrunning 代码零改动: `map --port` + `IOS_LOCATION_STATE` 本就支持多实例

## 1.5 重启恢复速查
| 场景 | 要做的事 |
|---|---|
| PC 重启 | 无 (systemd + linger 自动起) |
| 华为 USB | 插上即可, 无操作 |
| vivo 无线 | `adb -s 10CD9D0FR0001JD tcpip 5555` → 实测 IP connect (§7) |
| 只是断连 | `adb connect <ip>:5555` → Route Studio 重新 connect |
- 补丁版/登录/路线/参数: 重启都不丢

## 2. 路线
- 自动存档: `~/.ios-location-controller/session.json` → "操场循环01" 27 点 351m
- 备份: `/home/sesley/Workspace/paceghost/work/playground_loop.gpx`
- 丢了: Route Studio UI 里 Import GPX

## 3. 播放参数 (真跑 4'30" 档)
| 参数 | 值 |
|---|---|
| speed_kmh | **13.33** (4'30"/km) |
| speed_variation_pct | **3** |
| interval | 1.0 |
| loop | true |
| lateral_variation_m | 1.5 |
| variation_period | 10.0 |
| random_seed | 11 |

### 3.1 步幅同步 (改速度后必跑)
```bash
python3 -I /home/sesley/Workspace/paceghost/scripts/stride_sync.py 175 13.33
# 13.33km/h @ 175cm -> cadence 127
# lateral_variation 让实际路径 +3% -> 实测步幅 182cm
adb shell "settings put global jrstep_cadence 131"   # 压到 175 用这个 (热调 1s 生效)
```
- 公式 `cadence = speed_kmh*1000/60/(stride_cm/100)`
- 跑步页实时可见"平均步频/平均步幅"; 步幅 >185 就加 cadence
- 有效区间实证: 步幅 1.92m 有效, ~2.05m (骑车刷) 无效

## 4. 真跑流程 (窗口 06:00-23:00, 服务端校验)
1. Route Studio: 上述参数 → Connect → Start (蓝点绕圈)
2. 起人脸守卫:
   ```bash
   nohup python3 -u -I /home/sesley/Workspace/paceghost/scripts/face_watch.py --interval 1.2 \
     > /tmp/face_watch.log 2>&1 &
   ```
3. 手机 app 运动页: "开始跑步"亮蓝 → 点开始 → 选"至少跑1000米" → 弹窗全确认
4. 开跑后同步步幅 (见 §3.1)
5. 距离够: Route Studio Stop → app 点停止 → 结束 → 确认上传
6. 跑步记录页查"有效"绿标

### 4.1 人脸 (模块自动顶替, 无需真人)
- 触发: 开跑后不定时弹 (观测到 ~3min 处一次), 倒计时 20s/40s
- `face_watch.py` 检测到弹窗 → tap "确定" → 模块回预置图路径, **相机不开**
- 实证日志: `face: substituted face_use.jpg (445595B) -> CAP5258...jpg`
- 换图: `scripts/face_set.sh <图片> [序列号]` (自动 1080x1920 裁剪)
- 关掉: `adb shell settings put global jrface_on 0`

## 5. 跑完恢复
```bash
curl -s -X POST http://127.0.0.1:$P/api/stop -H "Content-Type: application/json" -d '{}'
curl -s -X POST http://127.0.0.1:$P/api/disconnect -H "Content-Type: application/json" -d '{}'
pkill -f face_watch.py
```
- 华为 (`mode=settings`): clear 会置 `jrgps_feed=0` 并删 `jrpos` (已实测干净)
- vivo (`mode=testprovider`): 自动拆 provider + 还原 shell appop

## 6. 换账号 (用户已冻结, 仅留档)
- 反复登录会触发「设备过多/登录上限」→ 用户决定不搞了
- v9 模块新路子: `jrdevice_rand=1` + 重启 app → 本进程内随机 ANDROID_ID, 免重装; 服务端是否只认它【待验证】
- 旧结论修正: 设备标识是 **ANDROID_ID, Android 8+ 按签名派生** (v8 Diag 读 app 进程内值 `6bb58043615916bc` 实证);
  之前"shell 读到不变所以是 app 自生成 UUID"的结论是错的 (shell 视角与 app 视角作用域不同)
- 旧脚本 `joyrun_account.sh` (卸载重装换签名) 仍可用, 但华为装包要按指纹且登多必触发上限

## 7. 卡点预案
| 症状 | 处置 |
|---|---|
| UI 暂停/参数点不动 | 状态机卡 error → `systemctl --user restart route-studio@<别名>` → 重新 connect |
| disconnect 返 400 | 旧 android.py 拿 `cmd location` 清理导致 → 已修 (mode=settings 分支) |
| 蓝点不动 | status 看 `injections`; 华为查 `settings get global jrpos` 在不在变 |
| "不在围栏内" | 首帧在围栏外 → stop→connect (重喂首点) →start, 或切 tab 复位 |
| 记录无效·单日里程超限 | 同账号当日额度用完 → 换账号 或 等次日 |
| 步数不涨 | `settings get global jrstep_on`=1; log 有无 `step_count sink captured` |
| 步幅 >185 | `settings put global jrstep_cadence 131` |
| 人脸没顶替 | log 有无 `face: substituted`; `jrface_on`=1 且源图存在 |
| adb 多设备报错 | 命令带 `-s`; 脚本已自动优先 USB |
| settings 只发改速 | 整体替换, loop 回落 false → 带 7 字段全量发 |

## 8. 关键事实 (别忘)
- 围栏判定只在定位初始化评一次, 进围栏后锁存; 切 tab 复位
- 围栏走廊绕校区一圈 (科苑路-夜市-10栋-体育场), 操场在围栏内
- 时间窗 06:00-23:00 是服务端查的, 改手机时钟没用
- 有效/无效分界: 4'53"=无效, 5'11"/5'34"/7'11"=有效
- KernelSU 安装页: keepass.kdbx 是密码库不是 boot.img; 本机 BL 锁死, 永久死路
- 计步是合成的 (`L0.c` EventSink 接管 + 真实传感器条件屏蔽)
- 人脸是图片 (`takePicture` 直接回路径, 相机不开)
- 模块日志: logcat `grep JRPatch` + `/sdcard/Android/data/com.joyrunworld.app/files/jrpatch.log`

## 9. 华为特有 (CDY-AN00 / EMUI / Android 10)
- `cmd location` 整个被裁 → `No shell command implementation`
- 必须 `settings put secure location_mode 3` (系统定位总开关, 开机可能是 0)
- 装 APK **必须用户按指纹**, adb 无法绕过
- 装前要勾选"已了解此应用未经检测"复选框 (约 105,1967), 再点"继续安装"(540,2250)
- 注入链路: `Settings.Global.jrpos` → 模块 `GpsFeed` → `LocationManager.addTestProvider("gps")`

## 10. 新设备部署 (5 步)
1. `adb install lsp/out-v6/base-487-lspatched.apk` (现成补丁版; 华为需按指纹+勾"未经检测")
2. `pm grant` CAMERA / ACTIVITY_RECOGNITION / 两个位置权限
3. `appops set com.joyrunworld.app android:mock_location allow`
4. `devices.json` 加条目 (serial / port / cadence 131 / face) → `systemctl --user enable --now route-studio@<新别名>`
5. `scripts/joyrun_switch.sh <新别名>` → 输出 `mode=` 确认注入方式 → 完成
