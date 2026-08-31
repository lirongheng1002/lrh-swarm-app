"""手机集群控制 APP —— Kivy 全中文纵向界面（Android 优先）

布局（手机竖屏，ScrollView 纵向滚动）：
  顶部固定：连接行（服务器IP/基础端口/连接·断开）+ 状态行（在线 X/10 · 编队开关）+ 卫星行（每机颗数，横向滚动）
  滚动区：
    一、全队操作  全部解锁/上锁/起飞[高度]/降落/返航/投弹/切自动(各自任务)/全部切模式
    二、队形编队  全队高度/三段间距/6 预设/开始编队/暂停编队
    三、单机操作  选机(Spinner)+该机状态/单机起飞/降落/解锁/上锁/返航/投弹/切模式
    四、任务航点  下载任务/上传任务/清除/经纬高输入 加航点/插入投弹点/任务表(点选行)
    五、运行日志  多行滚动文本

危险操作（全部解锁/起飞/降落/返航/投弹/强制动作/上传任务）先弹 Popup 二次确认。
"""
import os

from kivy.app import App
from kivy.clock import Clock
from kivy.config import Config
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from . import fleet as fleetmod
from . import mapview
from .core import vehicles, commands, missions, formation, gauss, config as cfgmod
from .widgets import RoundedButton, CompactTextInput, GlassPanel

# ---------- 中文字体注册（Android 上 Kivy 默认无 CJK 字体，必须内置） ----------
_FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fonts')
_ZH_FONT = None
if os.path.isdir(_FONTS_DIR):
    for _n in sorted(os.listdir(_FONTS_DIR)):
        if _n.lower().endswith(('.ttf', '.otf', '.ttc')):
            _ZH_FONT = os.path.join(_FONTS_DIR, _n)
            break
if _ZH_FONT:
    try:
        from kivy.core.text import LabelBase
        # 中文全局必杀注册：同时覆盖默认字体名 Roboto（Kivy 所有控件默认引用它，
        # 不依赖 default_font 配置的解析，直接让中文字体成为唯一渲染字体）
        LabelBase.register('ZHFont', fn_regular=_ZH_FONT, fn_bold=_ZH_FONT,
                           fn_italic=_ZH_FONT, fn_bolditalic=_ZH_FONT)
        LabelBase.register('Roboto', fn_regular=_ZH_FONT, fn_bold=_ZH_FONT,
                           fn_italic=_ZH_FONT, fn_bolditalic=_ZH_FONT)
        from kivy.config import Config
        Config.set('kivy', 'default_font', ['ZHFont', 'Roboto'])
    except Exception:
        pass

BTN_H = '52dp'
INPUT_H = '44dp'
ACCENT = (0.22, 0.55, 0.95, 1)
DANGER = (0.85, 0.28, 0.22, 1)
OK = (0.16, 0.62, 0.32, 1)
GRAY = (0.45, 0.45, 0.45, 1)

MODE_NAMES = [(zh, num) for num, zh in sorted(vehicles.MODE_ZH.items())]
MODE_SPINNER_VALUES = ['%s(%d)' % (zh, num) for zh, num in MODE_NAMES]


def _dft():
    return {
        'server': {'host': '112.124.6.186', 'mode': 'per_port', 'per_port_base': 15551},
        'link': {'heartbeat_timeout_s': 18, 'throttle': False, 'reconnect_s': 2,
                 'idle_timeout_s': 20},
        'vehicles': [{'sysid': i, 'name': '%d号机' % i,
                      'role': 'leader' if i == 1 else 'follower', 'offset': [0, 0, 0]}
                     for i in range(1, 11)],
        'formation': {'spacing_f': 5, 'spacing_l': 5, 'spacing_g': 10},
        'takeoff': {'alt_m': 20},
        'bomb': {'servo': 6, 'pwm': 2000, 'count': 1, 'time': 1},
        'map': {'gps_is_gcj': False},
    }


def _user_config_path():
    """优先用 App 用户数据目录里的 config.yaml（可改 IP 不用重装），
    首次启动时把随包默认 config.yaml 拷贝过去。桌面调试时也可直接用项目内 config.yaml。"""
    appdir = App.get_running_app().user_data_dir if App.get_running_app() else None
    user = os.path.join(appdir, 'config.yaml') if appdir else None
    bundled = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')
    if user and os.path.exists(user):
        return user
    if os.path.exists(bundled):
        if user:
            try:
                import shutil
                shutil.copy(bundled, user)
                return user
            except Exception:
                pass
        return bundled
    return None


class ConfirmPopup(Popup):
    """通用二次确认弹窗"""

    def __init__(self, title, text, on_ok, **kw):
        super().__init__(title=title, size_hint=(0.9, 0.42), auto_dismiss=False, **kw)
        body = BoxLayout(orientation='vertical', padding=14, spacing=12)
        lbl = Label(text=text, halign='left', valign='middle',
                    text_size=(450, None), font_size='17sp')
        btns = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=BTN_H)
        b_cancel = RoundedButton(text='取消', font_size='17sp',
                                 background_color=(0.5, 0.5, 0.5, 1), radius='10dp')
        b_ok = RoundedButton(text='确定执行', font_size='17sp',
                             background_color=DANGER, radius='10dp')
        b_cancel.bind(on_release=lambda _x: self.dismiss())
        b_ok.bind(on_release=lambda _x: (self.dismiss(), on_ok()))
        btns.add_widget(b_cancel)
        btns.add_widget(b_ok)
        body.add_widget(lbl)
        body.add_widget(btns)
        self.content = body


class CoordPopup(Popup):
    """坐标换算：CGCS2000 高斯平面 X/Y → 北纬/东经（回填航点经纬）"""

    def __init__(self, on_result, **kw):
        super().__init__(title='坐标换算（CGCS2000 高斯六度带）',
                         size_hint=(0.94, 0.7), auto_dismiss=False, **kw)
        self._on_result = on_result
        self._lat = self._lon = None
        body = BoxLayout(orientation='vertical', padding=14, spacing=12)
        self._in_x = CompactTextInput(hint_text='X（北向坐标，米）',
                                      input_filter='float')
        self._in_y = CompactTextInput(hint_text='Y（横坐标：(19)406840 / 19406840 / 406840）')
        self._in_z = CompactTextInput(hint_text='带号（可选，缺省自动判）',
                                      input_filter='int')
        self._lbl_res = Label(text='等待输入坐标…', font_size='16sp', halign='left',
                              valign='middle', color=(0.4, 0.85, 0.6, 1))
        rowb = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=BTN_H)
        b_calc = RoundedButton(text='换算', font_size='17sp',
                               background_color=ACCENT, radius='10dp')
        b_apply = RoundedButton(text='设为航点', font_size='17sp',
                                background_color=OK, radius='10dp')
        b_close = RoundedButton(text='关闭', font_size='17sp',
                                background_color=(0.5, 0.5, 0.5, 1), radius='10dp')
        b_calc.bind(on_release=lambda _x: self._calc())
        b_apply.bind(on_release=lambda _x: self._apply())
        b_close.bind(on_release=lambda _x: self.dismiss())
        rowb.add_widget(b_calc)
        rowb.add_widget(b_apply)
        rowb.add_widget(b_close)
        body.add_widget(self._in_x)
        body.add_widget(self._in_y)
        body.add_widget(self._in_z)
        body.add_widget(self._lbl_res)
        body.add_widget(rowb)
        self.content = body

    def _calc(self):
        try:
            x = float(self._in_x.text)
        except Exception:
            self._lbl_res.text = 'X 请输入数字'
            return
        yraw = self._in_y.text.strip()
        zstr = self._in_z.text.strip()
        try:
            zone = int(zstr) if zstr else None
        except Exception:
            zone = None
        try:
            lat, lon = gauss.zone_to_latlon(x, yraw, zone)
        except Exception as e:
            self._lbl_res.text = '换算失败：%s' % e
            return
        self._lat, self._lon = lat, lon
        self._lbl_res.text = '换算结果：北纬 %.6f°  东经 %.6f°' % (lat, lon)

    def _apply(self):
        if self._lat is None:
            self._lbl_res.text = '请先点「换算」'
            return
        self._on_result(self._lat, self._lon)
        self.dismiss()


