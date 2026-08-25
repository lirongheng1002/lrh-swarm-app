"""任务读取与航点设置（MAVLink MISSION 协议）"""
import time

MISSION_TIMEOUT = 3.0
ITEM_TIMEOUT = 2.0


def request_mission(bus, vehicle, log=None):
    """读取某架机的完整任务，返回航点列表；失败返回 None"""
    sysid = vehicle.sysid
    mav = bus.get_mav(sysid)
    if mav is None:
        if log:
            log('%s: 链路未连接，无法读取任务' % vehicle.name, 'warn')
        return None

    def w(pred, t):
        return bus.wait_for(pred, t)

    bus.send(sysid, mav.mission_request_list_encode(sysid, 1))
    count_msg = w(lambda s, m: s == sysid and m.get_type() == 'MISSION_COUNT',
                  MISSION_TIMEOUT)
    if count_msg is None:
        if log:
            log('%s: 任务读取超时（无回复），请确认该机已连接' % vehicle.name, 'warn')
        return None
    count = count_msg.count
    items = []
    for i in range(count):
        got = None
        for _ in range(3):
            bus.send(sysid, mav.mission_request_int_encode(sysid, 1, i))
            got = w(lambda s, m, i=i: s == sysid
                    and m.get_type() == 'MISSION_ITEM_INT' and m.seq == i,
                    ITEM_TIMEOUT)
            if got is not None:
                break
        if got is None:
            if log:
                log('%s: 航点 %d 读取超时' % (vehicle.name, i), 'warn')
            break
        items.append(_parse_item(got))
    bus.send(sysid, mav.mission_ack_encode(sysid, 1, 0))
    return items


def _parse_item(m):
    def _ll(x):
        return x / 1e7 if abs(x) > 1e6 else x

    return {
        'seq': m.seq,
        'cmd': m.command,
        'lat': _ll(m.x),
        'lon': _ll(m.y),
        'alt': m.z,
        'p1': m.param1, 'p2': m.param2, 'p3': m.param3, 'p4': m.param4,
        'frame': m.frame,
    }


def write_mission(bus, vehicle, items, log=None):
    """上传任务到飞机（MISSION 写协议）；成功返回 True"""
    sysid = vehicle.sysid
    mav = bus.get_mav(sysid)
    if mav is None:
        if log:
            log('%s: 链路未连接，无法上传任务' % vehicle.name, 'warn')
        return False
    if not items:
        # 空任务 = 清除飞机上的任务（MISSION_COUNT=0 + ACK）
        bus.send(sysid, mav.mission_count_encode(sysid, 1, 0))
        bus.send(sysid, mav.mission_ack_encode(sysid, 1, 0))
        if log:
            log('%s: 已发送空任务（清除原任务）' % vehicle.name, 'ok')
        return True

    def w(pred, t):
        return bus.wait_for(pred, t)

    bus.send(sysid, mav.mission_count_encode(sysid, 1, len(items)))
    for i, it in enumerate(items):
        req = w(lambda s, m, i=i: s == sysid
                and m.get_type() == 'MISSION_REQUEST' and m.seq == i,
                MISSION_TIMEOUT)
        if req is None:
            if log:
                log('%s: 飞机未响应航点 %d 请求，上传中断' % (vehicle.name, i), 'warn')
            return False
        bus.send(sysid, mav.mission_item_int_encode(
            sysid, 1, it['seq'], it.get('frame', 3), it['cmd'], 0, 1,
            it.get('p1', 0), it.get('p2', 0), it.get('p3', 0), it.get('p4', 0),
            int(it['lat'] * 1e7), int(it['lon'] * 1e7), it.get('alt', 0)))
    # 等完成确认或错误
    ack = w(lambda s, m: s == sysid and m.get_type() == 'MISSION_ACK', 2)
    if ack is not None and getattr(ack, 'type', 0) != 0:
        if log:
            log('%s: 上传被拒绝(结果%d)' % (vehicle.name, ack.type), 'warn')
        return False
    bus.send(sysid, mav.mission_ack_encode(sysid, 1, 0))
    return True
