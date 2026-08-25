"""手机 APP 核心冒烟测试（不依赖 Kivy，只测 MAVLink 链路逻辑）

流程：启动 mock_relay（10 架模拟机）→ FleetApp 连接 → 验证
  ① 连接/心跳/在线数
  ② 全队解锁（armed 状态变化）
  ③ 全队切自动与切模式
  ④ 全队起飞（相对高度变化）
  ⑤ 任务下载（MISSION 协议，mock 内置 6 航点）
  ⑥ 队形预设 + 编队启停（无人机侧不验证目标）
  ⑦ 断开

运行：python smoke_mobile.py
"""
import subprocess
import sys
import time

MOCK_RELAY = r'D:\1-DSHarness\swarm-console\mock_relay.py'
BASE_PORT = 15650
COUNT = 10


def main():
    print('=== 手机 APP 核心冒烟 ===')
    proc = subprocess.Popen([sys.executable, MOCK_RELAY, str(BASE_PORT), str(COUNT)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        core_smoke()
    finally:
        proc.terminate()

    print('全部 PASS (ALL PASS)')


def core_smoke():
    import os
    import sys as _sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from swarm_mobile.fleet import FleetApp

    cfg = {
        'link': {'heartbeat_timeout_s': 8, 'throttle': False, 'reconnect_s': 1,
                 'idle_timeout_s': 15},
        'vehicles': [{'sysid': i, 'name': '%d号机' % i,
                      'role': 'leader' if i == 1 else 'follower', 'offset': [0, 0, 0]}
                     for i in range(1, COUNT + 1)],
        'takeoff': {'alt_m': 20}, 'bomb': {'servo': 6, 'pwm': 2000, 'count': 1, 'time': 1},
        'formation': {'spacing_f': 5, 'spacing_l': 5, 'spacing_g': 10},
    }
    logs = []

    def _log(t):
        logs.append(t)
        print('  LOG:', t)

    app = FleetApp(cfg)
    app.on_log = _log
    n = 0
    for t in range(30):
        app.connect('127.0.0.1', BASE_PORT)
        for _ in range(6):
            app.tick()
            time.sleep(0.5)
        if app.online_count() >= 8:
            n = app.online_count()
            break
        app.disconnect()
        time.sleep(1)
    assert n >= 8, '在线数 %d < 8' % n
    print('① 连接+心跳 PASS：在线 %d/%d' % (n, COUNT))

    # ② 全队解锁
    ok = app.arm_all(True)
    assert ok >= 8, '解锁发送数 %d < 8' % ok
    for _ in range(4):
        app.tick()
        time.sleep(0.5)
    armed = [s for s, v in app.fleet.items() if v.armed]
    assert len(armed) >= 8, '解锁后 armed 数 %d < 8' % len(armed)
    print('② 全队解锁 PASS：%d 架已解锁' % len(armed))

    # ③ 全队切自动 + 单机切模式
    ok = app.set_mode_all(3)
    assert ok >= 8
    ok1 = app.set_mode(2, 4)
    assert ok1
    for _ in range(4):
        app.tick()
        time.sleep(0.5)
    m2 = app.fleet[2].mode
    assert m2 == 4, '2号机模式 %s != 4' % m2
    print('③ 切模式 PASS：全队 AUTO，2号机 GUIDED')

    # ④ 全队起飞
    ok = app.takeoff_all(20)
    assert ok >= 8
    for _ in range(6):
        app.tick()
        time.sleep(0.5)
    alts = [v.rel_alt for v in app.fleet.values() if v.rel_alt and v.rel_alt > 1]
    assert len(alts) >= 8, '起飞后高度>1m 的机 %d < 8' % len(alts)
    print('④ 全队起飞 PASS：%d 架升空（示例高度 %s m）' % (len(alts), int(alts[0])))

    # ⑤ 任务下载（后台线程 + 回调）
    got = {}

    def _on_dl(sysid, items):
        got['items'] = items

    app.on_mission_downloaded = _on_dl
    app.download_mission(1)
    t0 = time.time()
    while 'items' not in got and time.time() - t0 < 10:
        app.tick()
        time.sleep(0.3)
    items = got.get('items')
    assert items and len(items) == 6, '任务下载结果 %r' % (items,)
    print('⑤ 任务下载 PASS：%d 条航点' % len(items))

    # ⑥ 队形预设 + 编队启停
    app.apply_preset('人字形')
    off2 = app.fleet[2].offset
    assert off2[0] < 0 and abs(off2[1]) > 0, '人字形 2号机偏移 %s' % off2
    app.formation_start(30)
    assert app.formation_on
    for _ in range(4):
        app.tick()
        time.sleep(0.5)
    app.formation_stop()
    assert not app.formation_on
    print('⑥ 队形 PASS：人字形偏移 %s，编队启停正常' % off2)

    # ⑦ 断开
    app.disconnect()
    print('⑦ 断开 PASS')


if __name__ == '__main__':
    main()