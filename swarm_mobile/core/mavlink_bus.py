"""MAVLink 连接总线
- per_port：每架机一个 TCP 连接（阿里云服务器把端口转发到对应飞机）
- shared  ：单条 TCP 流汇聚全部飞机，按 sysid 区分
- 收包统一进 inbox（Condition 保护）：UI 用 drain() 轮询，协议握手用 wait_for()
- 统计每机上下行字节，供带宽面板显示（验证 4G 流量已大幅下降）
"""
import collections
import logging
import threading
import time

from pymavlink import mavutil

log = logging.getLogger('swarm.bus')

# 这些协议消息不参与 UI 轮询（留给任务读写的 wait_for 消费）
DRAIN_SKIP_TYPES = frozenset([
    'MISSION_COUNT', 'MISSION_ITEM', 'MISSION_ITEM_INT',
    'MISSION_REQUEST', 'MISSION_REQUEST_INT', 'MISSION_REQUEST_LIST',
    'MISSION_ACK',
    'PARAM_VALUE',        # 参数读写（PARAM_REQUEST_READ/PARAM_SET 的回复），留给 wait_for
])


def _pkt_len(msg):
    """消息在链路上的字节长度（用于带宽统计，估不到时用常量兜底）"""
    try:
        b = msg.get_msgbuf()
        if b:
            return len(b)
    except Exception:
        pass
    return 32


class Link:
    """单条 TCP 连接；sysid 非 None 表示专用连接（只接受该机包）"""

    def __init__(self, bus, host, port, sysid=None):
        self.bus = bus
        self.host = host
        self.port = port
        self.sysid = sysid
        self.mav = None
        self.online = False
        self.thread = None
        self._stop = False
        self._last_data = 0.0
        self._idle = False
        self._has_pkt = False

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name='link-%s' % self.port)
        self.thread.start()

    def stop(self):
        # 只设停止标志，不主动关 socket——让读线程在 0.5s 超时后自己干净退出
        # （避免从主线程关 socket 导致读线程抛 WinError 10038 掉线）
        self._stop = True

    def _run(self):
        import socket
        idle_timeout = self.bus.cfg['link'].get('idle_timeout_s', 20)
        reconnect_s = self.bus.cfg['link'].get('reconnect_s', 2)
        n_fail = 0
        while not self._stop:
            try:
                # 连接前先探测（8s 超时）：pymavlink 的 tcp 连接无超时，
                # 手机 4G 不通时会长时间卡住没反应 —— 探测保证快速失败+自动重试
                _s = socket.create_connection((self.host, self.port), timeout=8)
                _s.close()
                self.mav = mavutil.mavlink_connection(
                    'tcp:%s:%s' % (self.host, self.port),
                    source_system=255, source_component=190)
                self.online = True
                self._last_data = time.time()
                self._idle = False
                self._has_pkt = False
                n_fail = 0
                self.bus._on_link(self.sysid, True, None)
            except Exception as e:
                self.online = False
                n_fail += 1
                # 失败原因进日志（前 3 次每次记，之后每 5 次记一行，不刷屏）
                if n_fail <= 3 or n_fail % 5 == 0:
                    self.bus._on_link(self.sysid, False,
                                      '连接失败(第%d次，每%ds自动重试)：%s'
                                      % (n_fail, reconnect_s, e))
                time.sleep(reconnect_s)
                continue
            try:
                while not self._stop:
                    m = self.mav.recv_match(blocking=True, timeout=0.2)
                    if m is None:
                        # 无数据超时：从未收到数据=空端口(60s长退避)；曾收到过=链路中断(快速重连)
                        if time.time() - self._last_data > idle_timeout:
                            self._idle = not self._has_pkt
                            break
                        continue
                    self._last_data = time.time()
                    self._idle = False
                    self._has_pkt = True
                    src = m.get_srcSystem()
                    if self.sysid is not None and src not in (self.sysid, 0):
                        continue
                    self.bus._on_packet(src, m)
            except Exception as e:
                self.online = False
                self.bus._on_link(self.sysid, False, str(e))
            finally:
                try:
                    if self.mav is not None:
                        self.mav.close()
                except Exception:
                    pass
                self.mav = None
            if not self._stop:
                # 空闲端口 60 秒重试一次；有飞机/出错的按 reconnect_s 快速重连
                time.sleep(60 if self._idle else self.bus.cfg['link']['reconnect_s'])


