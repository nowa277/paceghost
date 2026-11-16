#!/usr/bin/env bash
# 沿围栏内侧播放轨迹: 起点 22.9195,113.8630, 3m/s, 1s/点
S=10CD9D0FR0001JD
# 用 python 算路径点, 每秒喂一个
python3 - << 'PYEOF' > /tmp/route_points.txt
import math
lat0, lon0 = 22.9195, 113.8630
speed = 3.0          # m/s -> 配速 5'33"/km
dur_s = 420          # 7 分钟 = 1.26km
bearing = 80.0       # 先向东偏北 (沿围栏)
m_per_deg_lat = 111320.0
m_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))
# 轨迹: 直线 300m -> 缓转向 -> 再直线 -> 回头弧线 (模拟操场圈)
t = 0
la, lo = lat0, lon0
import time
while t < dur_s:
    # 每 60s 转向 10 度 (模拟弯道)
    if t % 60 == 0 and t > 0:
        bearing += 12
    # 每点轻微抖动 (模拟 GPS 噪声)
    import random
    la += (speed * math.cos(math.radians(bearing))) / m_per_deg_lat
    lo += (speed * math.sin(math.radians(bearing))) / m_per_deg_lon
    acc = 6 + random.random() * 4
    print(f"{la:.7f},{lo:.7f},{acc:.1f}")
    t += 1
PYEOF
N=$(wc -l < /tmp/route_points.txt)
echo "路线点数: $N"
i=0
while read -r line; do
  i=$((i+1))
  LAT=$(echo "$line" | cut -d, -f1)
  LON=$(echo "$line" | cut -d, -f2)
  ACC=$(echo "$line" | cut -d, -f3)
  adb -s $S shell "cmd location providers set-test-provider-location gps --location $LAT,$LON --accuracy $ACC" >/dev/null 2>&1
  if [ $((i % 30)) -eq 0 ]; then echo "[$i s] $LAT,$LON"; fi
  sleep 1
done < /tmp/route_points.txt
echo "轨迹播放完成"
