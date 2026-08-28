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
        # 加载失败重试几次（ESRI 无子域，重试同一地址）
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
                lat_gcj, lng_gcj = wgs84_to_gcj02(lat, lon)
                px_x = _lng_to_px(lng_gcj, z)
                px_y = _lat_to_px(lat_gcj, z)
                sx = gx + (px_x - cx_px)
                sy = gy - (px_y - cy_px)
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
                    lat_gcj, lng_gcj = wgs84_to_gcj02(lat, lon)
                    px_x = _lng_to_px(lng_gcj, z)
                    px_y = _lat_to_px(lat_gcj, z)
                    sx = gx + (px_x - cx_px)
                    sy = gy - (px_y - cy_px)
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
                lat_gcj, lng_gcj = wgs84_to_gcj02(lat, lon)
                px_x = _lng_to_px(lng_gcj, z)
                px_y = _lat_to_px(lat_gcj, z)
                sx = gx + (px_x - cx_px)
                sy = gy - (px_y - cy_px)
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
                 on_close=None, embedded=False, on_double_tap=None, **kw):
        kw.setdefault('orientation', 'vertical')
        kw.setdefault('spacing', 4)
        kw.setdefault('padding', 4)
        super(MapPage, self).__init__(**kw)
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
        self._cells = []
        self._touches = {}             # touch.id -> touch（用于双指捏合）
        self._pinch_start_dist = None
        self._px_center = None
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
        lat, lng = self._tap_lat_lng(pos)
        self._pending_pick = (lat, lng)   # 存待定点，touch_up 延迟加点

    def _tap_lat_lng(self, pos):
        """地图内任意屏幕坐标 → WGS84 经纬（双击任务菜单用）"""
        z = self._zoom
        cx_px, cy_px = self._px_center
        g = self._grid
        gx = g.center_x if g else self.center_x
        gy = g.center_y if g else self.center_y
        px_x = cx_px + (pos[0] - gx)
        px_y = cy_px - (pos[1] - gy)
        return gcj02_to_wgs84(_px_to_lat(px_y, z), _px_to_lng(px_x, z))

    # ---------------- 双指捏合缩放 ----------------
    def on_touch_down(self, touch):
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
            # 双指=捏合缩放：取消第一指的单击加点/长按（防误触）
            self._pending_pick = None
            self._cancel_pick_add()
            self._cancel_long_press()
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
        if len(self._touches) >= 2:
            d = self._pinch_dist()
            if self._pinch_start_dist and self._pinch_start_dist > 0:
                ratio = d / self._pinch_start_dist
                if ratio > 1.05 and self._zoom < 18:
                    self._zoom += 1
                    self._pinch_start_dist = d
                    self._rebuild()
                elif ratio < 0.95 and self._zoom > 3:
                    self._zoom -= 1
                    self._pinch_start_dist = d
                    self._rebuild()
        return super(MapPage, self).on_touch_move(touch)

    def on_scroll_start(self, touch, check=True):
        """鼠标滚轮缩放（电脑/桌面可用）"""
        try:
            if getattr(touch, 'is_mouse_scrolling', False):
                dy = getattr(touch, 'scroll_y', 0)
                if dy and self.collide_point(*touch.pos):
                    if dy > 0 and self._zoom < 18:
                        self._zoom += 1
                        self._rebuild()
                    elif dy < 0 and self._zoom > 3:
                        self._zoom -= 1
                        self._rebuild()
                    return True
        except Exception:
            pass
        return super(MapPage, self).on_scroll_start(touch, check=check)

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
        self._pending_pick = None   # 长按不添加点（拖动）
        # 用按下位置找最近航点（按住移动也锁定按下时那个点）
        pos = self._down_pos or touch.pos
        if len(self._touches) != 1 or not self._drag_points:
            return
        idx, lat, lon = self._nearest_drag_point(pos)
        if idx is not None:
            self._drag_idx = idx
            self._drag_touch_id = touch.id
            self._fire_drag('start', idx, lat, lon)

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
                lat_gcj, lng_gcj = wgs84_to_gcj02(lat, lon)
                px_x = _lng_to_px(lng_gcj, z)
                px_y = _lat_to_px(lat_gcj, z)
                sx = gx + (px_x - cx_px)
                sy = gy - (px_y - cy_px)
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