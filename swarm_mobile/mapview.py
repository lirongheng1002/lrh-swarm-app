"""高德卫星地图（Kivy 纯控件，无额外依赖）

- 瓦片源：webst 高德瓦片（卫星图专用域名！），style=6 = 卫星图（瓦片为 GCJ-02 切片）
- 点击瓦片 → 反算经纬（GCJ -> WGS84）→ 回调 on_pick(lat, lng)
- 3x3 网格，每瓦 size_hint=(1/3,1/3) 自动拉伸满屏——竖屏/横屏都铺满
- 缩放 Slider（3~18）；中心默认=首在线机坐标，否则 config map 中心或默认
"""
import math

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.graphics import Color, Rectangle
from kivy.core.text import LabelBase
from math import hypot

from .widgets import RoundedButton

# ---------------- 高德瓦片 ----------------
_TILE_URL = 'https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}'
_SUB = ['1', '2', '3', '4']

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
    """一格瓦片：记录自身瓦片号，点击时回调外部；加载失败换子域自动重试"""
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
        self._refresh_source()
        self.bind(on_error=self._on_tile_error)

    def _tile_url(self, s):
        return _TILE_URL.format(s=s, x=self._tx, y=self._ty, z=self._z)

    def _refresh_source(self):
        s = _SUB[(self._tx * 7 + self._ty) % 4]
        self.source = self._tile_url(s)

    def _on_tile_error(self, *a):
        # 换下一个子域重试（4 子域循环最多 8 次），避免单子域故障整图空白
        self._retry += 1
        if self._retry < 8:
            s = _SUB[(self._tx * 7 + self._ty + self._retry) % 4]
            self.source = self._tile_url(s)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if self._on_tap:
                self._on_tap(self, touch.pos)
            return True
        return super(TileCell, self).on_touch_down(touch)


# ---------------- 卫星地图页 ----------------
class MapPage(BoxLayout):
    """卫星地图：3x3 瓦片铺满（横竖屏自适应）+ 双指捏合缩放 + 关闭按钮。

    手势：
    - 单指点击/抬起：取点回调 on_pick(lat, lng)
    - 双指捏合/张开：缩放地图（zoom 3~18）
    """
    def __init__(self, center=(31.2304, 121.4737), zoom=15, on_pick=None,
                 on_close=None, embedded=False, **kw):
        kw.setdefault('orientation', 'vertical')
        kw.setdefault('spacing', 4)
        kw.setdefault('padding', 4)
        super(MapPage, self).__init__(**kw)
        self._center = center          # (lat, lng) WGS84
        self._zoom = max(3, min(18, int(zoom)))
        self._on_pick = on_pick
        self._on_close = on_close
        self._embedded = embedded
        self._grid = None
        self._cells = []
        self._touches = {}             # touch.id -> touch（用于双指捏合）
        self._pinch_start_dist = None

        # 顶栏：坐标显示 + 缩放提示 + 关闭按钮（embedded 内嵌版无关闭）
        top = BoxLayout(orientation='horizontal', size_hint_y=None, height='42dp',
                        spacing=8, padding=(8, 4))
        self._lbl_coord = Label(text='%.5f, %.5f' % center, size_hint_x=0.55,
                                font_size='15sp', halign='left')
        self._lbl_zoom = Label(text='zoom %d' % self._zoom, size_hint_x=0.2,
                               font_size='14sp', halign='center',
                               color=(0.7, 0.85, 1, 1))
        top.add_widget(self._lbl_coord)
        top.add_widget(self._lbl_zoom)
        if not embedded:
            top.add_widget(_mk_button('关闭', (0.75, 0.28, 0.22, 1),
                                      self._do_close, size_hint_x=0.25))
        else:
            top.add_widget(Label(text='', size_hint_x=0.25))
        self.add_widget(top)

        self._hint = Label(text='双指捏合缩放，点击地图设为航点',
                           size_hint_y=None, height='26dp', font_size='12sp',
                           color=(0.9, 0.85, 0.6, 1))
        self.add_widget(self._hint)

        self.bind(size=self._on_resize)
        self._rebuild()

    def _on_resize(self, *a):
        # Popup 打开瞬间尺寸可能为 0——此时重建瓦片会算错/卡死，跳过等首次有效尺寸
        if self.width < 100 or self.height < 100:
            return
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
        if hasattr(self, '_lbl_zoom'):
            self._lbl_zoom.text = 'zoom %d' % self._zoom
        self._center = tuple(self._center)
        lat, lng = wgs84_to_gcj02(self._center[0], self._center[1])
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
        z = self._zoom
        cx_px, cy_px = self._px_center
        w = cell.width
        idx = self._grid.children.index(cell)
        row = idx // 3
        col_i = idx % 3
        px_x = cx_px - (1 - col_i) * w + (pos[0] - cell.x)
        px_y = cy_px + (1 - row) * w - (pos[1] - cell.y)
        lng_gcj = _px_to_lng(px_x, z)
        lat_gcj = _px_to_lat(px_y, z)
        lat, lng = gcj02_to_wgs84(lat_gcj, lng_gcj)
        self._lbl_coord.text = '%.5f, %.5f' % (lat, lng)
        if self._on_pick:
            self._on_pick(lat, lng)

    # ---------------- 双指捏合缩放 ----------------
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super(MapPage, self).on_touch_down(touch)
        # 先让子控件处理（TileCell 取点），同时自己 grab 以便跟踪手势
        handled = super(MapPage, self).on_touch_down(touch)
        touch.grab(self)
        self._touches[touch.id] = touch
        if len(self._touches) == 2:
            self._pinch_start_dist = self._pinch_dist()
        return handled or True

    def on_touch_move(self, touch):
        if touch.id in self._touches:
            self._touches[touch.id] = touch
        if len(self._touches) >= 2:
            d = self._pinch_dist()
            if self._pinch_start_dist and self._pinch_start_dist > 0:
                ratio = d / self._pinch_start_dist
                if ratio > 1.15 and self._zoom < 18:
                    self._zoom += 1
                    self._pinch_start_dist = d
                    self._rebuild()
                elif ratio < 0.85 and self._zoom > 3:
                    self._zoom -= 1
                    self._pinch_start_dist = d
                    self._rebuild()
        return super(MapPage, self).on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.id in self._touches:
            del self._touches[touch.id]
        try:
            touch.ungrab(self)
        except Exception:
            pass
        if len(self._touches) < 2:
            self._pinch_start_dist = None
        return super(MapPage, self).on_touch_up(touch)

    def _pinch_dist(self):
        pts = [(t.x, t.y) for t in self._touches.values()]
        if len(pts) < 2:
            return 0.0
        return hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1])