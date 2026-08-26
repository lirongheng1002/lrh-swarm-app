"""CGCS2000 高斯-克吕格投影（六度带）平面坐标 → 经纬度 反算

用途：领导直接输入平面直角坐标（X/Y），APP 换算成地理坐标后
回填航点经纬 / 地图定位。
- 椭球：CGCS2000（a=6378137，f=1/298.257222101，与 WGS84 几乎一致）
- 六度带：中央子午线 L0 = 6×带号 - 3
- Y 带号格式支持三种：
    "(19)406840"   括号带号 + 数值
    "19406840"     前两位为带号（7 位及以上数字）
    "406840"       纯数值（须另给带号，默认 19）
- Y 值为 中央子午线西移500km 后的成果坐标（<500000 = 中央子午线以西）
"""
import math
import re

_A = 6378137.0
_F = 1.0 / 298.257222101
_E2 = 2 * _F - _F * _F          # 第一偏心率平方
_EP2 = _E2 / (1 - _E2)          # 第二偏心率平方


def _meridian_arc(B):
    """子午线弧长（弧度 B → 米）"""
    e2 = _E2
    A0 = 1 + 3 / 4 * e2 + 45 / 64 * e2 ** 2 + 175 / 256 * e2 ** 3 + 11025 / 16384 * e2 ** 4
    A2 = 3 / 4 * e2 + 15 / 16 * e2 ** 2 + 525 / 512 * e2 ** 3 + 2205 / 2048 * e2 ** 4
    A4 = 15 / 64 * e2 ** 2 + 105 / 256 * e2 ** 3 + 2205 / 4096 * e2 ** 4
    A6 = 35 / 512 * e2 ** 3 + 315 / 2048 * e2 ** 4
    return _A * (1 - e2) * (A0 * B - A2 / 2 * math.sin(2 * B)
                            + A4 / 4 * math.sin(4 * B) - A6 / 6 * math.sin(6 * B))


def _foot_lat(x):
    """底点纬度 Bf（牛顿迭代，10^-14 米级收敛）"""
    e2 = _E2
    B = x / (_A * (1 - e2))
    for _ in range(12):
        d = (_meridian_arc(B) - x) * (1 - e2 * math.sin(B) ** 2) ** 1.5 / (_A * (1 - e2))
        B -= d
        if abs(d) < 1e-14:
            break
    return B


def _parse_y(y):
    """拆带号与 Y 数值；返回 (带号 or None, Y)"""
    s = str(y).strip()
    m = re.search(r'\((\d+)\)\s*([\d.]+)', s)
    if m:
        return int(m.group(1)), float(m.group(2))
    digits = re.sub(r'[\s,，]', '', s)
    if digits and digits.isdigit() and len(digits) >= 7:
        return int(digits[:2]), float(digits[2:])
    return None, float(s)


def zone_to_latlon(x, y, zone=None):
    """CGCS2000 高斯投影六度带反算 → (纬度, 经度)，WGS84 可用（误差<1m）

    x: 北向坐标（米）；y: 横坐标（可带带号）；zone: 带号（缺省自动取）
    """
    z2, y2 = _parse_y(y)
    if z2 is None:
        if zone is None:
            raise ValueError('Y 缺少带号，请填带号（如 19）')
        zz = int(zone)
    else:
        zz = z2
    l0 = 6.0 * zz - 3.0                 # 六度带中央子午线
    y0 = y2 - 500000.0                  # 相对中央子午线横距（西为负）
    bf = _foot_lat(float(x))
    e2, ep2 = _E2, _EP2
    sinb, cosb = math.sin(bf), math.cos(bf)
    t = math.tan(bf)
    eta2 = ep2 * cosb * cosb
    n = _A / math.sqrt(1 - e2 * sinb * sinb)
    m = _A * (1 - e2) / (1 - e2 * sinb * sinb) ** 1.5
    b = bf - t * y0 ** 2 / (2 * m * n) \
        + t * (5 + 3 * t * t + eta2 - 9 * eta2 * t * t) * y0 ** 4 / (24 * m * n ** 3)
    ll = y0 / (n * cosb) - (1 + 2 * t * t + eta2) * y0 ** 3 / (6 * n ** 3 * cosb)
    return math.degrees(b), l0 + math.degrees(ll)