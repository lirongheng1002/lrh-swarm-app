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
from kivy.uix.gridlayout import GridLayout
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
        Window.softinput_mode = 'below_target'
        # 统一深色底：按钮圆角外/输入框周边不再是透明区外露（领导：消除透明框）
        Window.clearcolor = (0.08, 0.1, 0.12, 1)
        self._sel_seq = None          # 任务表选中 seq
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
        top = BoxLayout(orientation='vertical', size_hint_y=None, height='128dp', spacing=3)
        row1 = BoxLayout(orientation='horizontal', spacing=4, size_hint_y=None, height=INPUT_H)
        self._host_in = CompactTextInput(text=str(self.cfg.get('server', {}).get('host', '')),
                                         hint_text='服务器IP', size_hint_x=0.48,
                                         halign='center')
        self._port_in = CompactTextInput(text=str(self.cfg.get('server', {}).get('per_port_base', 15551)),
                                         hint_text='端口', input_filter='int',
                                         size_hint_x=0.16, halign='center')
        self._autocenter(self._host_in)
        self._autocenter(self._port_in)
        self._btn_conn = RoundedButton(text='连接', font_size='15sp',
                                       background_color=ACCENT,
                                       size_hint_x=0.18, radius='8dp')
        self._btn_conn.bind(on_release=self._on_connect)
        self._btn_disc = RoundedButton(text='断开', font_size='15sp',
                                       background_color=(0.55, 0.55, 0.55, 1),
                                       size_hint_x=0.18, radius='8dp')
        self._btn_disc.bind(on_release=self._on_disconnect)
        row1.add_widget(self._host_in)
        row1.add_widget(self._port_in)
        row1.add_widget(self._btn_conn)
        row1.add_widget(self._btn_disc)
        top.add_widget(row1)

        row2 = BoxLayout(orientation='horizontal', spacing=4, size_hint_y=None, height='34dp')
        self._lbl_lock = Label(text='上锁', font_size='15sp', halign='center',
                               valign='middle', size_hint_x=0.2, color=GRAY)
        self._lbl_status = Label(text='状态：未连接', font_size='15sp', halign='left',
                                 valign='middle', size_hint_x=0.44)
        self._lbl_fm = Label(text='编队:关', font_size='15sp', halign='center', valign='middle',
                             color=GRAY, size_hint_x=0.36)
        row2.add_widget(self._lbl_lock)
        row2.add_widget(self._lbl_status)
        row2.add_widget(self._lbl_fm)
        top.add_widget(row2)

        # 卫星行：10 机两行（5+5）GridLayout，间隔小、不左右滑（机号红/颗数绿见刷新方法）
        self._sat_box = GridLayout(cols=5, spacing=3, size_hint_y=None,
                                   height='46dp', padding=(4, 2))
        top.add_widget(self._sat_box)
        root.add_widget(top)

        # ---- 四栏导航（顶部按钮切页；不用 TabbedPanel——安卓上其 content 尺寸 bug
        #      导致切到第2栏后切不回/整页点不动，地图与航线窗口全无响应）----
        # ---- 四栏导航（顶部按钮切页；不用 TabbedPanel——安卓上其 content 尺寸 bug
        #      导致切到第2栏后切不回/整页点不动，地图与航线窗口全无响应）----
        # 导航栏固定在 root，不参与页面滚动；始终可点击。
        nav = BoxLayout(orientation='horizontal', spacing=6, size_hint_y=None,
                        height='46dp', padding=(2, 2))
        self._btn_p1 = RoundedButton(text='① 全部飞机', font_size='15sp',
                                     background_color=ACCENT, radius='10dp')
        self._btn_p2 = RoundedButton(text='② 单架飞机', font_size='15sp',
                                     background_color=(0.35, 0.35, 0.35, 1),
                                     radius='10dp')
        self._btn_p3 = RoundedButton(text='③ 任务航线', font_size='15sp',
                                     background_color=(0.35, 0.35, 0.35, 1),
                                     radius='10dp')
        self._btn_p4 = RoundedButton(text='④ 运行日志', font_size='15sp',
                                     background_color=(0.35, 0.35, 0.35, 1),
                                     radius='10dp')
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
        body2 = BoxLayout(orientation='vertical', spacing=6, padding=(2, 2))
        self._map_page = mapview.MapPage(center=self._map_default_center(),
                                         zoom=14, embedded=True,
                                         on_pick=self._on_map_pick_embed,
                                         on_double_tap=self._on_map_double_tap)
        self._map_page.size_hint_y = 0.52
        body2.add_widget(self._map_page)
        bottom = BoxLayout(orientation='vertical', spacing=1, size_hint_y=0.48)
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
        g.add_widget(self._mk_btn('切自动任务', ACCENT, lambda: self._swarm_act(
            '切自动', self.fleet.auto_all), font_size='15sp'))
        g.add_widget(self._mk_btn('全部切模式', ACCENT, self._on_all_mode_btn,
                                  font_size='15sp'))

        # 行3/行4（全队高度/全队速度）拆出网格成独立整行——见下方 wrap 内重建
        # （领导：输入框横向拉长铺满左右、无留白；间距收紧向上贴顶）

        wrap = BoxLayout(orientation='vertical', spacing=8,
                         size_hint_y=None, height='234dp')
        wrap.add_widget(g)
        # 上方功能按钮区与全队高度/速度行整体明显分开（领导：与上面任务栏不重叠）
        wrap.add_widget(Label(text='', size_hint_y=None, height='28dp'))
        # 蓝色圆角毛玻璃框：全队高度 + 全队速度 两行整体框起（领导）
        bfm = GlassPanel(orientation='vertical', spacing=8, padding=(10, 8),
                         size_hint_y=None, height='104dp',
                         bg=(0.25, 0.45, 0.85, 0.16), border=(0.4, 0.65, 1, 0.6),
                         radius='12dp')
        # 行3：全队高度——输入框横拉铺满（领导：与按钮同高40dp）
        r3 = BoxLayout(orientation='horizontal', spacing=8, size_hint_y=None, height='40dp')
        r3.add_widget(Label(text='全队高度', font_size='14sp', size_hint_x=0.14,
                            halign='left', valign='middle', color=(0.85, 0.85, 0.85, 1)))
        self._fm_alt = CompactTextInput(text='30', input_filter='float', font_size='18sp',
                                        size_hint_x=0.52, size_hint_y=None,
                                        height='40dp', halign='center')
        r3.add_widget(self._fm_alt)
        # 单位 m：灰色毛玻璃小框（领导：单位用灰框）
        gm = GlassPanel(orientation='horizontal', size_hint_x=0.08, size_hint_y=None,
                        height='40dp', padding=(2, 0), spacing=0,
                        bg=(0.6, 0.62, 0.66, 0.16), border=(0.6, 0.62, 0.66, 0.5),
                        radius='8dp', border_width='1dp')
        gm.add_widget(Label(text='m', font_size='14sp', halign='center',
                            valign='middle', color=(0.75, 0.75, 0.75, 1)))
        r3.add_widget(gm)
        r3.add_widget(self._mk_btn('确定', OK, self._on_confirm_fm_alt,
                                   size_hint_x=0.2, font_size='14sp', height='40dp'))
        r3.add_widget(Label(text='', size_hint_x=0.06))
        bfm.add_widget(r3)
        # 行4：全队速度——独立整行
        r4 = BoxLayout(orientation='horizontal', spacing=8, size_hint_y=None, height='40dp')
        r4.add_widget(Label(text='全队速度', font_size='14sp', size_hint_x=0.14,
                            halign='left', valign='middle', color=(0.85, 0.85, 0.85, 1)))
        self._spd_all = CompactTextInput(text='10', input_filter='float', font_size='18sp',
                                         size_hint_x=0.52, size_hint_y=None,
                                         height='40dp', halign='center')
        r4.add_widget(self._spd_all)
        # 单位 m/s：灰色毛玻璃小框
        gms = GlassPanel(orientation='horizontal', size_hint_x=0.08, size_hint_y=None,
                         height='40dp', padding=(2, 0), spacing=0,
                         bg=(0.6, 0.62, 0.66, 0.16), border=(0.6, 0.62, 0.66, 0.5),
                         radius='8dp', border_width='1dp')
        gms.add_widget(Label(text='m/s', font_size='13sp', halign='center',
                             valign='middle', color=(0.75, 0.75, 0.75, 1)))
        r4.add_widget(gms)
        r4.add_widget(self._mk_btn('发送', OK, self._on_confirm_speed_all,
                                   size_hint_x=0.2, font_size='14sp', height='40dp'))
        r4.add_widget(Label(text='', size_hint_x=0.06))
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
        gr2 = GlassPanel(orientation='horizontal', spacing=8, padding=(10, 6),
                         size_hint_y=None, height='52dp',
                         bg=(0.25, 0.45, 0.85, 0.16), border=(0.4, 0.65, 1, 0.6),
                         radius='12dp')
        r2 = BoxLayout(orientation='horizontal', spacing=8, size_hint_y=None, height='40dp')
        r2.add_widget(Label(text='前后/左右/小组m', font_size='13sp', size_hint_x=0.24,
                            halign='left', valign='middle'))
        r2.add_widget(CompactTextInput(text=str(self.cfg['formation'].get('spacing_f', 5)),
                                       input_filter='float', font_size='18sp', size_hint_x=0.2))
        r2.add_widget(CompactTextInput(text=str(self.cfg['formation'].get('spacing_l', 5)),
                                       input_filter='float', font_size='18sp', size_hint_x=0.2))
        r2.add_widget(CompactTextInput(text=str(self.cfg['formation'].get('spacing_g', 10)),
                                       input_filter='float', font_size='18sp', size_hint_x=0.2))
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
        top = GlassPanel(orientation='horizontal', spacing=8, padding=(10, 4),
                         size_hint_y=None, height='40dp',
                         bg=(0.25, 0.45, 0.85, 0.16), border=(0.4, 0.65, 1, 0.6),
                         radius='12dp')
        self._sp_sys = Spinner(text='1号机', values=['%d号机' % i for i in range(1, 11)],
                               font_size='16sp', size_hint_x=0.36)
        self._sp_sys.bind(text=self._on_sys_changed)
        self._lbl_veh = Label(text='未选择', font_size='15sp', halign='left',
                              valign='middle', size_hint_x=0.64)
        top.add_widget(self._sp_sys)
        top.add_widget(self._lbl_veh)
        b.add_widget(Label(text='二、单机操作', font_size='18sp', bold=True,
                           color=(0.18, 0.4, 0.72, 1), size_hint_y=None, height='22dp',
                           halign='left', valign='middle'))
        b.add_widget(top)
        spc = BoxLayout(size_hint_y=None, height='6dp')
        b.add_widget(spc)

        # （领导：删占位空白——全部控件上移贴紧，不留大片空白）

        # 控制按钮区（2 列 3 行）
        gwrap = BoxLayout(orientation='vertical', spacing=2, size_hint_y=None, height='174dp')
        g = GridLayout(cols=2, spacing=6, size_hint_y=None, height='132dp')
        g.add_widget(self._mk_btn('单机起飞', OK, lambda: self._confirm(
            '单机起飞', '%s 按 %s m 起飞？' % (self._sel_name(), self._tof_alt()),
            lambda: self._single_act('起飞', self.fleet.takeoff, self._tof_alt())),
            font_size='17sp', height='40dp', radius='16dp'))
        g.add_widget(self._mk_btn('单机降落', OK, lambda: self._confirm(
            '单机降落', '%s 立即降落？' % self._sel_name(),
            lambda: self._single_act('降落', self.fleet.land)),
            font_size='17sp', height='40dp', radius='16dp'))
        g.add_widget(self._mk_btn('单机解锁', ACCENT, lambda: self._confirm(
            '单机解锁', '%s 解锁？' % self._sel_name(),
            lambda: self._single_act('解锁', self.fleet.arm, True)),
            font_size='17sp', height='40dp', radius='16dp'))
        g.add_widget(self._mk_btn('单机上锁', ACCENT, lambda: self._confirm(
            '单机上锁', '%s 上锁（仅地面）？' % self._sel_name(),
            lambda: self._single_act('上锁', self.fleet.arm, False)),
            font_size='17sp', height='40dp', radius='16dp'))
        g.add_widget(self._mk_btn('单机返航', DANGER, lambda: self._confirm(
            '单机返航', '%s 返航 RTL？' % self._sel_name(),
            lambda: self._single_act('返航', self.fleet.rtl)),
            font_size='17sp', height='40dp', radius='16dp'))
        g.add_widget(self._mk_btn('单机投弹', DANGER, lambda: self._confirm(
            '单机投弹', '%s 投弹（舵机6 PWM2000）？' % self._sel_name(),
            lambda: self._single_act('投弹', self.fleet.bomb)),
            font_size='17sp', height='40dp', radius='16dp'))
        gwrap.add_widget(g)

        # 底部固定：本机切模式（醒目蓝色大按钮，始终可点；前面无占位空白）
        # 模式开关组：本机全部切模式控件统一归置（切自动/悬停/接自动 一行平铺，始终可点）
        r4 = GridLayout(cols=2, spacing=6, size_hint_y=None, height='40dp')
        r4.add_widget(self._mk_btn('自动', (0.95, 0.72, 0.34, 1), self._on_single_auto,
                                   size_hint_x=0.5, font_size='14sp', height='40dp',
                                   radius='16dp'))
        r4.add_widget(self._mk_btn('悬停', (0.95, 0.72, 0.34, 1), self._on_single_loiter,
                                   size_hint_x=0.5, font_size='14sp', height='40dp',
                                   radius='16dp'))
        gwrap.add_widget(r4)
        b.add_widget(gwrap)
        # 本机高度/本机速度——蓝色圆角毛玻璃框（同①页全队行）+ m/m/s 灰色小毛玻璃框
        bpar = GlassPanel(orientation='vertical', spacing=6, padding=(10, 4),
                          size_hint_y=None, height='104dp',
                          bg=(0.25, 0.45, 0.85, 0.16), border=(0.4, 0.65, 1, 0.6),
                          radius='12dp')
        rh = BoxLayout(orientation='horizontal', spacing=8, size_hint_y=None, height='40dp')
        rh.add_widget(Label(text='本机高度', font_size='14sp', size_hint_x=0.14,
                            halign='left', valign='middle', color=(0.85, 0.85, 0.85, 1)))
        self._alt_one = CompactTextInput(text='30', input_filter='float', font_size='18sp',
                                         size_hint_x=0.52, size_hint_y=None,
                                         height='40dp', halign='center')
        rh.add_widget(self._alt_one)
        gm2 = GlassPanel(orientation='horizontal', size_hint_x=0.08, size_hint_y=None,
                         height='40dp', padding=(2, 0), spacing=0,
                         bg=(0.6, 0.62, 0.66, 0.16), border=(0.6, 0.62, 0.66, 0.5),
                         radius='8dp', border_width='1dp')
        gm2.add_widget(Label(text='m', font_size='14sp', halign='center',
                             valign='middle', color=(0.75, 0.75, 0.75, 1)))
        rh.add_widget(gm2)
        rh.add_widget(self._mk_btn('确认', OK, self._on_confirm_alt_one,
                                   size_hint_x=0.2, font_size='14sp', height='40dp'))
        rh.add_widget(Label(text='', size_hint_x=0.06))
        bpar.add_widget(rh)
        rs = BoxLayout(orientation='horizontal', spacing=8, size_hint_y=None, height='40dp')
        rs.add_widget(Label(text='本机速度', font_size='14sp', size_hint_x=0.14,
                            halign='left', valign='middle', color=(0.85, 0.85, 0.85, 1)))
        self._spd_one = CompactTextInput(text='5', input_filter='float', font_size='18sp',
                                         size_hint_x=0.52, size_hint_y=None,
                                         height='40dp', halign='center')
        rs.add_widget(self._spd_one)
        gms2 = GlassPanel(orientation='horizontal', size_hint_x=0.08, size_hint_y=None,
                          height='40dp', padding=(2, 0), spacing=0,
                          bg=(0.6, 0.62, 0.66, 0.16), border=(0.6, 0.62, 0.66, 0.5),
                          radius='8dp', border_width='1dp')
        gms2.add_widget(Label(text='m/s', font_size='12sp', halign='center',
                              valign='middle', color=(0.75, 0.75, 0.75, 1)))
        rs.add_widget(gms2)
        rs.add_widget(self._mk_btn('确认', OK, self._on_confirm_speed_one,
                                   size_hint_x=0.2, font_size='14sp', height='40dp'))
        rs.add_widget(Label(text='', size_hint_x=0.06))
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
        b = GlassPanel(orientation='vertical', spacing=4, size_hint_y=None,
                       height='180dp', padding=(8, 2), bg=(0.25, 0.45, 0.85, 0.16),
                       border=(0.4, 0.65, 1, 0.6), radius='12dp')
        # 目标机行：航点/任务都发给这架（领导：加航点必须明确是几号机）
        rt = BoxLayout(orientation='horizontal', spacing=5, size_hint_y=None, height='40dp')
        self._sp_tgt = Spinner(text='1号机', values=['%d号机' % i for i in range(1, 11)],
                               font_size='15sp', size_hint_x=0.25)
        rt.add_widget(self._sp_tgt)
        self._wp_lat = CompactTextInput(hint_text='纬度', input_filter='float',
                                        size_hint_x=0.25, halign='center')
        self._wp_lon = CompactTextInput(hint_text='经度', input_filter='float',
                                        size_hint_x=0.25, halign='center')
        self._wp_alt = CompactTextInput(hint_text='高度m', input_filter='float',
                                        size_hint_x=0.25, halign='center')
        rt.add_widget(self._wp_lat)
        rt.add_widget(self._wp_lon)
        rt.add_widget(self._wp_alt)
        b.add_widget(rt)

        # 功能按钮 4 等份：全屏地图/坐标换算/加航点/插投弹（加航点在全屏地图下方、插投弹在坐标换算下方）
        r3 = GridLayout(cols=2, spacing=4, size_hint_y=None, height='84dp',
                        padding=(0, 0))
        r3.add_widget(self._mk_btn('全屏地图', (0.15, 0.6, 0.35, 1),
                                   self._on_open_map, font_size='15sp',
                                   height='40dp'))
        r3.add_widget(self._mk_btn('坐标换算', (0.55, 0.4, 0.2, 1),
                                   self._on_open_coord, font_size='15sp',
                                   height='40dp'))
        r3.add_widget(self._mk_btn('加航点', ACCENT, self._on_add_wp,
                                   font_size='15sp', height='40dp'))
        r3.add_widget(self._mk_btn('插投弹', DANGER, self._on_add_bomb,
                                   font_size='15sp', height='40dp'))
        b.add_widget(r3)

        # 最底行：下载任务 / 上传任务 / 读取航线 / 读取航点 / 清除任务
        r1 = BoxLayout(orientation='horizontal', spacing=5,
                       size_hint_y=None, height='40dp')
        r1.add_widget(self._mk_btn('下载任务', ACCENT, self._on_download_mission,
                                   size_hint_x=0.2, font_size='13sp', height='40dp'))
        r1.add_widget(self._mk_btn('上传任务', ACCENT, lambda: self._confirm(
            '上传任务', '把当前任务（%d 条）写入 %s？' % (self._mission_len(), self._sel_name()),
            self._on_upload_mission), size_hint_x=0.2, font_size='13sp', height='40dp'))
        r1.add_widget(self._mk_btn('读取航线', ACCENT, self._on_read_route,
                                   size_hint_x=0.2, font_size='13sp', height='40dp'))
        r1.add_widget(self._mk_btn('读取航点', ACCENT, self._on_read_wp,
                                   size_hint_x=0.2, font_size='13sp', height='40dp'))
        r1.add_widget(self._mk_btn('清除任务', GRAY, self._on_clear_mission,
                                   size_hint_x=0.2, font_size='13sp', height='40dp'))
        b.add_widget(r1)

        # 任务表（移到最底，不打断中部三处均匀间距）
        self._mission_scroll = ScrollView(size_hint_y=None, height='4dp')
        self._mission_box = BoxLayout(orientation='vertical', spacing=2,
                                      size_hint_y=None)
        self._mission_box.bind(minimum_height=self._mission_box.setter('height'))
        self._mission_scroll.add_widget(self._mission_box)
        b.add_widget(self._mission_scroll)
        return b

    def _mission_len(self):
        v = self.fleet.vehicle(self._sel_sysid())
        return len(v.mission) if v else 0

    def _refresh_mission_table(self):
        # 可能从网络线程（任务下载/上传回调）触发 —— 同样调度到主线程
        Clock.schedule_once(lambda _dt: self._refresh_mission_table_impl(), 0)

    def _refresh_mission_table_impl(self):
        v = self.fleet.vehicle(self._mission_sysid())
        rows = v.mission if v else []
        self._mission_box.clear_widgets()
        sel = self._sel_seq
        for it in rows:
            cmd = vehicles.MAV_CMD_ZH.get(it['cmd'], 'M%g' % it['cmd'])
            pos = '' if it['cmd'] == 184 else ' %.6f,%.6f %sm' % (it['lat'], it['lon'], it['alt'])
            txt = '#%d %s%s' % (it['seq'], cmd, pos)
            row = RoundedButton(
                text=txt, font_size='14sp', height='34dp', size_hint_y=None,
                background_color=(0.35, 0.5, 0.35, 1) if sel == it['seq'] else
                                 (0.25, 0.3, 0.38, 1),
                radius='6dp')
            row.bind(on_release=lambda _x, s=it['seq']: self._on_mission_row(s))
            self._mission_box.add_widget(row)
        if not rows:
            self._mission_box.add_widget(Label(text='（任务为空——下载或设置航点）',
                                               font_size='14sp', height='30dp', size_hint_y=None))

    def _on_mission_row(self, seq):
        self._sel_seq = seq
        self._refresh_mission_table()

    def _on_download_mission(self, _x):
        if not self.fleet.connected:
            self._append_log('未连接')
            return
        self._append_log('正在下载 %s 任务…' % self._sel_name())
        self.fleet.download_mission(self._mission_sysid())

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
        if not self.fleet.connected:
            self._append_log('未连接')
            return
        self.fleet.clear_mission(self._mission_sysid())
        self._refresh_mission_table()

    def _mission_sysid(self):
        """③页目标机号（航点/任务操作对象，默认 1 号机）"""
        try:
            return int(self._sp_tgt.text.replace('号机', ''))
        except Exception:
            return 1

    def _on_add_wp(self, _x):
        try:
            lat = float(self._wp_lat.text)
            lon = float(self._wp_lon.text)
            alt = float(self._wp_alt.text)
        except Exception:
            self._append_log('加航点失败：纬度/经度/高度未填全')
            return
        sid = self._mission_sysid()
        self.fleet.append_waypoint(sid, lat, lon, alt)
        self._refresh_mission_table()
        self._append_log('%s号机 已加航点 (%.6f, %.6f, %sm)——点「上传任务」写入飞机' % (
            sid, lat, lon, alt))

    def _on_add_bomb(self, _x):
        if self._sel_seq is None:
            self._append_log('请先在任务表点选一个航点，再「插投弹」')
            return
        self.fleet.add_bomb_after(self._mission_sysid(), self._sel_seq)
        self._refresh_mission_table()

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
        """内嵌地图取点：直接回填经纬（常显，不关闭）"""
        self._wp_lat.text = '%.6f' % lat
        self._wp_lon.text = '%.6f' % lng
        self._append_log('地图取点 %.6f, %.6f —— 填好高度后点「加航点」' % (lat, lng))

    def _on_map_double_tap(self, lat, lng):
        """地图双击：弹出任务菜单（投弹/清空航线/返航）——类似电脑端右键"""
        sid = self._mission_sysid()
        popup = Popup(title='任务菜单 · %s号机' % sid, size_hint=(0.88, 0.52),
                      auto_dismiss=True)
        box = BoxLayout(orientation='vertical', spacing=8, padding=12)
        box.add_widget(self._mk_btn('投弹（%s号机追加投弹点）' % sid, DANGER,
                                    lambda: self._bomb_double_tap(sid, popup),
                                    size_hint_y=None, height='50dp', font_size='16sp'))
        box.add_widget(self._mk_btn('清空航线（%s号机）' % sid, GRAY,
                                    lambda: self._clear_double_tap(sid, popup),
                                    size_hint_y=None, height='50dp', font_size='16sp'))
        box.add_widget(self._mk_btn('返航 RTL（%s号机）' % sid, ACCENT,
                                    lambda: self._rtl_double_tap(sid, popup),
                                    size_hint_y=None, height='50dp', font_size='16sp'))
        popup.content = box
        Clock.schedule_once(lambda *a: popup.open(), 0.05)
        self._append_log('地图双击：%s号机 任务菜单（%.5f, %.5f）' % (sid, lat, lng))

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

    def _clear_double_tap(self, sid, popup):
        popup.dismiss()
        self._confirm('清空航线', '清除 %s号机全部任务航点？' % sid,
                      lambda: self._clear_mission_tgt(sid))

    def _clear_mission_tgt(self, sid):
        if not self.fleet.connected:
            self._append_log('未连接：无法清空航线')
            return
        self.fleet.clear_mission(sid)
        self._refresh_mission_table()
        self._append_log('%s号机 航线已清空' % sid)

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

    def _on_open_map(self):
        """打开高德卫星地图：以首架在线机（或默认）为中心，点击取点"""
        center = (34.26, 108.94)
        for s in sorted(self.fleet.fleet):
            v = self.fleet.fleet[s]
            lat = getattr(v, 'lat', None)
            lon = getattr(v, 'lon', None)
            if v.online and lat and lon and lat != 0:
                center = (lat, lon)
                break
        self._map_popup = Popup(
            title='高德卫星地图 —— 点击任一点设为航点',
            content=mapview.MapPage(center=center, zoom=15,
                                    on_pick=self._on_map_pick,
                                    on_close=lambda: self._map_popup.dismiss()),
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
        self._append_log('坐标换算回填：北纬 %.6f 东经 %.6f —— 填好高度后点「加航点」' % (lat, lon))

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
        if self.fleet.connected and self._btn_conn.text != '断开':
            self._btn_conn.text = '断开'

    def _refresh_satellites(self):
        Clock.schedule_once(lambda _dt: self._refresh_satellites_impl(), 0)

    def _refresh_satellites_impl(self):
        sysids = sorted(self.fleet.fleet)
        if len(self._sat_box.children) != len(sysids):
            self._sat_box.clear_widgets()
            for s in sysids:
                blk = BoxLayout(orientation='horizontal', spacing=1)
                lbl_id = Label(text='', font_size='13sp', bold=True)
                lbl_n = Label(text='', font_size='13sp')
                blk.lbl_id = lbl_id
                blk.lbl_n = lbl_n
                blk.add_widget(lbl_id)
                blk.add_widget(lbl_n)
                self._sat_box.add_widget(blk)
        for blk, s in zip(reversed(self._sat_box.children), sysids):
            v = self.fleet.fleet[s]
            lbl_id = blk.lbl_id
            lbl_n = blk.lbl_n
            lbl_id.text = str(s)
            lbl_n.text = '--'
            if v.online and v.satellites is not None:
                lbl_id.color = DANGER      # 机号：红（在线）
                lbl_n.text = str(v.satellites)
                lbl_n.color = OK           # 颗数：绿
            else:
                lbl_id.color = GRAY
                lbl_n.color = GRAY

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

    def on_stop(self):
        try:
            self.fleet.disconnect()
        except Exception:
            pass


def main():
    SwarmMobileApp().run()


if __name__ == '__main__':
    main()