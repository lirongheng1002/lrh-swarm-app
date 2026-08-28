"""手机端机队控制逻辑（纯 Python，不依赖 Kivy，可独立冒烟测试）

复用桌面控制台 swarm_console 的核心：
- mavlink_bus ：每机一条 TCP 连服务器 per_port 端口，收包队列/限流/带宽统计
- commands    ：模式/解锁/起飞/降落/返航/投弹/限流/引导等指令封装
- vehicles    ：机队状态对象 + 报文应用 apply_packet（含卫星数/模式/位置）
- missions    ：任务下载/上传（MISSION 协议）
- formation   ：队形数学（机头方向相对偏移）+ 6 种预设

手机端只做薄调度：全队/单机动作 + 编队定时器 + 后台任务读写线程。
"""
import threading
import time

from .core import mavlink_bus, commands, vehicles, missions, formation

MODE_AUTO = 3
MODE_GUIDED = 4
MODE_RTL = 6
MODE_LAND = 9

IDLE_TIMEOUT_S = 30


def _veh_cfg_list(cfg):
    """从 config 构造 vehicles 配置列表（与桌面端一致）"""
    return [dict(v) for v in cfg['vehicles']]


class FleetApp:
    """机队控制中枢：一端连 UI（Clock 回调），一端连 core（MAVLink）"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.bus = None
        self.connected = False
        self.last_err = ''
        # 机队列表在初始化时就构建（未连接也能本地编辑任务/队形）
        self.fleet = self._build_fleet()    # sysid -> Vehicle
        # 编队
        self.formation_on = False
        self._fm_thread = None
        self._fm_stop = threading.Event()
        self._fm_lock = threading.Lock()
        # 任务读写线程结果回调
        self.on_mission_downloaded = None   # fn(sysid, items|None)
        self.on_mission_uploaded = None     # fn(sysid, ok)
        self.on_log = None                  # fn(text)

    def _build_fleet(self):
        fleet = {}
        for v in self.cfg['vehicles']:
            veh = vehicles.Vehicle(v['sysid'], v.get('name', str(v['sysid'])),
                                   v.get('role', 'follower'),
                                   list(v.get('offset', [0, 0, 0])))
            veh.heartbeat_timeout = self.cfg.get('link', {}).get('heartbeat_timeout_s', 18)
            fleet[v['sysid']] = veh
        return fleet

    def _reset_online_state(self):
        for v in self.fleet.values():
            v.heartbeat_ts = 0.0
            v.link_ok = False
            v.pos_ts = 0.0

    # ---------------- 连接 / 断开 ----------------
    def connect(self, host, base_port):
        self.disconnect()
        lk = self.cfg['link']
        bus_cfg = {
            'server': {'host': host, 'mode': 'per_port', 'per_port_base': base_port},
            'link': {
                'reconnect_s': lk.get('reconnect_s', 2),
                'throttle': lk.get('throttle', False),
                'idle_timeout_s': lk.get('idle_timeout_s', 20),
            },
            'vehicles': _veh_cfg_list(self.cfg),
        }
        self._reset_online_state()
        self.bus = mavlink_bus.LinkBus(bus_cfg, on_link=self._link_state)
        self.bus.start()
        self.connected = True
        self._log('已连接 %s:%s~%s' % (host, base_port, base_port + len(self.fleet) - 1))

    def _link_state(self, sysid, ok, err):
        """单个端口连接状态回调：失败原因进日志（带端口号）；成功由 tick 显示在线"""
        if ok or not err:
            return
        port = ''
        try:
            lnk = self.bus.links.get(sysid)
            if lnk:
                port = str(lnk.port)
        except Exception:
            pass
        if port:
            self._log('[端口%s] %s' % (port, err))
        else:
            self._log('%s' % err)

    def disconnect(self):
        if self.bus is not None:
            try:
                self.bus.stop()
            except Exception:
                pass
        self.bus = None
        self.connected = False
        self.formation_stop()
        self._log('已断开')

    # ---------------- 状态刷新（UI 定时器调用） ----------------
    def tick(self):
        """收包 -> 应用状态；返回更新集合供 UI 刷新"""
        if self.bus is None:
            return
        try:
            msgs = self.bus.drain()
            if msgs:
                for _ts, src, m in msgs:
                    vehicles.apply_packet(self.fleet, src, m)
        except Exception as e:
            self.last_err = str(e)
        self._request_gps_streams()

    def _request_gps_streams(self):
        # 每架在线机请求 GPS_RAW_INT(24) @2Hz，卫星颗数才显示（同桌面控制台 ui.py:3605）。
        # 只发一条、约40B/机，流量可忽略；离线后复位标记，重连自动补发（4G 抖动后自愈）。
        if self.bus is None:
            return
        for s, v in self.fleet.items():
            if not v.online:
                v._gps_req = False
                continue
            if getattr(v, '_gps_req', False):
                continue
            try:
                commands.set_message_interval(self.bus, s, 24, 500000)
                v._gps_req = True
            except Exception:
                pass

    # ---------------- 指令（全队 / 单机） ----------------
    def _send(self, sysid, fn):
        if self.bus is None or sysid not in self.fleet:
            return False
        try:
            ok = fn(self.bus, sysid)
            return ok
        except Exception as e:
            self._log('指令异常 %s: %s' % (self.fleet[sysid].name, e))
            return False

    def set_mode(self, sysid, mode):
        return self._send(sysid, lambda b, s: commands.set_mode(b, s, mode))

    def set_mode_all(self, mode):
        n = 0
        for s in self.fleet:
            if self.set_mode(s, mode):
                n += 1
        return n

    def set_speed_all(self, mps):
        """全队航速：对每架在线机发 DO_CHANGE_SPEED"""
        n = 0
        for s in self.fleet:
            v = self.fleet[s]
            if getattr(v, 'online', False) and v.link:
                try:
                    commands.change_speed(v.link, s, mps)
                    n += 1
                except Exception:
                    pass
        return n

    def set_speed(self, sysid, mps):
        """单机设巡航速度（DO_CHANGE_SPEED 178）"""
        v = self.fleet.get(sysid)
        if not v or not getattr(v, 'online', False) or not v.link:
            return 0
        try:
            commands.change_speed(v.link, sysid, mps)
        except Exception:
            return 0
        return 1

    def arm(self, sysid, on=True, force=False):
        return self._send(sysid, lambda b, s: commands.arm(b, s, on, force))

    def arm_all(self, on=True, force=False):
        n = 0
        for s in self.fleet:
            if self.arm(s, on, force):
                n += 1
        return n

    def takeoff(self, sysid, alt_m):
        return self._send(sysid, lambda b, s: commands.takeoff(b, s, alt_m))

    def takeoff_all(self, alt_m):
        n = 0
        for s in self.fleet:
            if self.takeoff(s, alt_m):
                n += 1
        return n

    def land(self, sysid):
        return self.set_mode(sysid, MODE_LAND)

    def land_all(self):
        return self.set_mode_all(MODE_LAND)

    def rtl(self, sysid):
        return self.set_mode(sysid, MODE_RTL)

    def rtl_all(self):
        return self.set_mode_all(MODE_RTL)

    def bomb(self, sysid, servo=None, pwm=None, count=None, time_s=None):
        b = self.cfg.get('bomb', {})
        servo = servo if servo is not None else b.get('servo', 6)
        pwm = pwm if pwm is not None else b.get('pwm', 2000)
        count = count if count is not None else b.get('count', 1)
        time_s = time_s if time_s is not None else b.get('time', 1)
        return self._send(sysid, lambda b_, s: commands.bomb_drop(b_, s, servo, pwm, count, time_s))

    def bomb_all(self, **kw):
        n = 0
        for s in self.fleet:
            if self.bomb(s, **kw):
                n += 1
        return n

    def auto_all(self):
        """全部切 AUTO 执行各自任务"""
        return self.set_mode_all(MODE_AUTO)

    def guided_target(self, sysid, lat, lon, alt_m):
        return self._send(sysid, lambda b, s: commands.guided_target(b, s, lat, lon, alt_m))

    def throttle_downlink(self, sysid):
        return self._send(sysid, lambda b, s: commands.throttle_downlink(b, s))

    # ---------------- 编队 ----------------
    def apply_preset(self, name):
        """应用队形预设：改写每架 offset[0]/[1]（前/右），返回 True"""
        n = len(self.fleet)
        fm = self.cfg.get('formation', {})
        offs = formation.preset_offsets(
            name, n,
            fm.get('spacing_f', 5), fm.get('spacing_l', 5), fm.get('spacing_g', 10))
        for i, s in enumerate(sorted(self.fleet)):
            self.fleet[s].offset[0] = offs[i][0]
            self.fleet[s].offset[1] = offs[i][1]
        self._log('队形预设：%s' % name)
        return True

    def set_spacings(self, sf, sl, sg):
        self.cfg.setdefault('formation', {})['spacing_f'] = sf
        self.cfg['formation']['spacing_l'] = sl
        self.cfg['formation']['spacing_g'] = sg
        self._log('间距已设置 前%sm 左右%sm 小组%sm' % (sf, sl, sg))

    def formation_start(self, fleet_alt):
        """开始编队：fleet_alt=统一目标高度；每 0.5s 给每架僚机发引导目标。长机=sysid1"""
        if self.formation_on:
            return
        with self._fm_lock:
            self._fm_stop.clear()
            self._fm_thread = threading.Thread(target=self._formation_loop,
                                               args=(fleet_alt,), daemon=True)
            self._fm_thread.start()
        self.formation_on = True
        self._log('编队开始 目标高度 %sm' % fleet_alt)

    def formation_stop(self):
        if not self.formation_on:
            return
        with self._fm_lock:
            self._fm_stop.set()
        self.formation_on = False
        self._log('编队暂停')

    def _formation_loop(self, fleet_alt):
        bus = self.bus
        leader = self.fleet.get(1)
        while not self._fm_stop.is_set() and bus is not None:
            if leader is not None and leader.lat is not None:
                for s, v in self.fleet.items():
                    if s == 1:
                        continue
                    commands.set_mode(bus, s, MODE_GUIDED)
                    lat, lon, alt, hdg = formation.target_for(leader, v)
                    commands.guided_target(bus, s, lat, lon, fleet_alt + v.offset[2], hdg)
            self._fm_stop.wait(0.5)

    # ---------------- 任务 ----------------
    def download_mission(self, sysid):
        """后台线程读取任务，完成后回调 on_mission_downloaded"""
        def _run():
            mav = self.bus.get_mav(sysid) if self.bus else None
            items = None
            if mav is not None:
                items = missions.request_mission(self.bus, self.fleet[sysid], log=self._log)
                if items:
                    self.fleet[sysid].mission = items
                    self.fleet[sysid].mission_loaded = True
                    self._log('%s 任务下载 %d 条' % (self.fleet[sysid].name, len(items)))
            if self.on_mission_downloaded:
                self.on_mission_downloaded(sysid, items)
        threading.Thread(target=_run, daemon=True).start()

    def upload_mission(self, sysid, items=None):
        """后台线程上传任务（默认传选中机当前 mission）"""
        items = items if items is not None else self.fleet[sysid].mission
        if not items:
            self._log('%s 无任务可上传（先下载或设置航点）' % self.fleet[sysid].name)
            return False

        def _run():
            ok = missions.write_mission(self.bus, self.fleet[sysid], items, log=self._log)
            if ok:
                self.fleet[sysid].mission = items
                self.fleet[sysid].mission_loaded = True
            if self.on_mission_uploaded:
                self.on_mission_uploaded(sysid, ok)
        threading.Thread(target=_run, daemon=True).start()
        return True

    def append_waypoint(self, sysid, lat, lon, alt_m, cmd=16):
        """追加一个航点到任务末尾（本地列表，需 upload_mission 才写入飞机）"""
        v = self.fleet[sysid]
        seq = len(v.mission)
        v.mission.append({
            'seq': seq, 'cmd': cmd, 'lat': lat, 'lon': lon, 'alt': alt_m,
            'p1': 0, 'p2': 0, 'p3': 0, 'p4': 0, 'frame': 3,
        })
        self._log('%s 已设置航点 #%d (%.6f, %.6f) %sm ——请点「上传任务」写入飞机'
                  % (v.name, seq, lat, lon, alt_m))

    def add_bomb_after(self, sysid, after_seq):
        """在 after_seq 航点后插入投弹点(184)；插入位置用 after_seq+1"""
        v = self.fleet[sysid]
        if not v.mission or after_seq < 0 or after_seq >= len(v.mission):
            self._log('%s 无选中航点可插入投弹' % v.name)
            return False
        b = self.cfg.get('bomb', {})
        bomb = {'seq': 0, 'cmd': 184,
                'lat': v.mission[after_seq]['lat'], 'lon': v.mission[after_seq]['lon'],
                'alt': v.mission[after_seq]['alt'],
                'p1': b.get('servo', 6), 'p2': b.get('pwm', 2000),
                'p3': b.get('count', 1), 'p4': b.get('time', 1), 'frame': 3}
        v.mission.insert(after_seq + 1, bomb)
        for i, it in enumerate(v.mission):
            it['seq'] = i
        self._log('%s 已在航点 #%d 后插入投弹点（共 %d 条）——请点「上传任务」'
                  % (v.name, after_seq, len(v.mission)))
        return True

    def clear_mission(self, sysid):
        v = self.fleet[sysid]
        v.mission = []
        v.mission_loaded = False
        self._log('%s 任务已清空（本地）' % v.name)

    # ---------------- 状态查询 ----------------
    def online_count(self):
        return sum(1 for v in self.fleet.values() if v.online)

    def vehicle(self, sysid):
        return self.fleet.get(sysid)

    def _log(self, text):
        if self.on_log:
            try:
                self.on_log(text)
            except Exception:
                pass