class LinkBus:
    def __init__(self, config, on_link=None):
        self.cfg = config
        self.on_link = on_link
        self.sysids = [v['sysid'] for v in config['vehicles']]
        self.links = {}                    # sysid -> Link（shared 时键为 None）
        self._cond = threading.Condition()
        self._inbox = collections.deque(maxlen=8000)
        self._up = {s: 0 for s in self.sysids}
        self._down = {s: 0 for s in self.sysids}
        self.started = False

    # ---------------- 生命周期 ----------------
    def start(self):
        srv = self.cfg['server']
        host = srv['host']
        if srv['mode'] == 'shared':
            link = Link(self, host, srv['shared_port'], None)
            link.start()
            self.links[None] = link
        else:
            base = srv['per_port_base']
            for i, s in enumerate(self.sysids):
                link = Link(self, host, base + i, s)
                link.start()
                self.links[s] = link
                time.sleep(0.15)   # 错开建立连接，避免10路同时涌入服务器
        self.started = True

    def stop(self):
        self.started = False
        # 只设停止标志、不等待线程（线程在 0.2s 超时后自行退出），断开即时响应不卡顿
        for link in self.links.values():
            link.stop()

    def get_mav(self, sysid):
        """取该机所在链路的 MAVLink 方言对象（有 encode 方法，用于构建消息）"""
        link = self.links.get(sysid) or self.links.get(None)
        if link is None or link.mav is None:
            return None
        return link.mav.mav   # conn.mav 才是 MAVLink 方言，连接对象上没有 encode

    def send(self, sysid, msg):
        """发送一个已编码消息；返回是否发送成功"""
        link = self.links.get(sysid) or self.links.get(None)
        if link is None or link.mav is None:
            return False
        try:
            link.mav.mav.send(msg)   # 方言对象才有 send（连接对象只有 recv 等）
            with self._cond:
                self._up[sysid] = self._up.get(sysid, 0) + _pkt_len(msg)
            return True
        except Exception:
            return False

    def connected_count(self):
        return sum(1 for l in self.links.values() if l.online)

    # ---------------- 收包 ----------------
    def _on_link(self, sysid, ok, err):
        if self.on_link:
            try:
                self.on_link(sysid, ok, err)
            except Exception:
                pass

    def _on_packet(self, src, msg):
        with self._cond:
            self._inbox.append((time.time(), src, msg))
            self._down[src] = self._down.get(src, 0) + _pkt_len(msg)
            self._cond.notify_all()

    def drain(self, skip=DRAIN_SKIP_TYPES):
        """非阻塞取走一批包（skip 中的类型留给 wait_for，不被 UI 消费）"""
        with self._cond:
            if skip:
                keep = [p for p in self._inbox if p[2].get_type() in skip]
                got = [p for p in self._inbox if p[2].get_type() not in skip]
                self._inbox.clear()
                self._inbox.extend(keep)
            else:
                got = list(self._inbox)
                self._inbox.clear()
        return got

    def wait_for(self, pred, timeout):
        """阻塞等待满足条件的包（供任务读写等协议握手），超时返回 None"""
        end = time.time() + timeout
        with self._cond:
            while True:
                for i, (ts, src, msg) in enumerate(self._inbox):
                    if pred(src, msg):
                        del self._inbox[i]
                        return msg
                rem = end - time.time()
                if rem <= 0:
                    return None
                self._cond.wait(min(rem, 0.5))

    # ---------------- 带宽统计 ----------------
    def bw_totals(self):
        """返回每机累计上下行字节 {sysid: {up, down}}"""
        with self._cond:
            return {s: {'up': self._up[s], 'down': self._down[s]}
                    for s in self.sysids}
