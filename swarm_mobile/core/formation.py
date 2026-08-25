"""队形数学：机头方向相对偏移 -> 经纬度目标、队形预设、球面距离
偏移语义：[前方(机头方向,米), 右方(米), 高度差(米)]
编队目标 = 长机位置 + 按长机航向旋转后的偏移（机头一致，不会"方向反了"）
队形预设三个间距：前后 sf、左右 sl、小组 sg
"""
import math

M_PER_DEG = 111320.0


def offset_to_latlon(lat, lon, north_m, east_m):
    new_lat = lat + north_m / M_PER_DEG
    new_lon = lon + east_m / (M_PER_DEG * max(0.01, math.cos(math.radians(lat))))
    return new_lat, new_lon


def target_for(leader, vehicle):
    fwd, right, up = vehicle.offset
    hdg = leader.hdg if leader.hdg is not None else 0.0
    rad = math.radians(hdg)
    north = fwd * math.cos(rad) - right * math.sin(rad)
    east = fwd * math.sin(rad) + right * math.cos(rad)
    lat, lon = offset_to_latlon(leader.lat, leader.lon, north, east)
    alt = (leader.rel_alt if leader.rel_alt is not None else 0) + up
    return lat, lon, alt, hdg


def haversine(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def preset_offsets(name, n, sf=5.0, sl=5.0, sg=10.0):
    """返回 n 架机的 [前, 右] 偏移；第 0 个=长机 [0,0]。
    sf=前后间距, sl=左右间距, sg=小组间距（三角群等分组队形用）。
    飞机数量不足时，从最后往前减。"""
    off = [[0.0, 0.0] for _ in range(n)]
    if n <= 1:
        return off
    if name == '一字横排':
        for i in range(1, n):
            rank = (i + 1) // 2
            side = 1 if i % 2 == 1 else -1
            off[i] = [0.0, side * rank * sl]
    elif name == '人字形':
        for i in range(1, n):
            rank = (i + 1) // 2
            side = 1 if i % 2 == 1 else -1
            off[i] = [-rank * sf, side * rank * sl]
    elif name == '前三角':
        idx, row = 1, 1
        while idx < n:
            row += 1
            for j in range(row):
                if idx >= n:
                    break
                off[idx] = [-(row - 1) * sf, (j - (row - 1) / 2.0) * sl]
                idx += 1
    elif name == '后三角':
        idx, row = 1, 1
        while idx < n:
            row += 1
            for j in range(row):
                if idx >= n:
                    break
                off[idx] = [(row - 1) * sf, (j - (row - 1) / 2.0) * sl]
                idx += 1
    elif name == '梯形':
        idx, row = 1, 1
        while idx < n:
            row += 1
            width = row + 1
            for j in range(width):
                if idx >= n:
                    break
                off[idx] = [-(row - 1) * sf, (j - (width - 1) / 2.0) * sl]
                idx += 1
    elif name == '三角群':
        # 前三角(长机尖+2底) + 左后三角(3) + 右后三角(3)
        # 组内用 sf/sl，组之间用 sg；数量不足从最后(右后三角)往前减
        pts = [
            (-sf, -sl / 2), (-sf, sl / 2),
            (-sg, -sg), (-sg - sf, -sg - sl / 2), (-sg - sf, -sg + sl / 2),
            (-sg, sg), (-sg - sf, sg - sl / 2), (-sg - sf, sg + sl / 2),
        ]
        for i in range(1, n):
            if i - 1 < len(pts):
                off[i] = pts[i - 1]
            else:
                off[i] = [-(sg + sf), 0.0]
    return off
