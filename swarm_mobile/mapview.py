"""高德卫星地图（Kivy 纯控件，无额外依赖）

- 瓦片源：webst 高德瓦片（卫星图专用域名！），style=6 = 卫星图（瓦片为 GCJ-02 切片）
- 点击瓦片 → 反算经纬（GCJ -> WGS84）→ 回调 on_pick(lat, lng)
- 3x3 网格，每瓦 size_hint=(1/3,1/3) 自动拉伸满屏——竖屏/横屏都铺满
- 缩放 Slider（3~18）；中心默认=首在线机坐标，否则 config map 中心或默认
"""
import math
import os
import threading

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.widget import Widget
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.graphics import Color, Rectangle, Line, Ellipse
from kivy.core.text import LabelBase
from kivy.core.text import Label as CoreLabel
from math import hypot

from .widgets import RoundedButton

# ---------------- 高德瓦片（三种图源，对齐桌面 LRHwrkzxt map_tiles.py） ----------------
# street=街道 / satellite=卫星 / hybrid=卫星+路网（桌面同款 TILE_SERVERS）
TILE_SERVERS = {
    'street':    'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
    'satellite': 'https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}',
    'hybrid':    'https://webst0{s}.is.autonavi.com/appmaptile?style=8&x={x}&y={y}&z={z}',
}
# 默认图源=卫星（与手机现有显示一致；切换图源只需设 MAP_STYLE）
MAP_STYLE = 'satellite'
_SUB = ['1', '2', '3', '4']
_UA = 'Mozilla/5.0 (Linux; Android) LRH-swarm/1.2'

# ---- 触控灵敏度参数（领导要求便于后续调整：改这里即可）----
_PINCH_THRESHOLD = 1.008    # 双指捏合阈值：距离变化超过 0.8% 即触发一次缩放（原 1.03，提高 4 倍灵敏度）
_PINCH_STEP_DIST = 0.08     # 捏合距离每增加 8% 再跳一级（快速连续缩放；配合阈值=平滑跟手）
_PAN_DEBOUNCE = 0.05        # 单指平移防抖：0.05s（原 0.15s，拖动更跟手）
_ZOOM_MIN = 3
_ZOOM_MAX = 18

# Tile disk cache: already-viewed tiles read from local disk instantly (same as desktop console)
_TILE_CACHE_DIR = {'d': None}
# 后台落盘限流：最多 3 路并发写缓存（旧版 9 路直连不轰服务器，新版不要 18 路）
_DL_SEM = threading.Semaphore(3)


def _tile_cache_dir():
    # prefer app user data dir (writable on phone); fall back beside the project
    if _TILE_CACHE_DIR['d'] is None:
        d = None
        try:
            from kivy.app import App
            d = App.get_running_app().user_data_dir
        except Exception:
            d = None
        if not d:
            d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tile_cache')
        d = os.path.join(d, 'tile_cache')
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            d = None
        _TILE_CACHE_DIR['d'] = d
    return _TILE_CACHE_DIR['d']

# ---------------- GCJ-02 / WGS-84 ----------------
def out_of_china(lng, lat):
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _t_lat(x, y):
    ret = (-100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y
           + 0.2 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * math.pi) +
            20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) +
            40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) +
            320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _t_lng(x, y):
    ret = (300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y
           + 0.1 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * math.pi) +
            20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) +
            40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) +
            300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat, lng):
    if out_of_china(lng, lat):
        return lat, lng
    a = 6378245.0
    ee = 0.00669342162296594323
    d_lat = _t_lat(lng - 105.0, lat - 35.0)
    d_lng = _t_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - ee * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((a * (1 - ee)) / (magic * sqrt_magic) * math.pi)
    d_lng = (d_lng * 180.0) / (a / sqrt_magic * math.cos(rad_lat) * math.pi)
    return lat + d_lat, lng + d_lng


def gcj02_to_wgs84(lat, lng):
    if out_of_china(lng, lat):
        return lat, lng
    lat2, lng2 = wgs84_to_gcj02(lat, lng)
    return lat - (lat2 - lat), lng - (lng2 - lng)


# ---------------- 瓦片数学 ----------------
def _lng_to_px(lng, z):
    n = 2 ** z
    return (lng + 180.0) / 360.0 * n * 256.0


def _lat_to_px(lat, z):
    n = 2 ** z
    lat_rad = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n * 256.0
    return y


def _px_to_lng(x, z):
    n = 2 ** z
    return x / (n * 256.0) * 360.0 - 180.0


