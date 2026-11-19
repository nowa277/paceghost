# RS 页面 overlay 备份

refs/ 整体被 .gitignore 排除 (上游 mockrunning 不入库), 但 paceghost 在 RS 页面上
新增了两个卡片 + 一个锁定提示, 这些改动需要入库备份。本目录是部署副本。

## 部署方式
把本目录 4 个文件复制到 refs/mockrunning/src/ios_location_controller/static/ 覆盖同名文件即可:
```bash
cp webui/rs_overlay/* refs/mockrunning/src/ios_location_controller/static/
```

## 相对上游 RS 2.0 的改动清单
| 文件 | 改动 |
|---|---|
| pg_scan.js (新增) | USB 设备扫描卡: 扫描/连接(预置→连接→自愈)/人脸上传 |
| pg_sensor.js (新增) | 传感器配置卡 (cadence 自动推导) + 锁定原因提示 |
| index.html | +2 卡片容器, +2 script 标签, 连接方式 fieldset 隐藏 (默认 android), 导入按钮下加 pg-locked-hint 段 |
| app.css | 末尾追加 pg- 前缀样式段 (扫描卡/传感器卡/锁定提示) |

注意: 上游 app.js / web.py / playback.py / android.py 零改动。