class SwarmMobileApp(App):
    title = 'LRH 手机集群控制 v1.0 —— ArduPilot · 4G 云中继'

    def build(self):
        # 电脑调试按 16:9 打开（手机真机不受影响）
        try:
            from kivy.utils import platform
            if platform != 'android':
                Window.size = (1280, 720)
        except Exception:
            pass
        Window.softinput_mode = 'below_target'
        # 统一深色底：按钮圆角外/输入框周边不再是透明区外露（领导：消除透明框）
        Window.clearcolor = (0.08, 0.1, 0.12, 1)
        self._sel_seq = None          # 任务表选中 seq
        self._row_last_tap_t = 0        # 任务表行双击检测
        self._row_last_seq = None
        self._sel_sys = 1             # 单机区选中机
        self._fm_st = '编队:关'

        # 配置：优先用户可写副本，否则项目内默认
        self._config_path = _user_config_path()
        path = self._config_path
        cfg = {}
        if path and os.path.exists(path):
            try:
                cfg = cfgmod.load_config(path)
            except Exception as e:
                self._append_log('配置加载失败(%s)，用内置默认' % e)
        if not cfg or not cfg.get('vehicles'):
            cfg = _dft()
        self.cfg = cfg

        self.fleet = fleetmod.FleetApp(cfg)
        self.fleet.on_log = self._append_log
        self.fleet.on_mission_downloaded = self._on_mission_downloaded
        self.fleet.on_mission_uploaded = self._on_mission_uploaded

        root = self._build_ui()
        Clock.schedule_interval(self._tick, 0.5)
        self._append_log('LRH 手机集群控制 v1.0 就绪 —— 填好服务器地址后点「连接」')
        return root

    # ================= UI 构建 =================
    def _build_ui(self):
        self._log_text = ''
        root = BoxLayout(orientation='vertical', spacing=4, padding=(6, 6))

        # ---- 顶部固定区 ----
        # 顶部：连接行（IP+端口+连接+断开 一行）+ 状态行 + 卫星行（两行 5+5，间隔小、机号红/颗数绿）
        top = BoxLayout(orientation='vertical', size_hint_y=None, height='147dp', spacing=3)
        row1 = BoxLayout(orientation='horizontal', spacing=4, size_hint_y=None, height='32dp')
        self._host_in = CompactTextInput(text=str(self.cfg.get('server', {}).get('host', '')),
                                         hint_text='服务器IP', size_hint_x=0.48,
                                         font_size='13sp', halign='center')
        self._port_in = CompactTextInput(text=str(self.cfg.get('server', {}).get('per_port_base', 15551)),
                                         hint_text='端口', input_filter='int',
                                         size_hint_x=0.16, font_size='13sp', halign='center')
        self._autocenter(self._host_in)
        self._autocenter(self._port_in)
        self._btn_conn = RoundedButton(text='连接', font_size='13sp',
                                       background_color=ACCENT,
                                       size_hint_x=0.18, radius='8dp')
        self._btn_conn.bind(on_release=self._on_connect)
        self._btn_disc = RoundedButton(text='断开', font_size='13sp',
                                       background_color=(0.55, 0.55, 0.55, 1),
                                       size_hint_x=0.18, radius='8dp')
        self._btn_disc.bind(on_release=self._on_disconnect)
        row1.add_widget(self._host_in)
        row1.add_widget(self._port_in)
        row1.add_widget(self._btn_conn)
        row1.add_widget(self._btn_disc)
        top.add_widget(row1)

        row2 = BoxLayout(orientation='horizontal', spacing=4, size_hint_y=None, height='26dp')
        self._lbl_lock = Label(text='上锁', font_size='13sp', halign='center',
                               valign='middle', size_hint_x=0.2, color=GRAY)
        self._lbl_status = Label(text='状态：未连接', font_size='13sp', halign='left',
                                 valign='middle', size_hint_x=0.44)
        self._lbl_fm = Label(text='编队:关', font_size='13sp', halign='center', valign='middle',
                             color=GRAY, size_hint_x=0.36)
        row2.add_widget(self._lbl_lock)
        row2.add_widget(self._lbl_status)
        row2.add_widget(self._lbl_fm)
        top.add_widget(row2)

        # 卫星行：10 机两行（5+5），每格 = 机号+颗数（上）+ 该机飞行模式（下）
        self._sat_box = GridLayout(cols=5, spacing=3, size_hint_y=None,
                                   height='80dp', padding=(4, 2))
        top.add_widget(self._sat_box)
        root.add_widget(top)

        # ---- 四栏导航（顶部按钮切页；不用 TabbedPanel——安卓上其 content 尺寸 bug
        #      导致切到第2栏后切不回/整页点不动，地图与航线窗口全无响应）----
        # ---- 四栏导航（顶部按钮切页；不用 TabbedPanel——安卓上其 content 尺寸 bug
        #      导致切到第2栏后切不回/整页点不动，地图与航线窗口全无响应）----
        # 导航栏固定在 root，不参与页面滚动；始终可点击。
        nav = BoxLayout(orientation='horizontal', spacing=6, size_hint_y=None,
                        height='32dp', padding=(2, 2))
        self._btn_p1 = RoundedButton(text='全部飞机', font_size='13sp',
                                     background_color=ACCENT, radius='8dp')
        self._btn_p2 = RoundedButton(text='单架飞机', font_size='13sp',
                                     background_color=(0.35, 0.35, 0.35, 1),
                                     radius='8dp')
        self._btn_p3 = RoundedButton(text='任务航线', font_size='13sp',
                                     background_color=(0.35, 0.35, 0.35, 1),
                                     radius='8dp')
        self._btn_p4 = RoundedButton(text='运行日志', font_size='13sp',
                                     background_color=(0.35, 0.35, 0.35, 1),
                                     radius='8dp')
        self._btn_p1.bind(on_release=lambda _x: self._switch_page(0))
        self._btn_p2.bind(on_release=lambda _x: self._switch_page(1))
        self._btn_p3.bind(on_release=lambda _x: self._switch_page(2))
        self._btn_p4.bind(on_release=lambda _x: self._switch_page(3))
        nav.add_widget(self._btn_p1)
        nav.add_widget(self._btn_p2)
        nav.add_widget(self._btn_p3)
        nav.add_widget(self._btn_p4)
        root.add_widget(nav)

        # ---- 页① 全部飞机：全队操作 + 队形编队（领导要求飞行拆分：全部/单架）----
        sv0 = ScrollView()
        body0 = BoxLayout(orientation='vertical', spacing=0, padding=(4, 0),
                          size_hint_y=None)
        body0.bind(minimum_height=body0.setter('height'))
        body0.add_widget(self._section_title('一、全队操作', (0.18, 0.4, 0.72, 1)))
        body0.add_widget(self._build_fleet_ops())
        body0.add_widget(BoxLayout(size_hint_y=None, height='8dp'))
        body0.add_widget(self._section_title('二、队形编队', (0.18, 0.4, 0.72, 1)))
        body0.add_widget(self._build_formation())
        sv0.add_widget(body0)

        # ---- 页② 单架飞机：内容量小，直接 BoxLayout 铺满（不套外层 ScrollView，
        #      彻底避开安卓页面级滚动布局黑屏/空白）----
        body1 = BoxLayout(orientation='vertical', spacing=0, padding=(6, 0))
        body1.add_widget(self._build_single())
        body1.add_widget(BoxLayout(size_hint_y=1))

        # ---- 页③ 任务航线：上面=高德卫星地图（占 65%，重点！地图一定要大），下面=全部功能区贴底（占 35%）----
        body2 = BoxLayout(orientation='vertical', spacing=0, padding=(2, 2))
        # 地图 + 航线覆盖层（RelativeLayout 相对叠加：地图在下、航线在上）
        map_holder = RelativeLayout(size_hint_y=1)
        self._map_page = mapview.MapPage(center=self._map_default_center(),
                                         zoom=14, embedded=True,
                                         on_pick=self._on_map_pick_embed,
                                         on_double_tap=self._on_map_double_tap,
                                         gps_is_gcj=bool(self.cfg.get('map', {}).get('gps_is_gcj', False)))
        _cal = (self.cfg.get('map', {}) or {}).get('calib') or {}
        if _cal.get('on') and len(_cal.get('pts', [])) >= 2:
            self._map_page.set_calib(_cal['pts'], note='开机自动应用')
        self._map_page.size_hint = (1, 1)
        map_holder.add_widget(self._map_page)
        self._map_route_layer = mapview._RouteLayer(self._map_page)
        self._map_route_layer.size_hint = (1, 1)
        map_holder.add_widget(self._map_route_layer)
        body2.add_widget(map_holder)
        self._map_page._drag_cb = self._on_point_drag
        # 任务表显示在地图下方（读取航线信息：序号/指令/位置/高度m/悬停s）
        self._mission_scroll = ScrollView(size_hint_y=None, height='98dp')
        self._mission_box = BoxLayout(orientation='vertical', spacing=0, size_hint_y=None)
        self._mission_box.bind(minimum_height=self._mission_box.setter('height'))
        self._mission_scroll.add_widget(self._mission_box)
        body2.add_widget(self._mission_scroll)
        bottom = BoxLayout(orientation='vertical', spacing=1, size_hint_y=None, height='132dp')
        bottom.add_widget(self._build_mission())
        body2.add_widget(bottom)

        # ---- 页③ 运行日志（单独一栏，长按可选中复制 + 清空）----
        logbox3 = BoxLayout(orientation='vertical', spacing=6, padding=(4, 4))
        self._lbl_log = TextInput(text='', readonly=True, font_size='15sp',
                                  background_color=(0.12, 0.14, 0.12, 1),
                                  foreground_color=(0.75, 0.85, 0.75, 1),
                                  cursor_color=(0.9, 0.95, 0.9, 1), multiline=True)
        b_clear = RoundedButton(text='清空日志', font_size='16sp',
                                background_color=(0.35, 0.35, 0.45, 1),
                                size_hint_y=None, height=INPUT_H, radius='8dp')
        b_clear.bind(on_release=lambda _x: self._clear_log())
        logbox3.add_widget(self._lbl_log)
        logbox3.add_widget(b_clear)

        # ---- 页面槽：固定区域，切页 = clear + add（安卓最稳，不重叠）----
        self._pages = [sv0, body1, body2, logbox3]
        self._page_slot = BoxLayout(orientation='vertical')
        root.add_widget(self._page_slot)
        self._switch_page(0)
        return root

    def _switch_page(self, idx):
        """切页：清空页面槽再挂目标页；同时高亮导航按钮"""
        self._page_slot.clear_widgets()
        self._page_slot.add_widget(self._pages[idx])
        for i, b in enumerate((self._btn_p1, self._btn_p2, self._btn_p3, self._btn_p4)):
            b.background_color = ACCENT if i == idx else (0.35, 0.35, 0.35, 1)
            b._draw()

    def _autocenter(self, ti):
        """IP/端口数字自动居中：字多宽框多宽，数字在框中间"""
        def _upd(*_a):
            try:
                pad = max(0.0, (ti.width - len(ti.text) * ti.font_size * 0.55) / 2)
                ti.padding = (pad, int(ti.height * 0.3), pad, 0)
            except Exception:
                pass
        ti.bind(text=_upd)
        ti.bind(width=_upd)
        Clock.schedule_once(_upd, 0)

    def _clear_log(self):
        self._log_text = ''
        self._lbl_log.text = ''

    def _section_title(self, text, color):
        lbl = Label(text=text, font_size='18sp', bold=True, color=color,
                    size_hint_y=None, height='32dp', halign='center', valign='middle')
        lbl.bind(width=lambda w, v: setattr(w, 'text_size', (v, None)))
        return lbl

    def _h_cell(self, btn):
        return btn

    # ---------------- 一、全队操作 ----------------
    def _build_fleet_ops(self):
        """全队操作区：4 行 × 4 列网格，功能分区，避免重叠。

        行1（安全/起降）：全部解锁 | 全部上锁 | 全部起飞 | 全部降落
        行2（任务/模式）：全部返航 | 全部投弹 | 切自动任务 | 全部切模式
        行3（起飞参数）：起飞高度 | 输入框 | 确定 | m
        行4（全队参数）：全队高度 | 输入框 | 确定 | m
        """
        g = GridLayout(cols=4, spacing=6, size_hint_y=None, height='86dp',
                       padding=(2, 2))

        # 行1：安全与起降
        g.add_widget(self._mk_btn('全部解锁', DANGER, lambda: self._confirm(
            '全部解锁', '对全部 N 架机执行解锁（ARM）？\n确认飞机已就位、无人在桨区内。',
            lambda: self._swarm_act('解锁', self.fleet.arm_all, True)),
            font_size='15sp'))
        g.add_widget(self._mk_btn('全部上锁', DANGER, lambda: self._confirm(
            '全部上锁', '对全部在线机执行上锁（DISARM）？\n仅应在地面执行。',
            lambda: self._swarm_act('上锁', self.fleet.arm_all, False)),
            font_size='15sp'))
        g.add_widget(self._mk_btn('全部起飞', OK, lambda: self._confirm(
            '全部起飞', '全部 N 架按高度 %s m 同时起飞？' % self._tof_alt(),
            lambda: self._swarm_act('起飞', self.fleet.takeoff_all, self._tof_alt())),
            font_size='15sp'))
        g.add_widget(self._mk_btn('全部降落', DANGER, lambda: self._confirm(
            '全部降落', '全部 N 架立即降落（LAND）？',
            lambda: self._swarm_act('降落', self.fleet.land_all)),
            font_size='15sp'))

        # 行2：任务与模式
        g.add_widget(self._mk_btn('全部返航', DANGER, lambda: self._confirm(
            '全部返航', '全部 N 架返航（RTL）回各自起飞点？',
            lambda: self._swarm_act('返航', self.fleet.rtl_all)),
            font_size='15sp'))
        g.add_widget(self._mk_btn('全部投弹', DANGER, lambda: self._confirm(
            '全部投弹', '对全部 N 架同时发投弹指令（舵机6 PWM2000）？',
            lambda: self._swarm_act('投弹', self.fleet.bomb_all)),
            font_size='15sp'))
        g.add_widget(self._mk_btn('自动任务', ACCENT, lambda: self._swarm_act(
            '切自动', self.fleet.auto_all), font_size='15sp'))
        g.add_widget(self._mk_btn('全部模式', ACCENT, self._on_all_mode_btn,
                                  font_size='15sp'))

        # 行3/行4（全队高度/全队速度）拆出网格成独立整行——见下方 wrap 内重建
        # （领导：输入框横向拉长铺满左右、无留白；间距收紧向上贴顶）

        wrap = BoxLayout(orientation='vertical', spacing=8,
                         size_hint_y=None, height='234dp')
        wrap.add_widget(g)
        # 上方功能按钮区与全队高度/速度行整体明显分开（领导：与上面任务栏不重叠）
        wrap.add_widget(Label(text='', size_hint_y=None, height='28dp'))
        # 蓝色圆角毛玻璃框：全队高度 + 全队速度 两行整体框起（领导）
        bfm = BoxLayout(orientation='vertical', spacing=8, padding=(0, 8),
                        size_hint_y=None, height='104dp')
        # 行3：全队高度——输入框横拉铺满（领导：与按钮同高40dp）
        r3 = BoxLayout(orientation='horizontal', spacing=8, size_hint_y=None, height='40dp')
        _bh1 = self._mk_btn('全队高度', ACCENT, lambda *a: None,
                            size_hint_x=0.20, height='40dp', font_size='14sp', radius='8dp')
        r3.add_widget(_bh1)
        self._fm_alt = CompactTextInput(text='30', input_filter='float', font_size='18sp',
                                        size_hint_x=0.34, size_hint_y=None,
                                        height='40dp', halign='center')
        r3.add_widget(self._fm_alt)
        # 单位 m：红色按钮
        gm = self._mk_btn('m', DANGER, lambda *a: None, size_hint_x=0.12,
                       height='40dp', font_size='14sp', radius='8dp')
        r3.add_widget(gm)
        r3.add_widget(self._mk_btn('确定', OK, self._on_confirm_fm_alt,
                                   size_hint_x=0.34, font_size='14sp', height='40dp'))
        bfm.add_widget(r3)
        # 行4：全队速度——独立整行
        r4 = BoxLayout(orientation='horizontal', spacing=8, size_hint_y=None, height='40dp')
        _bh2 = self._mk_btn('全队速度', ACCENT, lambda *a: None,
                            size_hint_x=0.20, height='40dp', font_size='14sp', radius='8dp')
        r4.add_widget(_bh2)
        self._spd_all = CompactTextInput(text='10', input_filter='float', font_size='18sp',
                                         size_hint_x=0.34, size_hint_y=None,
                                         height='40dp', halign='center')
        r4.add_widget(self._spd_all)
        # 单位 m/s：红色按钮
        gms = self._mk_btn('m/s', DANGER, lambda *a: None, size_hint_x=0.12,
                          height='40dp', font_size='13sp', radius='8dp')
        r4.add_widget(gms)
        r4.add_widget(self._mk_btn('发送', OK, self._on_confirm_speed_all,
                                   size_hint_x=0.34, font_size='14sp', height='40dp'))
        bfm.add_widget(r4)
        wrap.add_widget(bfm)
        return wrap

    def _on_confirm_tof_alt(self, _x):
        self._append_log('起飞高度已设：%s m（下次「全部起飞」生效）' % self._tof_alt())

    def _on_confirm_fm_alt(self, _x):
        self._append_log('全队高度已设：%s m（下次「开始编队」/返航生效）' % self._fm_alt_val())

    def _on_confirm_alt_one(self, _x):
        try:
            v = float(self._alt_one.text)
        except Exception:
            v = 30.0
        self._append_log('本机高度已设：%s m（起飞/编队/返航高度参考）' % v)

    def _on_confirm_speed_one(self, _x):
        try:
            v = float(self._spd_one.text)
        except Exception:
            v = 5.0
        self._append_log('飞行速度已设：%s m/s（航点规划参考）' % v)

    def _on_confirm_speed_all(self, _x):
        try:
            v = float(self._spd_all.text)
        except Exception:
            v = 10.0
        if not self.fleet.connected:
            self._append_log('未连接：全队航速已记 %s m/s（连上后点「发送」）' % v)
            return
        n = self.fleet.set_speed_all(v)
        self._append_log('全队航速已发送：%s m/s（%d 架）' % (v, n))

    def _tof_alt(self):
        try:
            return float(self._tof_single.text)
        except Exception:
            return 20.0

    # ---------------- 二、队形编队 ----------------
    def _build_formation(self):
        b = BoxLayout(orientation='vertical', spacing=12,
                      size_hint_y=None, height='232dp')
        # 领导要求：队形区不再重复全队高度（①网格已有，编队/返航都读①的 _fm_alt）
        # 蓝色圆角毛玻璃框：前后/左右/小组 行整体框起（领导）
        gr2 = BoxLayout(orientation='horizontal', spacing=8, padding=(10, 6),
                        size_hint_y=None, height='52dp')
        r2 = BoxLayout(orientation='horizontal', spacing=8, size_hint_y=None, height='40dp')
        _bh3 = self._mk_btn('前后/左右/小组m', ACCENT, lambda *a: None,
                            size_hint_x=0.32, height='40dp', font_size='14sp', radius='8dp')
        r2.add_widget(_bh3)
        r2.add_widget(CompactTextInput(text=str(self.cfg['formation'].get('spacing_f', 5)),
                                       input_filter='float', font_size='18sp', size_hint_x=0.16))
        r2.add_widget(CompactTextInput(text=str(self.cfg['formation'].get('spacing_l', 5)),
                                       input_filter='float', font_size='18sp', size_hint_x=0.16))
        r2.add_widget(CompactTextInput(text=str(self.cfg['formation'].get('spacing_g', 10)),
                                       input_filter='float', font_size='18sp', size_hint_x=0.16))
        gr2.add_widget(r2)
        b.add_widget(gr2)
        r3 = BoxLayout(orientation='horizontal', spacing=0, size_hint_y=None, height='48dp')
        r3.add_widget(self._mk_btn('开始编队', OK, self._on_formation_start,
                                   size_hint_x=0.5, font_size='16sp'))
        r3.add_widget(self._mk_btn('暂停编队', DANGER, self._on_formation_stop,
                                   size_hint_x=0.5, font_size='16sp'))
        b.add_widget(r3)
        pg = GridLayout(cols=3, spacing=6, size_hint_y=None, height='96dp')
        for name in ['一字横排', '人字形', '前三角', '后三角', '梯形', '三角群']:
            pg.add_widget(self._mk_btn(name, (0.3, 0.3, 0.35, 1),
                                       lambda n=name: self._on_preset(n),
                                       height='42dp', font_size='15sp'))
        b.add_widget(pg)
        return b

    def _fm_alt_val(self):
        try:
            return float(self._fm_alt.text)
        except Exception:
            return 30.0

    def _on_preset(self, name):
        if not self.fleet.connected:
            self._append_log('未连接，队形仅更新本地偏移（连接后生效）')
        self.fleet.apply_preset(name)

    def _on_formation_start(self, _x):
        if not self.fleet.connected:
            self._append_log('未连接，无法开始编队')
            return
        self.fleet.formation_start(self._fm_alt_val())
        self._lbl_fm.text = '编队:开'
        self._lbl_fm.color = OK

    def _on_formation_stop(self, _x):
        self.fleet.formation_stop()
        self._lbl_fm.text = '编队:关'
        self._lbl_fm.color = GRAY
        self._lbl_lock.text = '上锁'
        self._lbl_lock.color = GRAY

    # ---------------- 三、单机操作 ----------------
    def _build_single(self):
        """单机操作页：控制元素整体下移，按钮圆润，底部固定本机切模式。"""
        b = BoxLayout(orientation='vertical', spacing=4, padding=(6, 0),
                      size_hint_y=None, height='422dp')
        # 选机行
        top = BoxLayout(orientation='horizontal', spacing=8, padding=(10, 4),
                        size_hint_y=None, height='40dp')
        self._sp_sys = Spinner(text='1号机', values=['%d号机' % i for i in range(1, 11)],
                               font_size='16sp', size_hint_x=0.36)
        self._sp_sys.bind(text=self._on_sys_changed)
        self._lbl_veh = Label(text='未选择', font_size='15sp', halign='left',
                              valign='middle', size_hint_x=0.64)
        top.add_widget(self._sp_sys)
        top.add_widget(self._lbl_veh)
        b.add_widget(Label(text='三、单机操作', font_size='18sp', bold=True,
                           color=(0.18, 0.4, 0.72, 1), size_hint_y=None, height='22dp',
                           halign='left', valign='middle'))
        b.add_widget(top)
        spc = BoxLayout(size_hint_y=None, height='6dp')
        b.add_widget(spc)

        # （领导：删占位空白——全部控件上移贴紧，不留大片空白）

        # 控制按钮区（2 列 3 行）
        gwrap = BoxLayout(orientation='vertical', spacing=2, size_hint_y=None, height='178dp')
        g = GridLayout(cols=2, spacing=6, size_hint_y=None, height='178dp')
        g.add_widget(self._mk_btn('单机起飞', OK, lambda: self._confirm(
            '单机起飞', '%s 按 %s m 起飞？' % (self._sel_name(), self._tof_alt()),
            lambda: self._single_act('起飞', self.fleet.takeoff, self._tof_alt())),
            font_size='16sp', height='40dp', radius='16dp'))
        g.add_widget(self._mk_btn('单机降落', OK, lambda: self._confirm(
            '单机降落', '%s 立即降落？' % self._sel_name(),
            lambda: self._single_act('降落', self.fleet.land)),
            font_size='16sp', height='40dp', radius='16dp'))
        g.add_widget(self._mk_btn('单机解锁', ACCENT, lambda: self._confirm(
            '单机解锁', '%s 解锁？' % self._sel_name(),
            lambda: self._single_act('解锁', self.fleet.arm, True)),
            font_size='16sp', height='40dp', radius='16dp'))
        g.add_widget(self._mk_btn('单机上锁', ACCENT, lambda: self._confirm(
            '单机上锁', '%s 上锁（仅地面）？' % self._sel_name(),
            lambda: self._single_act('上锁', self.fleet.arm, False)),
            font_size='16sp', height='40dp', radius='16dp'))
        g.add_widget(self._mk_btn('单机返航', DANGER, lambda: self._confirm(
            '单机返航', '%s 返航 RTL？' % self._sel_name(),
            lambda: self._single_act('返航', self.fleet.rtl)),
            font_size='16sp', height='40dp', radius='16dp'))
        g.add_widget(self._mk_btn('单机投弹', DANGER, lambda: self._confirm(
            '单机投弹', '%s 投弹（舵机6 PWM2000）？' % self._sel_name(),
            lambda: self._single_act('投弹', self.fleet.bomb)),
            font_size='16sp', height='40dp', radius='16dp'))
        g.add_widget(self._mk_btn('自动', (0.95, 0.72, 0.34, 1), self._on_single_auto,
                                  font_size='16sp', height='40dp', radius='16dp'))
        g.add_widget(self._mk_btn('悬停', (0.95, 0.72, 0.34, 1), self._on_single_loiter,
                                  font_size='16sp', height='40dp', radius='16dp'))
        gwrap.add_widget(g)
        b.add_widget(gwrap)
        # 本机高度/本机速度——蓝色圆角毛玻璃框（同①页全队行）+ m/m/s 灰色小毛玻璃框
        bpar = BoxLayout(orientation='vertical', spacing=6, padding=(0, 8),
                         size_hint_y=None, height='104dp')
        rh = BoxLayout(orientation='horizontal', spacing=8, size_hint_y=None, height='40dp')
        rh.add_widget(self._mk_btn('本机高度', ACCENT, lambda *a: None,
                                   size_hint_x=0.20, height='40dp', font_size='14sp', radius='8dp'))
        self._alt_one = CompactTextInput(text='30', input_filter='float', font_size='18sp',
                                         size_hint_x=0.34, size_hint_y=None,
                                         height='40dp', halign='center')
        rh.add_widget(self._alt_one)
        gm2 = self._mk_btn('m', DANGER, lambda *a: None, size_hint_x=0.12,
                           height='40dp', font_size='14sp', radius='8dp')
        rh.add_widget(gm2)
        rh.add_widget(self._mk_btn('确认', OK, self._on_confirm_alt_one,
                                   size_hint_x=0.34, font_size='14sp', height='40dp'))
        bpar.add_widget(rh)
        rs = BoxLayout(orientation='horizontal', spacing=8, size_hint_y=None, height='40dp')
        rs.add_widget(self._mk_btn('本机速度', ACCENT, lambda *a: None,
                                   size_hint_x=0.20, height='40dp', font_size='14sp', radius='8dp'))
        self._spd_one = CompactTextInput(text='5', input_filter='float', font_size='18sp',
                                         size_hint_x=0.34, size_hint_y=None,
                                         height='40dp', halign='center')
        rs.add_widget(self._spd_one)
        gms2 = self._mk_btn('m/s', DANGER, lambda *a: None, size_hint_x=0.12,
                            height='40dp', font_size='13sp', radius='8dp')
        rs.add_widget(gms2)
        rs.add_widget(self._mk_btn('确认', OK, self._on_confirm_speed_one,
                                   size_hint_x=0.34, font_size='14sp', height='40dp'))
        bpar.add_widget(rs)
        b.add_widget(BoxLayout(size_hint_y=None, height='4dp'))
        b.add_widget(bpar)
        b.add_widget(BoxLayout(size_hint_y=None, height='4dp'))
        b.add_widget(self._mk_btn('单机切换模式', ACCENT, self._on_single_mode_btn,
                                  size_hint_x=1.0, height='44dp', radius='12dp',
                                  font_size='18sp'))
        return b

    def _sel_sysid(self):
        try:
            return int(self._sp_sys.text.replace('号机', ''))
        except Exception:
            return 1

    def _sel_name(self):
        return '%s' % self._sp_sys.text

    def _on_sys_changed(self, _sp, _text):
        self._sel_sys = self._sel_sysid()
        self._refresh_mission_table()

    def _mode_popup(self, title, on_pick):
        """通用模式选择弹窗：2 列紧凑网格，避免 ScrollView 导致点不动。"""
        popup = Popup(title=title, size_hint=(0.9, 0.62), auto_dismiss=True)
        grid = GridLayout(cols=2, spacing=8, padding=10)
        for item in MODE_SPINNER_VALUES:
            num = int(item.split('(')[-1].rstrip(')'))
            grid.add_widget(self._mk_btn(
                item, ACCENT,
                lambda _x, n=num, it=item: (popup.dismiss(), on_pick(n, it)),
                height='48dp', font_size='15sp'))
        popup.content = grid
        # 延迟一帧打开，避免安卓 Popup 首次尺寸为 0 导致内容错位
        Clock.schedule_once(lambda *a: popup.open(), 0.05)
        return popup

    def _on_single_auto(self, _x):
        self._single_act('切自动', self.fleet.set_mode, 3)

    def _on_single_loiter(self, _x):
        self._single_act('悬停', self.fleet.set_mode, 5)

    def _on_single_join_auto(self, _x):
        self._single_act('接自动', self.fleet.set_mode, 3)

    def _on_single_mode_btn(self, _x):
        self._mode_popup(
            '切换 %s 飞行模式' % self._sel_name(),
            lambda n, it: self._pick_single_mode(n, it))

    def _pick_single_mode(self, num, text):
        self._single_act('切模式→%s' % text, self.fleet.set_mode, num)

    def _on_all_mode_btn(self, _x):
        self._mode_popup(
            '切换全队飞行模式',
            lambda n, it: self._pick_all_mode(n, it))

    def _pick_all_mode(self, num, text):
        self._swarm_act('切模式→%s' % text, self.fleet.set_mode_all, num)

    def _single_act(self, label, fn, *args):
        if not self.fleet.connected:
            self._append_log('未连接')
            popup = Popup(title='未连接', size_hint=(0.7, 0.3),
                          auto_dismiss=True)
            box = BoxLayout(orientation='vertical', padding=12)
            box.add_widget(Label(text='未连接服务器，无法操作\n请先点击顶部「连接」', font_size='15sp'))
            popup.content = box
            Clock.schedule_once(lambda *a: popup.open(), 0.05)
            return
        try:
            ok = fn(self._sel_sysid(), *args)
            self._append_log('%s %s：%s' % (self._sel_name(), label,
                                           '指令已发送' if ok else '发送失败'))
        except Exception as e:
            self._append_log('%s %s 失败：%s' % (self._sel_name(), label, e))

    # ---------------- 四、任务航点 ----------------
    def _build_mission(self):
        """任务航线页控件区：输入框紧凑，按钮圆润，功能分区。"""
        b = BoxLayout(orientation='vertical', spacing=4, size_hint_y=1,
                      padding=(8, 2))
        # 目标机行：航点/任务都发给这架（领导：加航点必须明确是几号机）
        rt = BoxLayout(orientation='horizontal', spacing=5, size_hint_y=None, height='40dp')
        self._sp_tgt = RoundedButton(text='1号机', font_size='15sp', size_hint_x=0.25,
                                      size_hint_y=None, height='40dp',
                                      background_color=(0.18, 0.35, 0.55, 1),
                                      on_release=lambda *a: self._pick_aircraft())
        rt.add_widget(self._sp_tgt)
        bx = BoxLayout(orientation='vertical', spacing=1, size_hint_x=0.25)
        self._wp_lat = CompactTextInput(hint_text='', input_filter='float',
                                        size_hint_y=None, height='24dp', halign='center')
        bx.add_widget(self._wp_lat)
        bx.add_widget(Label(text='纬度', font_size='14sp', size_hint_y=None, height='14dp',
                            halign='center', valign='middle', color=(0.7, 0.75, 0.7, 1)))
        rt.add_widget(bx)
        by = BoxLayout(orientation='vertical', spacing=1, size_hint_x=0.25)
        self._wp_lon = CompactTextInput(hint_text='', input_filter='float',
                                        size_hint_y=None, height='24dp', halign='center')
        by.add_widget(self._wp_lon)
        by.add_widget(Label(text='经度', font_size='14sp', size_hint_y=None, height='14dp',
                            halign='center', valign='middle', color=(0.7, 0.75, 0.7, 1)))
        rt.add_widget(by)
        bz = BoxLayout(orientation='vertical', spacing=1, size_hint_x=0.25)
        self._wp_alt = CompactTextInput(hint_text='', input_filter='float',
                                        size_hint_y=None, height='24dp', halign='center')
        bz.add_widget(self._wp_alt)
        bz.add_widget(Label(text='高度m', font_size='14sp', size_hint_y=None, height='14dp',
                            halign='center', valign='middle', color=(0.7, 0.75, 0.7, 1)))
        rt.add_widget(bz)
        b.add_widget(rt)

        # 功能按钮 4 等份：全屏地图/坐标换算/添加航点/添加投弹 一行平铺
        r3 = GridLayout(cols=4, spacing=4, size_hint_y=None, height='40dp',
                        padding=(0, 0))
        r3.add_widget(self._mk_btn('全屏地图', (0.15, 0.6, 0.35, 1),
                                   self._on_open_map, font_size='14sp',
                                   height='40dp'))
        r3.add_widget(self._mk_btn('坐标换算', (0.55, 0.4, 0.2, 1),
                                   self._on_open_coord, font_size='14sp',
                                   height='40dp'))
        r3.add_widget(self._mk_btn('添加航点', ACCENT, self._on_add_wp,
                                   font_size='14sp', height='40dp'))
        r3.add_widget(self._mk_btn('功能导航', DANGER, self._open_function_nav,
                                   font_size='14sp', height='40dp'))
        b.add_widget(r3)

        # 最底行：上传任务 / 读取航线 / 定位飞机 / 清除任务（4 个平铺）
        r1 = BoxLayout(orientation='horizontal', spacing=5,
                       size_hint_y=None, height='40dp')
        r1.add_widget(self._mk_btn('上传任务', ACCENT, lambda: self._confirm(
            '上传任务', '把当前任务（%d 条）写入 %s？' % (self._mission_len(), self._sel_name()),
            self._on_upload_mission), size_hint_x=0.25, font_size='13sp', height='40dp'))
        r1.add_widget(self._mk_btn('读取航线', ACCENT, self._on_read_route,
                                   size_hint_x=0.25, font_size='13sp', height='40dp'))
        r1.add_widget(self._mk_btn('定位飞机', ACCENT, self._on_locate_vehicle,
                                   size_hint_x=0.25, font_size='13sp', height='40dp'))
        r1.add_widget(self._mk_btn('清除任务', GRAY, self._on_clear_mission,
                                   size_hint_x=0.25, font_size='13sp', height='40dp'))
        b.add_widget(r1)

        return b

    def _mission_len(self):
        v = self.fleet.vehicle(self._sel_sysid())
        return len(v.mission) if v else 0

    def _refresh_mission_table(self):
        # 可能从网络线程（任务下载/上传回调）触发 —— 同样调度到主线程
        Clock.schedule_once(lambda _dt: self._refresh_mission_table_impl(), 0)

    def _refresh_mission_table_impl(self):
        """任务信息：对齐表格（序号/指令/位置/高度m/悬停s），行可点选"""
        v = self.fleet.vehicle(self._mission_sysid())
        rows = v.mission if v else []
        self._mission_box.clear_widgets()
        sel = self._sel_seq
        cols = (('序号', 0.10), ('指令', 0.18), ('位置', 0.36), ('高度m', 0.14), ('悬停s', 0.22))
        # 表头
        hd = BoxLayout(orientation='horizontal', spacing=0, size_hint_y=None, height='18dp')
        for h, w in cols:
            hd.add_widget(Label(text=h, font_size='12sp', bold=True, size_hint_x=w,
                                halign='center', valign='middle', color=(0.7, 0.85, 0.7, 1)))
        self._mission_box.add_widget(hd)
        for it in rows:
            cmd = vehicles.MAV_CMD_ZH.get(it['cmd'], 'M%g' % it['cmd'])
            if it.get('kind') == 'collect':
                cmd = '集合点'
            elif it.get('kind') == 'disperse':
                cmd = '离散点'
            if it['cmd'] == 184:
                pos = '--'
                alt = '--'
                hover = '%.0f' % it.get('param1', 0)
            else:
                pos = '%.4f,%.4f' % (it['lat'], it['lon'])
                alt = '%.1f' % it['alt'] if it['alt'] else '--'
                hover = '--'
            selrow = (sel == it['seq'])
            row = BoxLayout(orientation='horizontal', spacing=0, size_hint_y=None, height='20dp')
            for txt, w in ((str(it['seq']), 0.10), (cmd, 0.18), (pos, 0.36),
                           (alt, 0.14), (hover, 0.22)):
                lbl = Label(text=txt, font_size='12sp', size_hint_x=w,
                            halign='center', valign='middle',
                            color=(0.5, 0.9, 0.5, 1) if selrow else (0.85, 0.85, 0.85, 1))
                row.add_widget(lbl)
            row.on_touch_down = (lambda touch, s=it['seq'], r=row:
                                 self._mission_row_touch(r, touch, s))
            self._mission_box.add_widget(row)
        # 补齐到 4 行（不足用空行占位，使表格固定显示 4 行）
        for _ in range(max(0, 4 - len(rows))):
            row = BoxLayout(orientation='horizontal', spacing=0, size_hint_y=None, height='20dp')
            for w in (0.10, 0.18, 0.36, 0.14, 0.22):
                row.add_widget(Label(text='--', font_size='12sp', size_hint_x=w,
                                     halign='center', valign='middle',
                                     color=(0.55, 0.55, 0.55, 1)))
            self._mission_box.add_widget(row)
        if not rows:
            self._mission_box.add_widget(Label(text='（任务为空——下载或设置航点）',
                                               font_size='12sp', height='20dp', size_hint_y=None,
                                               color=(0.6, 0.6, 0.6, 1)))
        self._refresh_map_route()

    def _refresh_map_route(self):
        """把当前机任务航点画到地图上（圆点+相邻连线）"""
        try:
            v = self.fleet.vehicle(self._mission_sysid())
            route = []
            drag = []
            if v:
                for i, it in enumerate(getattr(v, 'mission', [])):
                    lat = it.get('lat')
                    lon = it.get('lon')
                    if lat and lon and abs(lat) > 1 and abs(lon) > 1:
                        route.append((lat, lon))
                        drag.append((i, lat, lon))
            self._map_route_layer.set_route(route)
            self._map_page.set_draggable_points(drag)
        except Exception:
            pass

    def _on_point_drag(self, ev, seq, lat, lon):
        """长按拖动航点：实时改经纬，松手刷新"""
        sid = self._mission_sysid()
        v = self.fleet.vehicle(sid)
        if not v or not v.mission or seq is None or seq >= len(v.mission):
            return
        if ev == 'start':
            self._sel_seq = seq
            self._refresh_mission_table()
        elif ev in ('move', 'end'):
            v.mission[seq]['lat'] = lat
            v.mission[seq]['lon'] = lon
            self._refresh_map_route()
            if ev == 'end':
                self._refresh_mission_table()
                self._append_log('%s号机 #%s 航点已移动到 (%.6f, %.6f)' % (sid, seq, lat, lon))

    def _refresh_map_aircraft(self):
        """把有GPS的在线机位置画到地图（<8颗星灰点，>=8颗星蓝点）"""
        try:
            planes = []
            for s in sorted(self.fleet.fleet):
                v = self.fleet.fleet[s]
                if getattr(v, 'online', False) and v.lat is not None and abs(v.lat) > 1:
                    planes.append((s, v.lat, v.lon, getattr(v, 'satellites', None)))
            self._map_route_layer.set_aircraft(planes)
        except Exception:
            pass

    def _on_mission_row(self, seq):
        self._sel_seq = seq
        self._refresh_mission_table()

    def _mission_row_touch(self, row, touch, seq):
        if not row.collide_point(*touch.pos):
            return False
        now = touch.time_start
        # 双击行：判断点的是哪列 -> 指令菜单 / 编辑高度 / 悬停 / 经纬度
        if self._row_last_tap_t and now - self._row_last_tap_t < 0.45 and self._row_last_seq == seq:
            self._row_last_tap_t = 0
            rel = (touch.x - row.x) / max(1.0, row.width)
            if rel < 0.28:
                col = 0      # 序号/指令列 -> 指令切换菜单
            elif rel < 0.64:
                col = 2      # 位置列 -> 编辑经纬度
            elif rel < 0.78:
                col = 3      # 高度列 -> 编辑高度
            else:
                col = 4      # 悬停列 -> 编辑悬停
            self._row_double_tap(seq, col)
            return True
        self._row_last_tap_t = now
        self._row_last_seq = seq
        self._on_mission_row(seq)
        return True

    def _row_double_tap(self, seq, col):
        if col == 0:
            self._row_cmd_menu(seq)
        elif col == 2:
            self._edit_wp_pos(seq)
        elif col == 3:
            self._edit_wp_alt(seq)
        elif col == 4:
            self._edit_wp_hold(seq)

    def _row_cmd_menu(self, seq):
        """双击航点行：切指令（起飞/投弹/返航/集合/离散/清除）"""
        sid = self._mission_sysid()
        v = self.fleet.vehicle(sid)
        if not v or not v.mission or seq >= len(v.mission):
            return
        popup = Popup(title='航点指令 · #%s' % seq, size_hint=(0.85, 0.62), auto_dismiss=True)
        box = BoxLayout(orientation='vertical', spacing=6, padding=12)
        mk = lambda t, c, cb: self._mk_btn(t, c, cb, size_hint_y=None, height='46dp', font_size='15sp')
        box.add_widget(mk('起飞 Takeoff（%sm）' % self._tof_alt(), OK,
                          lambda: self._takeoff_double_tap(sid, popup)))
        box.add_widget(mk('投弹任务（184）', DANGER, lambda: self._bomb_double_tap(sid, popup)))
        box.add_widget(mk('返航 RTL', ACCENT, lambda: self._rtl_double_tap(sid, popup)))
        kind = v.mission[seq].get('kind')
        ktxt = '集合点' if kind == 'collect' else ('离散点' if kind == 'disperse' else '普通')
        box.add_widget(mk('设为集合点（当前:%s）' % ktxt, ACCENT,
                          lambda: self._menu_kind(sid, seq, popup, 'collect')))
        box.add_widget(mk('设为离散点（当前:%s）' % ktxt, ACCENT,
                          lambda: self._menu_kind(sid, seq, popup, 'disperse')))
        box.add_widget(mk('清除任务', GRAY, lambda: self._clear_double_tap(sid, popup)))
        popup.content = box
        Clock.schedule_once(lambda *a: popup.open(), 0.05)

    def _edit_wp_alt(self, seq):
        sid = self._mission_sysid()
        v = self.fleet.vehicle(sid)
        if not v or not v.mission or seq >= len(v.mission):
            self._append_log('无此航点')
            return
        self._input_dialog('编辑高度（#%s）' % seq, '高度(m)',
                           lambda val: self._set_wp_alt(sid, seq, val),
                           default=str(v.mission[seq].get('alt', 0)))

    def _edit_wp_hold(self, seq):
        sid = self._mission_sysid()
        v = self.fleet.vehicle(sid)
        if not v or not v.mission or seq >= len(v.mission):
            self._append_log('无此航点')
            return
        self._input_dialog('编辑悬停（#%s）' % seq, '悬停(秒)',
                           lambda val: self._set_wp_hold(sid, seq, val),
                           default=str(v.mission[seq].get('p1', 0)))

    def _edit_wp_pos(self, seq):
        sid = self._mission_sysid()
        v = self.fleet.vehicle(sid)
        if not v or not v.mission or seq >= len(v.mission):
            self._append_log('无此航点')
            return
        it = v.mission[seq]
        cur = '%.6f,%.6f' % (it.get('lat', 0), it.get('lon', 0))
        self._input_dialog('编辑经纬度（#%s）' % seq, '纬度,经度',
                           lambda val: self._set_wp_pos(sid, seq, val),
                           default=cur, input_filter=None)

    def _set_wp_pos(self, sid, seq, val):
        try:
            parts = val.replace('，', ',').split(',')
            lat = float(parts[0].strip())
            lon = float(parts[1].strip())
        except Exception:
            self._append_log('经纬度无效，格式：纬度,经度')
            return
        v = self.fleet.vehicle(sid)
        if v and v.mission and seq < len(v.mission):
            v.mission[seq]['lat'] = lat
            v.mission[seq]['lon'] = lon
            self._refresh_mission_table()
            self._map_page._center = (lat, lon)
            self._map_page._zoom = max(self._map_page._zoom, 15)
            self._map_page._rebuild()
            self._append_log('%s号机 #%s 经纬度已改 (%.6f, %.6f)——地图已定位' % (sid, seq, lat, lon))

    def _on_download_mission(self, _x):
        if not self.fleet.connected:
            self._append_log('未连接')
            return
        self._append_log('正在下载 %s 任务…' % self._sel_name())
        self.fleet.download_mission(self._mission_sysid())

    def _on_locate_vehicle(self, *_a):
        """定位飞机：地图中心移到有GPS的机位置并放大
        优先页③当前选中机；若无GPS则自动取第一架有GPS的在线机"""
        sid = self._mission_sysid()
        v = self.fleet.vehicle(sid)
        if not (v and getattr(v, 'online', False) and v.lat is not None):
            v = None
            for cand_s in sorted(self.fleet.fleet):
                cand = self.fleet.fleet[cand_s]
                if getattr(cand, 'online', False) and cand.lat is not None:
                    v = cand
                    sid = cand_s
                    break
        if not v:
            self._append_log('定位：无 有GPS 的在线飞机')
            return
        try:
            self._map_page._center = (v.lat, v.lon)
            self._map_page._zoom = 16
            self._map_page._rebuild()
            self._append_log('定位：%s号机 (%.6f, %.6f)' % (sid, v.lat, v.lon))
        except Exception as e:
            self._append_log('定位失败：%s' % e)
    def _on_read_route(self, _x):
        if not self.fleet.connected:
            self._append_log('未连接')
            return
        self._append_log('正在读取 %s 航线…' % self._sel_name())
        self.fleet.download_mission(self._mission_sysid())

    def _on_read_wp(self, _x):
        if not self.fleet.connected:
            self._append_log('未连接')
            return
        self._append_log('正在读取 %s 航点表…' % self._sel_name())
        self.fleet.download_mission(self._mission_sysid())

    def _on_upload_mission(self):
        if not self.fleet.connected:
            self._append_log('未连接')
            return
        self._append_log('正在上传 %s 任务…' % self._sel_name())
        self.fleet.upload_mission(self._mission_sysid())

    def _on_clear_mission(self, _x):
        sid = self._mission_sysid()
        self._confirm('清除任务', '清除 %s号机 全部任务航点？（本地，上传才写飞机）' % sid,
                      lambda: self._clear_mission_tgt(sid))

    def _mission_sysid(self):
        """③页目标机号（航点/任务操作对象，默认 1 号机）"""
        try:
            return int(self._sp_tgt.text.replace('号机', ''))
        except Exception:
            return 1

    def _pick_aircraft(self):
        """选目标机号：弹 1~10 号机按钮（手机端比 Spinner 下拉可靠）"""
        popup = Popup(title='选择目标机', size_hint=(0.62, 0.66), auto_dismiss=True)
        box = GridLayout(cols=2, spacing=8, padding=14)
        for i in range(1, 11):
            box.add_widget(self._mk_btn('%d号机' % i, ACCENT,
                                         lambda i=i: self._set_tgt(i, popup),
                                         size_hint_y=None, height='44dp', font_size='17sp'))
        popup.content = box
        Clock.schedule_once(lambda *a: popup.open(), 0.05)

    def _set_tgt(self, i, popup):
        popup.dismiss()
        self._sp_tgt.text = '%d号机' % i
        self._append_log('目标机：%s号机（添加航点/任务对象）' % i)

    def _on_add_wp(self, _x):
        try:
            lat = float(self._wp_lat.text)
            lon = float(self._wp_lon.text)
        except Exception:
            self._append_log('加航点失败：纬度/经度未填全')
            return
        try:
            alt = float(self._wp_alt.text) if self._wp_alt.text.strip() else 100.0
        except Exception:
            alt = 100.0
        sid = self._mission_sysid()
        self.fleet.append_waypoint(sid, lat, lon, alt)
        self._refresh_mission_table()
        # 地图拉到新航点（定位）
        self._map_page._center = (lat, lon)
        self._map_page._zoom = max(self._map_page._zoom, 15)
        self._map_page._rebuild()
        self._append_log('%s号机 已加航点 (%.6f, %.6f, %sm)——地图已定位到此点' % (
            sid, lat, lon, alt))

    def _on_add_bomb(self, _x):
        if self._sel_seq is None:
            self._append_log('请先在任务表点选一个航点，再「添加投弹」')
            return
        self.fleet.add_bomb_after(self._mission_sysid(), self._sel_seq)
        self._refresh_mission_table()

    def _open_function_nav(self, _x=None):
        """底部「功能导航」：一键弹出任务功能菜单（添加航点/投弹/高度/悬停/集合/离散/返航/清除/起飞）"""
        sid = self._mission_sysid()
        v = self.fleet.vehicle(sid)
        seq = self._sel_seq
        popup = Popup(title='功能导航 · %s号机' % sid, size_hint=(0.9, 0.85), auto_dismiss=True)
        sc = ScrollView()
        box = BoxLayout(orientation='vertical', spacing=6, padding=12, size_hint_y=None)
        box.bind(minimum_height=box.setter('height'))
        mk = lambda t, c, cb: self._mk_btn(t, c, cb, size_hint_y=None, height='46dp', font_size='15sp')
        it = v.mission[seq] if (v and v.mission and seq is not None and seq < len(v.mission)) else {}
        kind = it.get('kind')
        ktxt = '集合点' if kind == 'collect' else ('离散点' if kind == 'disperse' else '普通')
        bcfg = self.cfg.get('bomb', {})
        box.add_widget(mk('① 起飞 Takeoff（%sm）' % self._tof_alt(), OK,
                          lambda: self._takeoff_double_tap(sid, popup)))
        box.add_widget(mk('② 添加航点（当前输入坐标）', ACCENT,
                          lambda: (popup.dismiss(), self._on_add_wp(None))))
        box.add_widget(mk('③ 返航 RTL', ACCENT, lambda: self._rtl_double_tap(sid, popup)))
        box.add_widget(mk('④ 设航点高度（当前 %sm）' % it.get('alt', 0), ACCENT,
                          lambda: self._menu_alt(sid, seq, popup)))
        box.add_widget(mk('⑤ 投弹舵机设置（当前 %d 号舵机·PWM %s）' % (bcfg.get('servo', 6), bcfg.get('pwm', 2000)),
                          DANGER, lambda: self._bomb_servo_set(sid, popup)))
        box.add_widget(mk('⑥ 设为集合点（当前:%s）' % ktxt, ACCENT,
                          lambda: self._menu_kind(sid, seq, popup, 'collect')))
        box.add_widget(mk('⑦ 设为离散点（当前:%s）' % ktxt, ACCENT,
                          lambda: self._menu_kind(sid, seq, popup, 'disperse')))
        box.add_widget(mk('⑧ 清除任务', GRAY, lambda: self._clear_double_tap(sid, popup)))
        box.add_widget(mk('⑨ 定位校准（两定点重叠，地图纠偏）', (0.7, 0.5, 0.95, 1),
                          lambda: (popup.dismiss(), self._open_geo_calib())))
        sc.add_widget(box)
        popup.content = sc
        Clock.schedule_once(lambda *a: popup.open(), 0.05)
        self._append_log('功能导航：%s号机' % sid)

    def _map_default_center(self):
        """地图默认中心：首选首架在线机坐标，否则默认市区"""
        for s in sorted(self.fleet.fleet):
            v = self.fleet.fleet[s]
            lat = getattr(v, 'lat', None)
            lon = getattr(v, 'lon', None)
            if getattr(v, 'online', False) and lat and lon and lat != 0:
                return (lat, lon)
        return (34.26, 108.94)

    def _on_map_pick_embed(self, lat, lng):
        """内嵌地图单击 = 回填经纬 + 直接加一个坐标点（航点）"""
        self._wp_lat.text = '%.6f' % lat
        self._wp_lon.text = '%.6f' % lng
        try:
            alt = float(self._wp_alt.text) if self._wp_alt.text.strip() else 100.0
        except Exception:
            alt = 100.0
        sid = self._mission_sysid()
        self.fleet.append_waypoint(sid, lat, lng, alt)
        self._refresh_mission_table()
        self._append_log('%s号机 已加航点 (%.6f, %.6f, %sm)——点「上传任务」写入飞机' % (
            sid, lat, lng, alt))

    def _on_map_double_tap(self, lat, lng):
        """双击地图：不再弹菜单——改用下方「功能导航」+ 任务表选行操作"""
        self._append_log('双击地图：请在下方「功能导航」选择操作，并先点任务表选中航点')

    def _nearest_wp_seq_at(self, lat, lng, v):
        """双击点附近(屏幕~28px≈标记/几米)是否有已有航点；有则返回其 seq"""
        if not v or not v.mission:
            return None
        mp = getattr(self, '_map_page', None)
        g = getattr(mp, '_grid', None)
        pc = getattr(mp, '_px_center', None)
        if g is None or not pc:
            return None
        z = mp._zoom
        cx_px, cy_px = pc
        gx, gy = g.center_x, g.center_y
        try:
            llat_gcj, llng_gcj = mp._to_disp(lat, lng)
            dpx = mapview._lng_to_px(llng_gcj, z)
            dpy = mapview._lat_to_px(llat_gcj, z)
            dsx = gx + (dpx - cx_px)
            dsy = gy - (dpy - cy_px)
        except Exception:
            return None
        best_d = 1e18
        best = None
        for i, it in enumerate(v.mission):
            ilat = it.get('lat')
            ilon = it.get('lon')
            if not ilat or not ilon or abs(ilat) < 1 or abs(ilon) < 1:
                continue
            try:
                ilat_gcj, ilng_gcj = mp._to_disp(ilat, ilon)
                px = mapview._lng_to_px(ilng_gcj, z)
                py = mapview._lat_to_px(ilat_gcj, z)
                sx = gx + (px - cx_px)
                sy = gy - (py - cy_px)
                d = ((sx - dsx) ** 2 + (sy - dsy) ** 2) ** 0.5
                if d < best_d:
                    best_d = d
                    best = i
            except Exception:
                pass
        return best if best_d <= 28 else None

    def _menu_alt(self, sid, seq, popup):
        popup.dismiss()
        self._input_dialog('设航点高度（%s号机 #%s）' % (sid, seq), '高度(m)',
                           lambda val: self._set_wp_alt(sid, seq, val))

    def _menu_hold(self, sid, seq, popup):
        popup.dismiss()
        self._input_dialog('悬停时间（%s号机 #%s）' % (sid, seq), '悬停(秒)',
                           lambda val: self._set_wp_hold(sid, seq, val))

    def _menu_kind(self, sid, seq, popup, kind):
        popup.dismiss()
        if seq is None:
            self._append_log('请先在任务表点选一个航点')
            return
        v = self.fleet.vehicle(sid)
        if v and v.mission and seq < len(v.mission):
            if v.mission[seq].get('kind') == kind:
                v.mission[seq].pop('kind', None)     # 再点一次取消
            else:
                v.mission[seq]['kind'] = kind
            self._refresh_mission_table()
            self._append_log('%s号机 #%s 设为%s' % (sid, seq, '集合点' if kind == 'collect' else '离散点'))

    def _set_wp_alt(self, sid, seq, val):
        if seq is None:
            self._append_log('请先在任务表点选一个航点，再设高度')
            return
        try:
            altv = float(val)
        except Exception:
            self._append_log('高度值无效：%s' % val)
            return
        v = self.fleet.vehicle(sid)
        if v and v.mission and seq < len(v.mission):
            v.mission[seq]['alt'] = altv
            self._refresh_mission_table()
            self._append_log('%s号机 #%s 高度=%sm' % (sid, seq, altv))

    def _set_wp_hold(self, sid, seq, val):
        if seq is None:
            self._append_log('请先在任务表点选一个航点，再设悬停')
            return
        try:
            sec = float(val)
        except Exception:
            self._append_log('悬停值无效：%s' % val)
            return
        v = self.fleet.vehicle(sid)
        if v and v.mission and seq < len(v.mission):
            v.mission[seq]['p1'] = sec
            self._refresh_mission_table()
            self._append_log('%s号机 #%s 悬停=%ss' % (sid, seq, sec))

    def _input_dialog(self, title, label, on_ok, default=None, input_filter='float'):
        popup = Popup(title=title, size_hint=(0.82, 0.42), auto_dismiss=True)
        box = BoxLayout(orientation='vertical', spacing=10, padding=14)
        box.add_widget(Label(text=label, halign='center', font_size='15sp'))
        tin = CompactTextInput(text=str(default) if default is not None else '',
                               hint_text=label, input_filter=input_filter, font_size='18sp')
        box.add_widget(tin)
        row = BoxLayout(size_hint_y=None, height='46dp', spacing=10)
        row.add_widget(self._mk_btn('确定', ACCENT, lambda: (popup.dismiss(), on_ok(tin.text)),
                                    size_hint_y=None, height='46dp'))
        row.add_widget(self._mk_btn('取消', GRAY, lambda: popup.dismiss(),
                                    size_hint_y=None, height='46dp'))
        box.add_widget(row)
        popup.content = box
        Clock.schedule_once(lambda *a: popup.open(), 0.05)

    def _bomb_double_tap(self, sid, popup):
        popup.dismiss()
        self._confirm('投弹', '在 %s号机任务末尾追加投弹点（舵机6 PWM2000）？' % sid,
                      lambda: self._bomb_append(sid))

    def _bomb_append(self, sid):
        if self._sel_seq is None:
            self._append_log('请先在地图下方任务表点选一个航点，再「投弹」插入其后')
            return
        self.fleet.add_bomb_after(sid, self._sel_seq)
        self._refresh_mission_table()
        self._append_log('%s号机 已插入投弹点' % sid)

    def _bomb_servo_set(self, sid, popup):
        popup.dismiss()
        bcfg = self.cfg.setdefault('bomb', {})
        cur = '%d,%s' % (bcfg.get('servo', 6), bcfg.get('pwm', 2000))
        self._input_dialog('投弹舵机设置（%s号机）' % sid, '舵机号,PWM（如 6,2000）',
                           lambda val: self._bomb_servo_apply(val),
                           default=cur, input_filter=None)

    def _bomb_servo_apply(self, val):
        try:
            parts = val.replace('，', ',').split(',')
            servo = int(parts[0].strip())
            pwm = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else 2000
            b = self.cfg.setdefault('bomb', {})
            b['servo'] = servo
            b['pwm'] = pwm
            self._append_log('投弹设置：%d 号舵机，PWM %d（下次「添加投弹」生效）' % (servo, pwm))
        except Exception:
            self._append_log('设置无效：请填 舵机号,PWM（如 6,2000）')

    def _clear_double_tap(self, sid, popup):
        popup.dismiss()
        self._confirm('清空航线', '清除 %s号机全部任务航点？' % sid,
                      lambda: self._clear_mission_tgt(sid))

    def _clear_mission_tgt(self, sid):
        # 清除本地任务不依赖连接（上传才写飞机）
        self.fleet.clear_mission(sid)
        self._refresh_mission_table()
        self._append_log('%s号机 任务已清空（本地）' % sid)

    def _rtl_double_tap(self, sid, popup):
        popup.dismiss()
        self._confirm('返航', '%s号机 返航 RTL？' % sid,
                      lambda: self._rtl_tgt(sid))

    def _rtl_tgt(self, sid):
        if not self.fleet.connected:
            self._append_log('未连接：无法返航')
            return
        self.fleet.rtl(sid)
        self._append_log('%s号机 返航指令已发' % sid)

    def _takeoff_double_tap(self, sid, popup):
        popup.dismiss()
        self._input_dialog('起飞 Takeoff（%s号机）' % sid, '起飞高度(m)',
                           lambda val: self._takeoff_tgt(sid, val),
                           default=str(self._tof_alt()))

    def _takeoff_tgt(self, sid, alt_s):
        if not self.fleet.connected:
            self._append_log('未连接：无法起飞')
            return
        try:
            alt = float(alt_s) if alt_s.strip() else float(self._tof_alt())
        except Exception:
            self._append_log('起飞高度无效：%s' % alt_s)
            return
        try:
            ok = self.fleet.takeoff(sid, alt)
            self._append_log('%s号机 起飞指令已发（%sm）' % (sid, alt)
                             if ok else '%s号机 起飞发送失败' % sid)
        except Exception as e:
            self._append_log('起飞失败：%s' % e)

    def _on_open_map(self):
        """打开高德卫星地图：继承主地图当前中心+缩放+校准（两图同步），点击取点"""
        mp = self._map_page
        center = (mp._center if mp else (34.26, 108.94))
        zoom = int(getattr(mp, '_zoom', 15) or 15)
        calib = getattr(mp, '_calib', None)
        gps_gcj = getattr(mp, 'gps_is_gcj', False)
        full = mapview.MapPage(center=center, zoom=zoom,
                               on_pick=self._on_map_pick,
                               on_close=lambda: self._map_popup.dismiss(),
                               gps_is_gcj=gps_gcj)
        if calib:
            full.set_calib(calib, note=getattr(mp, '_calib_from', ''))
        # 同步主地图的航点/飞机标记层（独立实例上叠加，打开即一致）
        try:
            layer = mapview._RouteLayer(full)
            layer.size_hint = (1, 1)
            if hasattr(self, '_map_route_layer'):
                layer.set_route(self._map_route_layer._route)
                layer.set_aircraft(self._map_route_layer._planes)
            full.add_widget(layer)
            self._full_layer = layer
        except Exception:
            pass
        self._map_popup = Popup(
            title='高德卫星地图 —— 点击任一点设为航点',
            content=full,
            size_hint=(0.98, 0.98))
        self._map_popup.open()

    def _on_map_pick(self, lat, lng):
        self._wp_lat.text = '%.6f' % lat
        self._wp_lon.text = '%.6f' % lng
        self._append_log('地图取点 %.6f, %.6f —— 填好高度后点「加航点」' % (lat, lng))
        try:
            self._map_popup.dismiss()
        except Exception:
            pass

    def _on_open_coord(self):
        CoordPopup(on_result=self._on_coord_result).open()

    def _on_coord_result(self, lat, lon):
        self._wp_lat.text = '%.6f' % lat
        self._wp_lon.text = '%.6f' % lon
        # 地图预览（直接定位到换算出的点）
        self._map_page._center = (lat, lon)
        self._map_page._zoom = max(self._map_page._zoom, 15)
        self._map_page._rebuild()
        self._append_log('坐标换算回填：北纬 %.6f 东经 %.6f —— 地图已定位到此点' % (lat, lon))

    # ---------------- 定位校准（领导法：两定点重叠） ----------------
    def _open_geo_calib(self, _x=None):
        # 功能导航⑨：同一位置取两对坐标——①地图点一下得到的「地理坐标」
        # ②您设备自定位的「直角坐标 X/Y」→ 相似变换，让地图标记与您的坐标重叠。
        self._calib_ui = {'disp': [None, None], 'pairs': [None, None]}
        popup = Popup(title='定位校准（两定点重叠）', size_hint=(0.95, 0.9), auto_dismiss=False)
        body = BoxLayout(orientation='vertical', spacing=8, padding=12)
        tip = Label(text='对同一位置：点「取点1」在地图上点一下 -> 记下识别坐标；\n再在下方填您设备的直角坐标 X/Y（米）并按「确认点1」。两点取完点「计算并启用」。',
                    font_size='14sp', halign='left', valign='top', text_size=(440, None), color=(0.85, 0.9, 0.85, 1))
        self._calib_status = Label(text='第1点：未取。第2点：未取。', font_size='16sp',
                                   halign='left', valign='middle', color=(0.6, 0.9, 0.6, 1))
        # 第1点
        r1a = BoxLayout(orientation='horizontal', spacing=6)
        b1_pick = RoundedButton(text='① 取点1（地图上点一下）', font_size='15sp',
                                background_color=ACCENT, radius='10dp')
        b1_ok = RoundedButton(text='确认点1', font_size='15sp', background_color=OK, radius='10dp')
        r1a.add_widget(b1_pick)
        r1a.add_widget(b1_ok)
        x1 = CompactTextInput(hint_text='X1 北向坐标(米)')
        y1 = CompactTextInput(hint_text='Y1 横坐标(可带带号)')
        z1 = CompactTextInput(hint_text='带号(可空自动判)')
        r1b = BoxLayout(orientation='horizontal', spacing=6)
        for w in (x1, y1, z1):
            w.size_hint_x = 1
            r1b.add_widget(w)
        # 第2点
        r2a = BoxLayout(orientation='horizontal', spacing=6)
        b2_pick = RoundedButton(text='② 取点2（地图上点一下）', font_size='15sp',
                                background_color=ACCENT, radius='10dp')
        b2_ok = RoundedButton(text='确认点2', font_size='15sp', background_color=OK, radius='10dp')
        r2a.add_widget(b2_pick)
        r2a.add_widget(b2_ok)
        x2 = CompactTextInput(hint_text='X2 北向坐标(米)')
        y2 = CompactTextInput(hint_text='Y2 横坐标(可带带号)')
        z2 = CompactTextInput(hint_text='带号(可空自动判)')
        r2b = BoxLayout(orientation='horizontal', spacing=6)
        for w in (x2, y2, z2):
            w.size_hint_x = 1
            r2b.add_widget(w)
        # 底部操作
        r3 = BoxLayout(orientation='horizontal', spacing=6)
        b_calc = RoundedButton(text='计算并启用', font_size='16sp', background_color=ACCENT, radius='10dp')
        b_clr = RoundedButton(text='清除校准', font_size='14sp', background_color=(0.55, 0.4, 0.4, 1), radius='10dp')
        b_close = RoundedButton(text='关闭', font_size='15sp', background_color=(0.5, 0.5, 0.5, 1), radius='10dp')
        r3.add_widget(b_calc)
        r3.add_widget(b_clr)
        r3.add_widget(b_close)
        b1_pick.bind(on_release=lambda _x: self._open_calib_map(0))
        b1_ok.bind(on_release=lambda _x: self._calib_confirm(0, x1, y1, z1))
        b2_pick.bind(on_release=lambda _x: self._open_calib_map(1))
        b2_ok.bind(on_release=lambda _x: self._calib_confirm(1, x2, y2, z2))
        b_calc.bind(on_release=lambda _x: self._calib_enable(popup))
        b_clr.bind(on_release=lambda _x: self._calib_clear(popup))
        b_close.bind(on_release=lambda _x: popup.dismiss())
        for w in (tip, self._calib_status, r1a, r1b, r2a, r2b, r3):
            body.add_widget(w)
        popup.content = body
        self._calib_popup = popup
        Clock.schedule_once(lambda *a: popup.open(), 0.05)
        self._append_log('定位校准：对同一位置取两定点（地图点1下+直角坐标X/Y），使标记与地图重叠')

    def _open_calib_map(self, idx):
        # 打开地图让领导点一下：识别出的坐标 = 该点的「地理坐标点」
        mp = self._map_page
        center = (mp._center if mp else (34.26, 108.94))
        self._calib_map_popup = Popup(
            title='取点%s —— 在地图上点一下实际位置' % ('1' if idx == 0 else '2'),
            content=mapview.MapPage(center=center, zoom=15,
                                    on_pick=lambda lat, lng: self._calib_pick(idx, lat, lng),
                                    on_close=lambda: self._calib_map_popup.dismiss()),
            size_hint=(0.98, 0.98))
        self._calib_map_popup.open()

    def _calib_pick(self, idx, lat, lng):
        self._calib_ui['disp'][idx] = (lat, lng)
        try:
            self._calib_map_popup.dismiss()
        except Exception:
            pass
        n = '1' if idx == 0 else '2'
        self._calib_status.text = '第%s点 地图坐标已取：%.6f, %.6f —— 请填直角坐标X/Y并按确认' % (n, lat, lng)
        self._append_log('校准点%s 地图识别坐标 %.6f, %.6f' % (n, lat, lng))

    def _calib_confirm(self, idx, xi, yi, zi):
        # 直角坐标X/Y（+带号）→ 经纬（CGCS2000 高斯六度带，同控制台）
        try:
            x = float(xi.text.strip())
        except Exception:
            self._calib_status.text = '第%s点 X 不是数字，请重填' % ('1' if idx == 0 else '2')
            return
        yraw = yi.text.strip()
        if not yraw:
            self._calib_status.text = '第%s点 Y 为空，请填写' % ('1' if idx == 0 else '2')
            return
        try:
            zone = int(zi.text.strip()) if zi.text.strip() else None
        except Exception:
            zone = None
        disp = self._calib_ui['disp'][idx]
        if disp is None:
            self._calib_status.text = '第%s点 还没取地图点，请先按「取点%d」' % ('1' if idx == 0 else '2', idx + 1)
            return
        try:
            glat, glon = gauss.zone_to_latlon(x, yraw, zone)
        except Exception as e:
            self._calib_status.text = '直角坐标换算失败：%s' % e
            return
        # 配对：([GPS纬度, GPS经度] <- 识别的[地图纬度, 地图经度])
        self._calib_ui['pairs'][idx] = (glat, glon, disp[0], disp[1])
        n = '1' if idx == 0 else '2'
        self._calib_status.text = '第%s点 已确认：直角→%.6f,%.6f / 地图 %.6f,%.6f' % (n, glat, glon, disp[0], disp[1])
        self._append_log('校准点%s 直角坐标换算 %.6f,%.6f（地图点 %.6f,%.6f）' % (n, glat, glon, disp[0], disp[1]))

    def _calib_enable(self, popup):
        pairs = self._calib_ui['pairs']
        if pairs[0] is None or pairs[1] is None:
            self._calib_status.text = '两点未取齐：请先完成第1、2点的地图取点和确认'
            return
        (g1lat, g1lon, d1lat, d1lon), (g2lat, g2lon, d2lat, d2lon) = pairs
        self._map_page.set_calib(pairs, note='手动')
        self._map_page._rebuild()
        # 持久化：下次开机自动应用
        self.cfg.setdefault('map', {})['calib'] = {'on': True, 'pts': [list(p) for p in pairs]}
        self._write_cfg()
        # 汇报偏差规模（米）：识别坐标与直角换算坐标的差，便于领导核对
        def _m(a, b):
            lm = 111320.0
            cm = lm * math.cos(math.radians(a[0]))
            return ((b[0] - a[0]) * lm) ** 2 + ((b[1] - a[1]) * cm) ** 2
        d_pt1 = _m((g1lat, g1lon), (d1lat, d1lon)) ** 0.5
        d_pt2 = _m((g2lat, g2lon), (d2lat, d2lon)) ** 0.5
        self._calib_status.text = '校准已启用（偏差点1≈%.0fm、点2≈%.0fm）。标记应与您的坐标重叠' % (d_pt1, d_pt2)
        self._append_log('定位校准已启用：两定点相似变换（平移+旋转+缩放），%s' %
                         ('偏差 点1≈%.0fm / 点2≈%.0fm' % (d_pt1, d_pt2)))
        try:
            popup.dismiss()
        except Exception:
            pass

    def _calib_clear(self, popup):
        self._map_page.clear_calib()
        self._map_page._rebuild()
        self.cfg.setdefault('map', {})['calib'] = {'on': False}
        self._write_cfg()
        self._calib_status.text = '校准已清除，恢复原始地图'
        self._append_log('定位校准已清除')

    def _write_cfg(self):
        # 把 cfg 写回手机内 config.yaml（与连接保存同款）
        try:
            if self._config_path and os.path.exists(self._config_path):
                import yaml
                with open(self._config_path, 'w', encoding='utf-8') as f:
                    yaml.safe_dump(self.cfg, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            self._append_log('  （配置保存失败：%s）' % e)

    # ---------------- 回调 ----------------
    def _sp_mode_all_mode(self):
        return self._parse_mode(self._sp_mode_all.text)

    def _sp_mode_one_mode(self):
        return self._parse_mode(self._sp_mode_one.text)

    def _parse_mode(self, text):
        try:
            return int(text[text.index('(') + 1:text.index(')')])
        except Exception:
            return 3

    def _on_mission_downloaded(self, sysid, items):
        if items:
            self._append_log('%s 任务 %d 条已下载' % (sysid, len(items)))
        else:
            self._append_log('%s 任务下载失败/超时' % sysid)
        self._refresh_mission_table()

    def _on_mission_uploaded(self, sysid, ok):
        self._append_log('%s 任务上传：%s' % (sysid, '成功' if ok else '失败'))
        if ok:
            self._refresh_mission_table()

    # ---------------- 连接 / 断开 ----------------
    def _on_connect(self, _x):
        host = self._host_in.text.strip()
        try:
            port = int(self._port_in.text)
        except Exception:
            self._append_log('端口无效')
            return
        if not host:
            self._append_log('服务器 IP 为空')
            return
        try:
            self.fleet.connect(host, port)
            self._btn_conn.text = '连接中…'
            Clock.schedule_once(lambda _t: setattr(self._btn_conn, 'text', '连接'), 1.2)
            self._append_log('正在连接 %s:%s…（连上后显示 在线 X/10）' % (host, port))
            # 持久化：把改过的服务器地址写回手机内 config.yaml（下次打开默认就是这个）
            if self._config_path and os.path.exists(self._config_path):
                try:
                    self.cfg.setdefault('server', {})
                    self.cfg['server']['host'] = host
                    self.cfg['server']['per_port_base'] = port
                    import yaml
                    with open(self._config_path, 'w', encoding='utf-8') as f:
                        yaml.safe_dump(self.cfg, f, allow_unicode=True, sort_keys=False)
                except Exception as e:
                    self._append_log('  （提示：地址未能保存，%s）' % e)
        except Exception as e:
            self._append_log('连接失败：%s' % e)

    def _on_disconnect(self, _x):
        self.fleet.disconnect()
        self._lbl_status.text = '状态：未连接'
        self._lbl_fm.text = '编队:关'
        self._lbl_fm.color = GRAY
        self._lbl_lock.text = '上锁'
        self._lbl_lock.color = GRAY
        self._refresh_satellites()
        self._refresh_mission_table()

    # ---------------- 定时刷新 ----------------
    def _tick(self, _dt):
        self.fleet.tick()
        n = self.fleet.online_count()
        total = len(self.fleet.fleet)
        conn = self.fleet.connected
        self._lbl_status.text = '状态：%s · 在线 %d/%d' % (
            '已连接' if conn else '未连接', n, total)
        self._lbl_status.color = OK if conn else GRAY
        # 飞机解锁/锁定（领导：状态栏最左边显示）
        armed = False
        for _s, _v in self.fleet.fleet.items():
            if _v.online:
                armed = _v.armed
                break
        self._lbl_lock.text = '解锁' if armed else '上锁'
        self._lbl_lock.color = DANGER if armed else (0.55, 0.8, 0.6, 1)
        self._refresh_satellites()
        self._refresh_single_state()
        self._refresh_map_aircraft()
        if self.fleet.connected and self._btn_conn.text != '断开':
            self._btn_conn.text = '断开'

    def _refresh_satellites(self):
        Clock.schedule_once(lambda _dt: self._refresh_satellites_impl(), 0)

    def _refresh_satellites_impl(self):
        """卫星行：10 机两行（5+5），每格上位机号+颗数、下位该机飞行模式"""
        sysids = sorted(self.fleet.fleet)
        if len(self._sat_box.children) != len(sysids):
            self._sat_box.clear_widgets()
            for s in sysids:
                blk = BoxLayout(orientation='vertical', spacing=0)
                top = BoxLayout(orientation='horizontal', spacing=1)
                lbl_id = Label(text='', font_size='13sp', bold=True)
                lbl_n = Label(text='', font_size='13sp')
                lbl_mode = Label(text='', font_size='12sp')
                blk.lbl_id = lbl_id
                blk.lbl_n = lbl_n
                blk.lbl_mode = lbl_mode
                top.add_widget(lbl_id)
                top.add_widget(lbl_n)
                blk.add_widget(top)
                blk.add_widget(lbl_mode)
                self._sat_box.add_widget(blk)
        for blk, s in zip(reversed(self._sat_box.children), sysids):
            v = self.fleet.fleet[s]
            lbl_id = blk.lbl_id
            lbl_n = blk.lbl_n
            lbl_mode = blk.lbl_mode
            lbl_id.text = str(s)
            lbl_n.text = '--'
            lbl_mode.text = '--'
            if v.online and v.satellites is not None:
                lbl_id.color = DANGER      # 机号：红（在线）
                lbl_n.text = str(v.satellites)
                lbl_n.color = OK           # 颗数：绿
            else:
                lbl_id.color = GRAY
                lbl_n.color = GRAY
            if v.online and v.mode is not None:
                lbl_mode.text = v.mode_zh
                lbl_mode.color = OK
            else:
                lbl_mode.color = GRAY

    def _refresh_single_state(self):
        Clock.schedule_once(lambda _dt: self._refresh_single_state_impl(), 0)

    def _refresh_single_state_impl(self):
        v = self.fleet.vehicle(self._sel_sysid())
        if v is None:
            self._lbl_veh.text = '未选择'
            return
        if not v.online:
            self._lbl_veh.text = '离线'
            self._lbl_veh.color = GRAY
            return
        parts = ['%s' % v.mode_zh]
        if v.rel_alt is not None:
            parts.append('高%gm' % int(v.rel_alt))
        if v.satellites is not None:
            parts.append('星%d' % v.satellites)
        if v.voltage is not None:
            parts.append('%.1fV' % v.voltage)
        parts.append('解锁' if v.armed else '上锁')
        self._lbl_veh.text = ' '.join(parts)
        self._lbl_veh.color = OK if v.armed else (0.9, 0.85, 0.75, 1)

    # ---------------- 通用 ----------------
    def _mk_btn(self, text, color, on_release, size_hint_x=1, height=BTN_H,
                radius='8dp', font_size='16sp', size_hint_y=None):
        b = RoundedButton(text=text, font_size=font_size,
                          background_color=color,
                          size_hint_y=size_hint_y, height=height,
                          size_hint_x=size_hint_x, radius=radius)
        # 统一安全护栏：回调先按「带参」试调，签名不收时退回无参；任何异常只写日志，
        # 绝不冒泡崩掉 App（领导反馈点按钮秒退 —— 护栏后任何回调异常都不可能再闪退）
        def _safe(*a):
            try:
                on_release(*a)
            except TypeError:
                try:
                    on_release()
                except Exception as e:
                    self._append_log('操作异常：%s' % e)
            except Exception as e:
                self._append_log('操作异常：%s' % e)
        b.bind(on_release=_safe)
        return b

    def _mk_hbox(self, widgets, height=INPUT_H):
        bx = BoxLayout(orientation='horizontal', spacing=6, size_hint_y=None, height=height)
        for w in widgets:
            bx.add_widget(w)
        return bx

    def _swarm_act(self, label, fn, *args):
        if not self.fleet.connected:
            self._append_log('未连接')
            return
        try:
            n = fn(*args)
            online = sum(1 for s in self.fleet.fleet
                         if getattr(self.fleet.fleet[s], 'online', False))
            if label.startswith('切自动'):
                self._append_log('全部切 AUTO：各机执行各自任务（%d 架；在线 %d/%d）'
                                 % (n, online, len(self.fleet.fleet)))
            else:
                self._append_log('全队%s：指令已发送 %d 架（在线 %d/%d）'
                                 % (label, n, online, len(self.fleet.fleet)))
        except Exception as e:
            self._append_log('全队%s 失败：%s' % (label, e))

    def _confirm(self, title, text, on_ok):
        ConfirmPopup(title=title, text=text, on_ok=on_ok).open()

    def _append_log(self, text):
        # 可能从 mavlink 网络线程回调进来 —— 必须调度到主线程再改控件，
        # 非主线程直接写 _lbl_log.text 是 Kivy 崩溃/闪退的根因
        Clock.schedule_once(lambda _dt: self._log_impl(text), 0)

    def _log_impl(self, text):
        self._log_text = (self._log_text + '\n' + text).strip()
        lines = self._log_text.split('\n')
        if len(lines) > 80:
            lines = lines[-80:]
            self._log_text = '\n'.join(lines)
        if hasattr(self, '_lbl_log'):
            self._lbl_log.text = self._log_text
        # ---- 操作使用记录：同步落盘（领导要求记录操作手机的使用记录）----
        # 每次操作以「时间 + 内容」追加到 用户数据目录/操作记录_<日期>.log，
        # 与 UI 日志区一致；写盘失败绝不打断界面/主流程。
        try:
            import time as _t
            _day = _t.strftime('%Y%m%d')
            _ts = _t.strftime('%H:%M:%S')
            _dir = App.get_running_app().user_data_dir
            _p = os.path.join(_dir, '操作记录_%s.log' % _day)
            with open(_p, 'a', encoding='utf-8') as _f:
                _f.write('[%s] %s\n' % (_ts, text))
        except Exception:
            pass

    def on_stop(self):
        try:
            self.fleet.disconnect()
        except Exception:
            pass


def main():
    # 电脑调试窗口按 16:9 比例打开（1280x720；手机真机运行时不影响）
    try:
        from kivy.utils import platform
        if platform != 'android':
            from kivy.core.window import Window
            Window.size = (1280, 720)   # Window.size 直接生效（Config.set 对已实例化 Config 无效）
    except Exception:
        pass
    SwarmMobileApp().run()


if __name__ == '__main__':
    main()