def _px_to_lat(y, z):
    n = 2 ** z
    t = 1.0 - 2.0 * y / (n * 256.0)
    return math.degrees(math.atan(math.sinh(math.pi * t)))


# ---------------- 通用按钮 ----------------
def _mk_button(text, color, cb, **kw):
    kw.setdefault('size_hint_y', None)
    kw.setdefault('height', '44dp')
    kw.setdefault('font_size', '15sp')
    kw.setdefault('radius', '10dp')
    b = RoundedButton(text=text, background_color=color, **kw)
    b.bind(on_release=lambda *a: cb())
    return b


# ---------------- 单瓦片 ----------------
class TileCell(AsyncImage):
    # 一格瓦片：本地磁盘缓存优先，未缓存后台下载落盘，失败换子域重试
    def __init__(self, tx=0, ty=0, z=15, on_tap=None, **kw):
        kw.setdefault('keep_ratio', False)
        kw.setdefault('allow_stretch', True)
        super(TileCell, self).__init__(**kw)
        self._tx = tx
        self._ty = ty
        self._z = z
        self._on_tap = on_tap
        self._lbl = None
        self._retry = -1
        self._loaded = False
        self._fetching = False
        self._refresh_source()
        self.bind(on_error=self._on_tile_error)
        self.bind(on_load=self._on_tile_loaded)

    def _tile_url(self, s):
        return TILE_SERVERS.get(MAP_STYLE, TILE_SERVERS['satellite']).format(
            s=s, x=self._tx, y=self._ty, z=self._z)

    def _cache_path(self, s):
        d = _tile_cache_dir()
        if not d:
            return None
        return os.path.join(d, 't_%s_%d_%d_%d.jpg' % (s, self._tx, self._ty, self._z))

    def _refresh_source(self):
        # 有效磁盘缓存 -> 本地秒读；否则直接 source=瓦片网址（Kivy 自带直连=
        # 旧版已验证显示路径，任何缓存/线程异常都不影响出图）。
        # 后台线程只做「预下载落盘」加速下次打开，失败绝不阻塞显示。
        if self._fetching:
            return
        s = _SUB[(self._tx * 7 + self._ty) % 4]
        p = self._cache_path(s)
        if p and os.path.exists(p) and os.path.getsize(p) > 200:
            self.source = p
        else:
            self.source = self._tile_url(s)
            self._start_download(s)

    def _start_download(self, s):
        def _dl():
            import urllib.request
            data = None
            try:
                with _DL_SEM:
                    req = urllib.request.Request(self._tile_url(s), headers={'User-Agent': _UA})
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        data = resp.read()
            except Exception:
                data = None
            Clock.schedule_once(lambda dt: self._on_downloaded(s, data))
        threading.Thread(target=_dl, daemon=True).start()

    def _on_downloaded(self, s, data):
        self._fetching = False
        try:
            if data and len(data) > 200 and data[:2] == b'\xff\xd8':
                p = self._cache_path(s)
                if p:
                    try:
                        with open(p, 'wb') as f:
                            f.write(data)
                    except Exception:
                        pass
                if not self._loaded:
                    self.source = p if p else self._tile_url(s)
            else:
                self._on_download_failed()
        except Exception:
            self._on_download_failed()

    def _on_download_failed(self):
        self._retry += 1
        if self._retry < 8:
            s = _SUB[(self._tx * 7 + self._ty + self._retry) % 4]
            self._start_download(s)
        else:
            # 重试耗尽：复位下载标志，交给 3s 自愈(_tile_recover)重新尝试
            self._fetching = False

    def _on_tile_error(self, *a):
        # 加载失败：若来源是本地缓存文件，删掉损坏缓存回退直连网址，再走重试
        try:
            _src = self.source
            if _src and str(_src).startswith('/') and str(_src).endswith(('.jpg', '.png')):
                p = _src if isinstance(_src, str) else str(_src)
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
                self.source = self._tile_url(_SUB[(self._tx * 7 + self._ty) % 4])
        except Exception:
            pass
        self._on_download_failed()

    def _on_tile_loaded(self, *a):
        # tile loaded ok: mark loaded and reset retry counter
        self._loaded = True
        self._retry = -1

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if self._on_tap:
                self._on_tap(self, touch.pos)
            return True
        return super(TileCell, self).on_touch_down(touch)


