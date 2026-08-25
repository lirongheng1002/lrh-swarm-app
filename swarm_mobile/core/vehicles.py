"""机队状态：每架机的状态对象 + 报文应用 + 机队注册表"""
import math
import time

MODE_ZH = {
    0: '稳定', 1: '特技', 2: '定高', 3: '自动', 4: '引导', 5: '悬停',
    6: '返航', 7: '环绕', 9: '降落', 11: '漂移', 13: '运动', 14: '翻转',
    15: '自调', 16: '定位', 17: '刹车', 18: '投掷', 19: '避障',
    20: '引导无GPS', 21: '智能返航', 22: '流量', 23: '跟随', 24: '之字',
    25: '系统ID', 26: '自转', 27: '自动返航', 28: '龟形',
}

MAV_CMD_ZH = {
    16: '航点', 22: '起飞', 21: '降落', 20: '返航', 30: '沿航线返航',
    82: '样条航点', 93: '盘旋定时', 94: '盘旋圈数', 189: '无限盘旋',
    115: '区域扫描', 178: '跳转', 177: '设定舵量',
    181: '继电器', 182: '继电器重复', 183: '投弹(舵机)', 184: '投弹(舵机重复)',
    211: '机械爪', 216: '喷洒',
}


class Vehicle:
    def __init__(self, sysid, name, role, offset):
        self.sysid = sysid
        self.name = name
        self.role = role                       # leader / follower
        self.offset = list(offset)             # [前方(机头方向,米), 右方(米), 高度差(米)]
        self.armed = False
        self.mode = None
        self.lat = self.lon = self.rel_alt = None
        self.gps_only = False    # True=位置来自原始GPS(未3D锁定兜底)，锁定后自动转False
        self.hdg = None
        self.vx = self.vy = 0.0
        self.voltage = None
        self.satellites = None
        self.fix_type = None
        self.hdop = None
        self.heartbeat_ts = 0.0
        self.pos_ts = 0.0
        self.link_ok = False
        self.link_err = ''
        self.mission = []
        self.mission_loaded = False
        self.mission_loading = False
        self.current_seq = None
        self.target = None                     # 最近一次编队目标 (lat, lon, alt, yaw)
        self.deviation = None                  # 实际位置与目标距离（米）
        self._throttled = False
        self.heartbeat_timeout = 5.0

    @property
    def online(self):
        return (time.time() - self.heartbeat_ts) < self.heartbeat_timeout

    @property
    def mode_zh(self):
        if self.mode is None:
            return '--'
        return MODE_ZH.get(self.mode, '模式%d' % self.mode)

    @property
    def speed(self):
        return math.hypot(self.vx, self.vy)


def apply_packet(fleet, src, msg, now=None):
    """把收到的 MAVLink 消息应用到机队状态（UI 与测试共用）"""
    now = now or time.time()
    v = fleet.get(src)
    if v is None:
        return
    t = msg.get_type()
    if t == 'HEARTBEAT':
        v.heartbeat_ts = now
        if msg.base_mode is not None:
            v.armed = bool(msg.base_mode & 0x80)
        v.mode = msg.custom_mode
        v.link_ok = True
    elif t == 'GLOBAL_POSITION_INT':
        v.lat = msg.lat / 1e7
        v.lon = msg.lon / 1e7
        v.gps_only = False       # 3D 锁定正式位置到达，清除兜底标记
        v.rel_alt = msg.relative_alt / 1000.0
        v.hdg = msg.hdg / 100.0
        v.vx = msg.vx / 100.0
        v.vy = msg.vy / 100.0
        v.pos_ts = now
    elif t == 'GPS_RAW_INT':
        v.satellites = msg.satellites_visible
        v.fix_type = msg.fix_type
        v.hdop = (msg.eph / 100.0) if msg.eph else None
        # 兜底位置：fix>=2 即有 GPS 原始坐标（正式位置消息要 3D 锁定才发）——
        # 有星未锁定时地图先画图标（机号照标），领导上电即可看到定位点
        if (v.lat is None and v.fix_type is not None and v.fix_type >= 2
                and msg.lat is not None and abs(msg.lat) > 10000):
            v.lat = msg.lat / 1e7
            v.lon = msg.lon / 1e7
            v.gps_only = True
    elif t == 'MISSION_CURRENT':
        v.current_seq = msg.seq
    elif t == 'BATTERY_STATUS':
        if msg.voltages:
            v.voltage = msg.voltages[0] / 1000.0


class Fleet:
    def __init__(self, config):
        self.cfg = config
        self.vehicles = {}
        for v in config['vehicles']:
            _veh = Vehicle(
                v['sysid'], v.get('name', '%d号机' % v['sysid']),
                v.get('role', 'follower'), v.get('offset', [0, 0, 0]))
            _veh.heartbeat_timeout = config['link'].get('heartbeat_timeout_s', 8)
            self.vehicles[v['sysid']] = _veh
        self.leader = next((v for v in self.vehicles.values()
                            if v.role == 'leader'), None)

    def get(self, sysid):
        return self.vehicles.get(sysid)

    def followers(self):
        return [v for v in self.vehicles.values() if v.role != 'leader']

    def all(self):
        return sorted(self.vehicles.values(), key=lambda v: v.sysid)
