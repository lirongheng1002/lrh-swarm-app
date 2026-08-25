"""配置加载与校验（config.yaml）"""
import os

import yaml

CONFIG_NAME = 'config.yaml'


def project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_config(path=None):
    if path:
        return path
    cand = os.path.join(project_root(), CONFIG_NAME)
    if os.path.exists(cand):
        return cand
    raise FileNotFoundError(
        '未找到 config.yaml。请把 config.yaml.example 复制一份并改名为 config.yaml，'
        '然后按注释修改服务器地址与飞机列表。')


def load_config(path=None):
    path = find_config(path)
    with open(path, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}

    srv = cfg.setdefault('server', {})
    srv.setdefault('host', '127.0.0.1')
    srv.setdefault('mode', 'per_port')
    srv.setdefault('per_port_base', 14550)
    srv.setdefault('shared_port', 14550)

    lk = cfg.setdefault('link', {})
    lk.setdefault('heartbeat_timeout_s', 18)
    lk.setdefault('position_timeout_s', 3)
    lk.setdefault('target_hz', 2)
    lk.setdefault('throttle', False)
    lk.setdefault('reconnect_s', 2)
    lk.setdefault('idle_timeout_s', 20)

    veh = cfg.setdefault('vehicles', [])
    if not veh:
        raise ValueError('配置里没有飞机（vehicles 为空），请检查 config.yaml')

    fm = cfg.setdefault('formation', {})
    fm.setdefault('grid_m', 10)
    fm.setdefault('min_spacing_m', 5)
    fm.setdefault('spacing_f', 5)
    fm.setdefault('spacing_l', 5)
    fm.setdefault('spacing_g', 10)
    fm.setdefault('rendezvous', None)

    b = cfg.setdefault('bomb', {})
    b.setdefault('servo', 6)
    b.setdefault('pwm', 2000)
    b.setdefault('count', 1)
    b.setdefault('time', 1)
    cfg.setdefault('takeoff', {}).setdefault('alt_m', 20)
    ui = cfg.setdefault('ui', {})
    ui.setdefault('language', 'zh')
    ui.setdefault('background', None)
    mp = cfg.setdefault('map', {})
    mp.setdefault('style', 'satellite')
    mp.setdefault('zoom', 17)
    mp.setdefault('center', None)
    mp.setdefault('gps_is_gcj', False)
    cfg['_path'] = path
    return cfg