# ---------------- 卫星地图页 ----------------
class _RouteLayer(Widget):
    """地图覆盖层：航点圆点+连线 + 飞机位置标记（<8颗星灰，>=8颗星蓝）"""
    def __init__(self, map_ref, **kw):
        kw.setdefault('size_hint', (1, 1))
        super(_RouteLayer, self).__init__(**kw)
        self._map = map_ref
        self._route = []
        self._planes = []
        self._aircraft_labels = {}
        self.bind(size=lambda *a: self._redraw())
        self.bind(pos=lambda *a: self._redraw())

    def set_route(self, route):
        self._route = list(route)
        self._redraw()

    def set_aircraft(self, planes):
        """planes: [(sysid, lat, lon, satellites), ...]"""
        self._planes = list(planes)
        self._redraw()

    def _redraw(self, *a):
        self.canvas.clear()
        m = self._map
        pc = getattr(m, '_px_center', None)
        if m._grid is None or not pc:
            return
        z = m._zoom
        cx_px, cy_px = pc
        g = m._grid
        gx, gy = g.center_x, g.center_y
        # 画航线（航点圆点 + 黄色连线）
        pts = []
        for (lat, lon) in self._route:
            try:
                lat_gcj, lng_gcj = self._map._to_disp(lat, lon)
                px_x = _lng_to_px(lng_gcj, z)
                px_y = _lat_to_px(lat_gcj, z)
                sx, sy = m._w2s(px_x, px_y)
                pts.append((sx, sy))
            except Exception:
                pass
        with self.canvas:
            if pts:
                Color(1, 0.75, 0.1, 1)
                Line(points=[c for p in pts for c in p], width=2)
                for (sx, sy) in pts:
                    Color(0.1, 0.7, 1, 1)
                    Ellipse(pos=(sx - 6, sy - 6), size=(12, 12))
            # 飞机位置标记（圆点 + 机号）
            W = getattr(m, 'width', 0)
            H = getattr(m, 'height', 0)
            for (sysid, lat, lon, satellites) in self._planes:
                try:
                    lat_gcj, lng_gcj = self._map._to_disp(lat, lon)
                    px_x = _lng_to_px(lng_gcj, z)
                    px_y = _lat_to_px(lat_gcj, z)
                    sx, sy = m._w2s(px_x, px_y)
                    if -20 <= sx <= W + 20 and -20 <= sy <= H + 20:
                        if satellites is not None and satellites >= 8:
                            Color(0.1, 0.6, 1, 1)
                        else:
                            Color(0.55, 0.55, 0.55, 1)
                        Ellipse(pos=(sx - 9, sy - 9), size=(18, 18))
                except Exception:
                    pass
        self._sync_aircraft_labels()

    def _sync_aircraft_labels(self):
        """用 Label 控件在飞机点旁显示机号"""
        m = self._map
        pc = getattr(m, '_px_center', None)
        for k in list(self._aircraft_labels.keys()):
            try:
                self.remove_widget(self._aircraft_labels[k])
            except Exception:
                pass
        self._aircraft_labels = {}
        if not self._planes or m._grid is None or not pc:
            return
        z = m._zoom
        cx_px, cy_px = pc
        gx, gy = m._grid.center_x, m._grid.center_y
        for (sysid, lat, lon, satellites) in self._planes:
            try:
                lat_gcj, lng_gcj = self._map._to_disp(lat, lon)
                px_x = _lng_to_px(lng_gcj, z)
                px_y = _lat_to_px(lat_gcj, z)
                sx, sy = m._w2s(px_x, px_y)
                col = (0.1, 0.6, 1, 1) if (satellites is not None and satellites >= 8) else (0.55, 0.55, 0.55, 1)
                lbl = Label(text=str(sysid), font_size='16sp', bold=True,
                            color=(1, 0.18, 0.18, 1), size_hint=(None, None),
                            size=(30, 26), halign='center', valign='middle')
                # 背景色圈
                from kivy.graphics import Color, Ellipse
                with lbl.canvas.before:
                    Color(0, 0, 0, 0.55)
                    Ellipse(pos=(0, 0), size=(26, 26))
                lbl.pos = (sx + 12, sy - 13)
                self.add_widget(lbl)
                self._aircraft_labels[sysid] = lbl
            except Exception:
                pass


