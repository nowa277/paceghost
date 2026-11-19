# paceghost — 悦跑世界校园跑自动化

真跑打卡一条龙: Route Studio 喂模拟 GPS 播放路线 + LSPatch 模块合成计步/顶替人脸。
**换设备 = 一条命令, 新设备 = USB 插一次以后只走 WiFi。**

运行手册见 [RUNBOOK.md](RUNBOOK.md) (细节全在里面); 交接分析笔记见 docs/HANDOFF*.md。

## 目录

```
devices.json            设备登记表 (唯一事实源: 别名/序列号/WiFi/端口/步频/脸图)
route/playground_loop.gpx  标准路线 (操场循环01, 27点 351m)
systemd/route-studio@.service  每设备实例模板单元
scripts/
  joyrun_switch.sh      ★ 一键切换设备 (--start 直接开跑)
  joyrun_new_device.sh  ★ 新设备接入 (USB 一次: 装包/权限/人脸/开WiFi/登记/建实例)
  joyrun_wifi.sh        WiFi adb 维护 (重连全部 / --enable 给某台开 WiFi)
  face_set.sh           换人脸图 (1080x1920 裁剪推送)
  face_watch.py         人脸弹窗守卫 (自动点确定)
  stride_sync.py        速度->步频同步
  rs_instance.sh        实例启动器 (systemd 调用, 别改端口逻辑)
  joyrun_account.sh     换账号旧脚本 (已冻结, 仅留档)
lsp/
  module/src/com/poc/jrpatch/   Xposed 模块源码 (MainHook 入口, 9 个 hook 组)
  module/stubs/                 Xposed 编译期桩
  build_module.sh               模块编译 + 重打补丁 APK
patches/mockrunning-android-settings-mode.patch  mockrunning 本地魔改快照
```

## 日常三件事

```bash
scripts/joyrun_switch.sh huawei          # 切到华为 (USB/WiFi 自动选通道)
scripts/joyrun_switch.sh vivo --start    # 切到 vivo 并直接开跑
scripts/joyrun_wifi.sh                   # PC/手机重启后重连所有 WiFi 设备
scripts/joyrun_new_device.sh 别名        # 新手机: USB 插上 + 报别名, 其余全自动
```

## 新设备流程 (USB 一次 → 只走 WiFi)

1. 手机开 USB 调试, 插电脑
2. `scripts/joyrun_new_device.sh <别名>` — 自动: 装最新补丁 APK → 权限 + mock appop → 推人脸 → `adb tcpip 5555` + WiFi connect → 登记 devices.json (分配下一个端口) → 启动 `route-studio@<别名>` 实例 → connect
3. 拔 USB。此后 Route Studio / 所有脚本走 `IP:5555` (switch 脚本 USB 在线优先走 USB)
4. 手机重启后 adbd tcpip 复位 → 插一下 USB 跑 `scripts/joyrun_wifi.sh` 自愈, 或日常直接重跑它

> 同账号在新设备登录可能触发服务端设备上限, 与脚本无关。

## 架构要点 (为什么这样做)

- **每台手机一个 Route Studio 实例** (端口不同, 状态文件 `~/.ios-location-controller/session-<别名>.json`),
  互不干扰; mockrunning 代码零改动 (`map --port` + `IOS_LOCATION_STATE` 本就支持)
- **注入方式自动探测**: 有 `cmd location` 走 ADB testprovider (vivo), 没有则模块进程内
  `addTestProvider` (华为, `mode=settings`), connect 时自动落
- **切换免调试**: 路线/参数存在各实例状态文件, switch 只做设备侧预置 (appop/计步/清残留/推脸)

## 重新 clone 后要补的本地件 (都不在 git 里)

| 缺什么 | 从哪来 |
|---|---|
| `apk/com.joyrunworld.app/base.apk` | 原始 APK (自己从手机 pull) |
| `lsp/lspatch.jar` | LSPatch (JingMatrix fork) release |
| `lsp/sign-*.jks` | 签名 keystore (**丢了就得全员卸载重装**, 只在本地) |
| `lsp/module/assets/face.jpg` | 人脸图 (模块内嵌兜底, 可空) |
| `work/face/face_src.png` | 人脸源图 (devices.json face 字段指向) |
| `refs/mockrunning/` | clone 第三方项目 + `git apply patches/mockrunning-android-settings-mode.patch` |
| `tools/mr-venv/` | `python3 -m venv tools/mr-venv && tools/mr-venv/bin/pip install -e refs/mockrunning` |

## systemd 安装

```bash
cp systemd/route-studio@.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now route-studio@<别名>   # 每台一台
loginctl enable-linger $USER                        # 开机自启 (已开过)
```

## 重打补丁 APK (改模块代码后)

```bash
lsp/build_module.sh v10     # 出到 lsp/out-v10/; 新签名≠旧签名 -> 换签名=卸载重装
```

## 注意

- 真跑窗口 **06:00–23:00** 是服务端校验, 改手机时钟没用
- 日里程上限按账号算, 双机同账号会互相挤占
- 签名 keystore / 人脸图 / 抓包数据 / 原始 APK 都被 .gitignore, 别提交