class MapPage(BoxLayout):
    """卫星地图：3x3 瓦片铺满（横竖屏自适应）+ 双指捏合缩放 + 关闭按钮。

    手势：
    - 单指点击/抬起：取点回调 on_pick(lat, lng)
    - 双指捏合/张开：缩放地图（zoom 3~18）
    """
    def __init__(self, center=(31.2304, 121.4737), zoom=15, on_pick=None,
                 on_close=None, embedded=False, on_double_tap=None,
                 gps_is_gcj=False, **kw):
        kw.setdefault('orientation', 'vertical')
        kw.setdefault('spacing', 4)
        kw.setdefault('padding', 4)
        super(MapPage, self).__init__(**kw)
        self.gps_is_gcj = bool(gps_is_gcj)   # GPS 已是 GCJ 则不重复转换
        self._calib = None   # 定位校准：[(GPS经, GPS纬, 地图经, 地图纬), ...] 两定点相似变换
        self._calib_from = None   # 校准来源描述（如 '手动' ）
        self._to_disp = self._disp_or_gcj
        self._to_air = self._air_or_gcj
        self._center = center          # (lat, lng) WGS84
        self._zoom = max(3, min(18, int(zoom)))
        self._on_pick = on_pick
        self._on_close = on_close
        self._on_double_tap = on_double_tap
        self._embedded = embedded
        self._last_tap_t = 0
        self._grid = None
        # 航点长按拖动状态
        self._drag_points = []
        self._drag_idx = None
        self._drag_touch_id = None
        self._long_press_uid = None
        self._down_pos = None
        self._drag_cb = None
        self._pending_pick = None    # (lat,lng) 待加点（双击则取消）
        self._pick_uid = None        # 延迟加点的 Clock id
        # 地图平移（长按空白处拖动）
        self._panning = False
        self._pan_touch_id = None
        self._pan_start_pos = None
        self._pan_start_center = None
        self._cells = []
        self._touches = {}             # touch.id -> touch（用于双指捏合）
        self._pinch_start_dist = None
        self._px_center = None
        self._zoom_dt_uid = None
        self._pan_dt_uid = None
        self.bind(size=self._on_resize)
        self._rebuild()
        # 瓦片自动恢复：重试已耗尽的格子每 3 秒重新请求（4G 抖动后自动补黑格）
        Clock.schedule_interval(self._tile_recover, 3.0)

    def _disp_or_gcj(self, lat, lon):
        """飞机坐标 -> 地图显示坐标(GCJ)；若 GPS 已是 GCJ 则原样。
        校准开启时，先经两定点相似变换再转 GCJ（标记与地图重叠）"""
        if self._calib:
            lat, lon = self._calib_fwd(lat, lon)
        if self.gps_is_gcj:
            return lat, lon
        return wgs84_to_gcj02(lat, lon)

    def _air_or_gcj(self, lat, lon):
        """地图(GCJ)点 -> 原坐标(WGS)；若 GPS 已是 GCJ 则原样。
        校准开启时，反向抵消相似变换（地图点 -> 应发 GPS）"""
        if self.gps_is_gcj:
            return lat, lon
        lat, lon = gcj02_to_wgs84(lat, lon)
        if self._calib:
            return self._calib_inv(lat, lon)
        return lat, lon

    # ---------------- 定位校准（领导法：两定点相似变换） ----------------
    def set_calib(self, pairs, note=''):
        """两定点定位校准：pairs=[(GPS纬, GPS经, 地图纬, 地图经), ...]（>=2）。
        不足2点或 None = 关闭。相似变换(平移+旋转+缩放)把「直角坐标换算出的经纬」
        与地图点重叠；飞机标记、取点、平移、定位全部套用。"""
        pairs = list(pairs or [])
        if len(pairs) >= 2:
            self._calib = pairs[:2]
            self._calib_from = note
        else:
            self._calib = None
            self._calib_from = ''

    def clear_calib(self):
        self._calib = None
        self._calib_from = ''

    @property
    def calib_on(self):
        return self._calib is not None

    def _calib_len_ok(self):
        return bool(self._calib) and len(self._calib) >= 2

    def _calib_fwd(self, lat, lon):
        """GPS经纬 -> 校准后地图显示经纬（局部米制相似变换）"""
        if not self._calib_len_ok():
            return lat, lon
        p1, p2 = self._calib[0], self._calib[1]
        lm = 111320.0
        c1 = lm * math.cos(math.radians(p1[1]))   # 第1点GPS 经度方向 米/度
        c2 = lm * math.cos(math.radians(p1[3]))   # 第1点地图 经度方向 米/度
        g2e = (p2[1] - p1[1]) * c1
        g2n = (p2[0] - p1[0]) * lm
        d2e = (p2[3] - p1[3]) * c2
        d2n = (p2[2] - p1[2]) * lm
        den = g2e * g2e + g2n * g2n
        if den < 1.0:
            return lat, lon          # 两点太近：校准不可用，原样返回
        ge = (lon - p1[1]) * c1
        gn = (lat - p1[0]) * lm
        k_re = (d2e * g2e + d2n * g2n) / den
        k_im = (d2n * g2e - d2e * g2n) / den
        de = k_re * ge - k_im * gn
        dn = k_im * ge + k_re * gn
        return p1[2] + dn / lm, p1[3] + de / c2

    def _calib_inv(self, lat, lon):
        """校准后地图显示经纬 -> GPS经纬（反向）"""
        if not self._calib_len_ok():
            return lat, lon
        p1, p2 = self._calib[0], self._calib[1]
        lm = 111320.0
        c1 = lm * math.cos(math.radians(p1[1]))
        c2 = lm * math.cos(math.radians(p1[3]))
        g2e = (p2[1] - p1[1]) * c1
        g2n = (p2[0] - p1[0]) * lm
        d2e = (p2[3] - p1[3]) * c2
        d2n = (p2[2] - p1[2]) * lm
        den = d2e * d2e + d2n * d2n
        if den < 1.0:
            return lat, lon
        de = (lon - p1[3]) * c2
        dn = (lat - p1[2]) * lm
        # z_g = z_d * z_g2 / z_d2  (除以 z_d2 = 乘共轭 / |z_d2|^2)
        p_r = de * g2e - dn * g2n   # Re(z_d * z_g2)
        p_i = de * g2n + dn * g2e   # Im(z_d * z_g2)
        zg_re = (p_r * d2e + p_i * d2n) / den
        zg_im = (p_i * d2e - p_r * d2n) / den
        return p1[0] + zg_im / lm, p1[1] + zg_re / c1

    def _on_resize(self, *a):
        # Popup 打开瞬间尺寸可能为 0——此时重建瓦片会算错/卡死，跳过等首次有效尺寸
        if self.width < 100 or self.height < 100:
            return
        try:
            self._rebuild()
        except Exception:
            pass

    def _tile_recover(self, *a):
        """自动补齐加载失败的瓦片：重试已耗尽(>=8)且未加载的格子每 3 秒重新请求"""
        try:
            for (cell, tx, ty) in list(self._cells):
                if not getattr(cell, '_loaded', False) and cell._retry >= 8:
                    cell._retry = -1
                    cell._fetching = False
                    cell._refresh_source()
        except Exception:
            pass

    def _zoom_rebuild(self):
        """缩放防抖：手势/连滚停止后只重建一次（不再每步重建 9 张瓦片）
        防抖 0.08s：比原 0.15s 快一倍，缩放响应更迅速，同时避免每步重建卡顿"""
        if self._zoom_dt_uid:
            Clock.unschedule(self._zoom_dt_uid)
        self._zoom_dt_uid = Clock.schedule_once(
            lambda dt: self._do_rebuild_safe(), 0.08)

    def _do_rebuild_safe(self):
        self._zoom_dt_uid = None
        try:
            self._rebuild()
        except Exception:
            pass

    def _do_close(self):
        if self._on_close:
            self._on_close()


    def _rebuild(self, *a):
        """按中心+缩放重建 3x3 瓦片网格"""
        if self.width < 100 or self.height < 100:
            return
        self._center = tuple(self._center)
        lat, lng = self._to_disp(self._center[0], self._center[1])
        z = self._zoom
        cx_px = _lng_to_px(lng, z)
        cy_px = _lat_to_px(lat, z)
        cx = int(cx_px // 256)
        cy = int(cy_px // 256)
        off_x = cx_px - cx * 256.0     # 中心在瓦片内的像素偏移
        off_y = cy_px - cy * 256.0
        self._px_center = (cx_px, cy_px)
        self._off = (off_x, off_y)
        self._left_tx = cx - 1          # 3x3 网格左下瓦片号（点击反算基准）
        self._bottom_ty = cy + 1
        # 世界px -> 屏幕px 显示系数：每瓦片 256 世界px 拉伸铺到 1/3 屏
        # (keep_ratio=False, allow_stretch=True)；任何缩放下同一地物应落在
        # 同一屏幕位置，标记绘制必须用这两系数 + 中心瓦片几何中心基准
        self._kx = self.width / 768.0
        self._ky = self.height / 768.0
        self._w0x = (cx + 0.5) * 256.0   # 中心瓦片几何中心（世界px）
        self._w0y = (cy + 0.5) * 256.0
        # 注意：grid 刚 add_widget 尚未布局，center 不可靠；标记/取点统一用
        # MapPage 自身中心 self.center（grid 铺满 MapPage，中心即屏中心）

        if self._grid is not None:
            self.remove_widget(self._grid)
        self._grid = GridLayout(cols=3, spacing=0)
        self._cells = []
        for dy in (1, 0, -1):
            for dx in (-1, 0, 1):
                tx = cx + dx
                ty = cy - dy          # 屏幕上 y 轴反向
                max_t = 2 ** z - 1
                # 越界瓦片由高德返回 404 空图，无需特判
                cell = TileCell(tx=tx, ty=ty, z=z,
                                on_tap=self._on_cell_tap)
                cell.size_hint = (1.0 / 3.0, 1.0 / 3.0)
                self._grid.add_widget(cell)
                self._cells.append((cell, tx, ty))
        self.add_widget(self._grid)

    def _on_cell_tap(self, cell, pos):
        """点击像素 -> 全球像素 -> GCJ02 -> WGS84 -> 回调"""
        # 双指手势过程中不触发取点
        if len(self._touches) >= 2:
            return
        lat, lng = self._tap_lat_lng(pos)
        self._pending_pick = (lat, lng)   # 存待定点，touch_up 延迟加点

    def _w2s(self, px_x, px_y):
        """世界px(同一缩放级) -> 屏幕坐标：以中心瓦片几何中心为基准 + 显示系数
        瓦片格拉伸铺到 1/3 屏(keep_ratio=False)，kx=屏宽/768、ky=屏高/768。
        旧式(px_x-cx_px)未乘系数/错基准 → 缩放时标记相对地物漂移。"""
        kx = getattr(self, '_kx', self.width / 768.0 if self.width else 1.0)
        ky = getattr(self, '_ky', self.height / 768.0 if self.height else 1.0)
        w0x = getattr(self, '_w0x', None)
        w0y = getattr(self, '_w0y', None)
        if w0x is None:
            w0x, w0y = self._w0x, self._w0y
        # grid 铺满 MapPage，用 MapPage 自身中心（布局稳定，缩放重建后不漂）
        gx = self.center_x
        gy = self.center_y
        return gx + (px_x - w0x) * kx, gy - (px_y - w0y) * ky

    def _s2w(self, sx, sy):
        """屏幕坐标 -> 世界px(当前缩放级)：_w2s 的逆"""
        kx = getattr(self, '_kx', self.width / 768.0 if self.width else 1.0)
        ky = getattr(self, '_ky', self.height / 768.0 if self.height else 1.0)
        w0x = getattr(self, '_w0x', None)
        w0y = getattr(self, '_w0y', None)
        if w0x is None:
            w0x, w0y = self._w0x, self._w0y
        gx = self.center_x
        gy = self.center_y
        return w0x + (sx - gx) / kx, w0y - (sy - gy) / ky

    def _tap_lat_lng(self, pos):
        """地图内任意屏幕坐标 → WGS84 经纬（双击任务菜单用）"""
        z = self._zoom
        # 用统一映射（显示系数+中心瓦片基准）反算，与标记绘制一致，取点不漂移
        px_x, px_y = self._s2w(pos[0], pos[1])
        return self._to_air(_px_to_lat(px_y, z), _px_to_lng(px_x, z))

    # ---------------- 双指捏合缩放 ----------------
    def on_touch_down(self, touch):
        # 鼠标滚轮（部分平台以 touch 形式派发，button 字段含方向）
        if getattr(touch, 'is_mouse_scrolling', False):
            self._wheel_dbg('wheel', 'btn=' + str(getattr(touch, 'button', '')))
            try:
                self._wheel_zoom(touch)
            except Exception:
                pass
            return True
        if not self.collide_point(*touch.pos):
            return super(MapPage, self).on_touch_down(touch)
        # 双击检测：0.35s 内再次点击 = 双击（弹任务菜单，类似电脑端右键）
        if self._last_tap_t and touch.time_start - self._last_tap_t < 0.45:
            self._last_tap_t = 0
            self._cancel_pick_add()   # 双击：取消单击加点（只开菜单不加点）
            self._pending_pick = None
            if len(self._touches) < 2 and self._on_double_tap:
                lat, lng = self._tap_lat_lng(touch.pos)
                self._on_double_tap(lat, lng)
            return True
        self._last_tap_t = touch.time_start
        # 先让子控件处理（TileCell 取点），同时自己 grab 以便跟踪手势
        handled = super(MapPage, self).on_touch_down(touch)
        touch.grab(self)
        self._touches[touch.id] = touch
        if len(self._touches) == 2:
            self._pinch_start_dist = self._pinch_dist()
            # 双指=捏合缩放：取消第一指的单击加点/长按/平移（防误触）
            self._pending_pick = None
            self._cancel_pick_add()
            self._cancel_long_press()
            self._panning = False
        # 长按检测：单指按住 0.5s 不动 -> 拖动航点
        self._down_pos = touch.pos
        if len(self._touches) == 1 and not self._drag_idx:
            self._cancel_long_press()
            self._long_press_uid = Clock.schedule_once(
                lambda dt: self._on_long_press(touch), 0.5)
        return handled or True

    def on_touch_move(self, touch):
        if touch.id in self._touches:
            self._touches[touch.id] = touch
        # 拖动航点
        if self._drag_idx is not None and self._drag_touch_id == touch.id:
            lat, lng = self._tap_lat_lng(touch.pos)
            self._fire_drag('move', self._drag_idx, lat, lng)
            return True
        # 平移地图（长按空白处后拖动）
        if self._panning and self._pan_touch_id == touch.id:
            dx = touch.pos[0] - self._pan_start_pos[0]
            dy = touch.pos[1] - self._pan_start_pos[1]
            self._pan_map(dx, dy)
            return True
        if len(self._touches) >= 2:
            d = self._pinch_dist()
            if self._pinch_start_dist and self._pinch_start_dist > 0:
                ratio = d / self._pinch_start_dist
                # 高灵敏捏合：超过阈值即响应，按捏合量连续跳级（平滑跟手）
                if ratio >= _PINCH_THRESHOLD:
                    steps = int((ratio - 1.0) / _PINCH_STEP_DIST) or 1
                    steps = min(steps, 2)  # 每次最多跳 2 级（防过猛）
                    self._zoom = min(_ZOOM_MAX, self._zoom + steps)
                    self._pinch_start_dist = d
                    self._zoom_rebuild()
                elif ratio <= 1.0 / _PINCH_THRESHOLD:
                    steps = int((1.0 - ratio) / _PINCH_STEP_DIST) or 1
                    steps = min(steps, 2)
                    self._zoom = max(_ZOOM_MIN, self._zoom - steps)
                    self._pinch_start_dist = d
                    self._zoom_rebuild()
        return super(MapPage, self).on_touch_move(touch)

    def _wheel_zoom(self, touch):
        """鼠标滚轮缩放：scrollup=放大 / scrolldown=缩小（兼容 scroll_y）"""
        try:
            if not self.collide_point(*touch.pos):
                return False
            btn = getattr(touch, 'button', '')
            if btn == 'scrollup':
                if self._zoom < _ZOOM_MAX:
                    self._zoom += 1
                    self._zoom_rebuild()
                    self._wheel_dbg('fwd', 'zoom ' + str(self._zoom))
                    return True
            elif btn == 'scrolldown':
                if self._zoom > _ZOOM_MIN:
                    self._zoom -= 1
                    self._zoom_rebuild()
                    self._wheel_dbg('back', 'zoom ' + str(self._zoom))
                    return True
            else:
                dy = getattr(touch, 'scroll_y', 0) or 0
                if dy > 0 and self._zoom < _ZOOM_MAX:
                    self._zoom += 1
                    self._zoom_rebuild()
                    return True
                elif dy < 0 and self._zoom > _ZOOM_MIN:
                    self._zoom -= 1
                    self._zoom_rebuild()
                    return True
        except Exception:
            pass
        return False

    def _wheel_dbg(self, ev, msg):
        # 调试已关闭（滚轮缩放已修复，方向读 touch.button）
        pass

    def on_scroll_start(self, touch, check=True):
        try:
            sy = getattr(touch, 'scroll_y', 0)
            sx = getattr(touch, 'scroll_x', 0)
            if self.collide_point(*touch.pos):
                self._wheel_dbg('sstart', 'sy=' + str(sy) + ' sx=' + str(sx))
            if self._wheel_zoom(touch):
                return True
        except Exception:
            pass
        return super(MapPage, self).on_scroll_start(touch, check=check)

    def on_scroll_move(self, touch, check=True):
        if self._wheel_zoom(touch):
            return True
        return super(MapPage, self).on_scroll_move(touch, check=check)

    def on_scroll_stop(self, touch, check=True):
        if self._wheel_zoom(touch):
            return True
        return super(MapPage, self).on_scroll_stop(touch, check=check)

    def on_touch_up(self, touch):
        # 结束拖动航点
        if self._drag_idx is not None and self._drag_touch_id == touch.id:
            lat, lng = self._tap_lat_lng(touch.pos)
            self._fire_drag('end', self._drag_idx, lat, lng)
            self._drag_idx = None
            self._drag_touch_id = None
            self._cancel_long_press()
            if touch.id in self._touches:
                del self._touches[touch.id]
            try:
                touch.ungrab(self)
            except Exception:
                pass
            if len(self._touches) < 2:
                self._pinch_start_dist = None
            return True
        self._cancel_long_press()
        if self._panning and self._pan_touch_id == touch.id:
            self._panning = False
            self._pan_touch_id = None
        if touch.id in self._touches:
            del self._touches[touch.id]
        try:
            touch.ungrab(self)
        except Exception:
            pass
        # 单点抬起：延迟 0.3s 加点（给双击留窗口）；双击会在 on_touch_down 取消
        if self._pending_pick and len(self._touches) == 0:
            lat, lng = self._pending_pick
            self._pending_pick = None
            self._schedule_pick_add(lat, lng)
        if len(self._touches) < 2:
            self._pinch_start_dist = None
        return super(MapPage, self).on_touch_up(touch)

    def _pinch_dist(self):
        pts = [(t.x, t.y) for t in self._touches.values()]
        if len(pts) < 2:
            return 0.0
        return hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1])

    def set_draggable_points(self, points):
        """可拖动航点：[(idx, lat, lon), ...]"""
        self._drag_points = list(points)

    def _cancel_long_press(self):
        if self._long_press_uid:
            try:
                Clock.unschedule(self._long_press_uid)
            except Exception:
                pass
        self._long_press_uid = None

    def _schedule_pick_add(self, lat, lng):
        self._cancel_pick_add()
        self._pick_uid = Clock.schedule_once(
            lambda dt: self._commit_pick(lat, lng), 0.45)

    def _cancel_pick_add(self):
        if self._pick_uid:
            try:
                Clock.unschedule(self._pick_uid)
            except Exception:
                pass
        self._pick_uid = None

    def _commit_pick(self, lat, lng):
        self._pick_uid = None
        if self._on_pick:
            self._on_pick(lat, lng)

    def _on_long_press(self, touch):
        self._long_press_uid = None
        self._pending_pick = None   # 长按不添加点
        pos = self._down_pos or touch.pos
        if len(self._touches) != 1:
            return
        idx, lat, lon = self._nearest_drag_point(pos)
        if idx is not None:
            # 长按航点 -> 拖航点
            self._drag_idx = idx
            self._drag_touch_id = touch.id
            self._fire_drag('start', idx, lat, lon)
        else:
            # 长按空白 -> 平移地图
            self._panning = True
            self._pan_touch_id = touch.id
            self._pan_start_pos = tuple(pos)
            self._pan_start_center = tuple(self._center)

    def _nearest_drag_point(self, pos):
        z = self._zoom
        pc = getattr(self, '_px_center', None)
        g = self._grid
        if g is None or not pc or not self._drag_points:
            return None, None, None
        cx_px, cy_px = pc
        gx, gy = g.center_x, g.center_y
        best_d = 1e9
        best = None
        for (idx, lat, lon) in self._drag_points:
            try:
                lat_gcj, lng_gcj = self._to_disp(lat, lon)
                px_x = _lng_to_px(lng_gcj, z)
                px_y = _lat_to_px(lat_gcj, z)
                sx, sy = self._w2s(px_x, px_y)
                d = hypot(sx - pos[0], sy - pos[1])
                if d < best_d:
                    best_d = d
                    best = (idx, lat, lon)
            except Exception:
                pass
        if best and best_d <= 52:
            return best
        return None, None, None

    def _fire_drag(self, ev, idx, lat, lon):
        if self._drag_cb:
            try:
                self._drag_cb(ev, idx, lat, lon)
            except Exception:
                pass

    def _pan_map(self, dx, dy):
        """按屏幕位移平移地图中心（跟手：0.05s 防抖，拖动感觉即时）"""
        try:
            z = self._zoom
            cx_px, cy_px = self._px_center
            new_cx = cx_px - dx
            new_cy = cy_px + dy
            lat_gcj = _px_to_lat(new_cy, z)
            lng_gcj = _px_to_lng(new_cx, z)
            lat, lng = self._to_air(lat_gcj, lng_gcj)
            self._center = (lat, lng)
            # 平移独立 0.05s 防抖重建（PAN_DEBOUNCE）：拖动中只更新中心，
            # 停手后重建一次；比缩放(0.08s)更跟手，又不每帧重建 9 格瓦片
            self._pan_debounce_rebuild()
        except Exception:
            pass

    def _pan_debounce_rebuild(self):
        """平移防抖：0.05s 内连续拖动只重建一次（跟手且不卡）"""
        if self._pan_dt_uid:
            Clock.unschedule(self._pan_dt_uid)
        self._pan_dt_uid = Clock.schedule_once(
            lambda dt: self._pan_rebuild_now(), _PAN_DEBOUNCE)

    def _pan_rebuild_now(self):
        self._pan_dt_uid = None
        try:
            self._rebuild()
        except Exception:
            pass