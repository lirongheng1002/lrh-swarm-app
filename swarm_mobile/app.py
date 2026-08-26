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
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from . import fleet as fleetmod
from . import mapview
from .core import vehicles, commands, missions, formation, gauss, config as cfgmod

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
        b_cancel = Button(text='取消', font_size='17sp')
        b_ok = Button(text='确定执行', font_size='17sp', background_color=DANGER)
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
        self._in_x = TextInput(hint_text='X（北向坐标，米）', font_size='17sp',
                               multiline=False, input_filter='float')
        self._in_y = TextInput(hint_text='Y（横坐标：(19)406840 / 19406840 / 406840）',
                               font_size='17sp', multiline=False)
        self._in_z = TextInput(hint_text='带号（可选，缺省自动判）', font_size='17sp',
                               multiline=False, input_filter='int')
        self._lbl_res = Label(text='等待输入坐标…', font_size='16sp', halign='left',
                              valign='middle', color=(0.4, 0.85, 0.6, 1))
        rowb = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=BTN_H)
        b_calc = Button(text='换算', font_size='17sp', background_color=ACCENT)
        b_apply = Button(text='设为航点', font_size='17sp', background_color=OK)
        b_close = Button(text='关闭', font_size='17sp')
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
        # 顶部压缩（领导要求：连接/断开放一行，顶栏缩小给页面让空间）
        top = BoxLayout(orientation='vertical', size_hint_y=None, height='108dp', spacing=3)
        row1 = BoxLayout(orientation='horizontal', spacing=6, size_hint_y=None, height=INPUT_H)
        self._host_in = TextInput(text=str(self.cfg.get('server', {}).get('host', '')),
                                  hint_text='服务器IP 如112.124.6.186',
                                  font_size='17sp', multiline=False, size_hint_x=0.62)
        self._port_in = TextInput(text=str(self.cfg.get('server', {}).get('per_port_base', 15551)),
                                  hint_text='端口', font_size='17sp', multiline=False,
                                  input_filter='int', size_hint_x=0.18)
        self._btn_conn = Button(text='连接', font_size='17sp', background_color=ACCENT, size_hint_x=0.2)
        self._btn_conn.bind(on_release=self._on_connect)
        row1.add_widget(self._host_in)
        row1.add_widget(self._port_in)
        row1.add_widget(self._btn_conn)
        top.add_widget(row1)

        row2 = BoxLayout(orientation='horizontal', spacing=6, size_hint_y=None, height='36dp')
        self._lbl_status = Label(text='状态：未连接', font_size='17sp', halign='left',
                                 valign='middle', size_hint_x=0.56)
        self._lbl_fm = Label(text='编队:关', font_size='16sp', halign='center', valign='middle',
                             color=GRAY, size_hint_x=0.22)
        self._btn_disc = Button(text='断开', font_size='16sp', size_hint_x=0.22)
        self._btn_disc.bind(on_release=self._on_disconnect)
        row2.add_widget(self._lbl_status)
        row2.add_widget(self._lbl_fm)
        row2.add_widget(self._btn_disc)
        top.add_widget(row2)

        self._sat_scroll = ScrollView(size_hint=(1, 1), do_scroll_y=False)
        self._sat_box = BoxLayout(orientation='horizontal', spacing=6,
                                  size_hint_x=None, padding=(4, 2))
        top.add_widget(self._sat_scroll)
        self._sat_scroll.add_widget(self._sat_box)
        root.add_widget(top)

        # ---- 四栏导航（顶部按钮切页；不用 TabbedPanel——安卓上其 content 尺寸 bug
        #      导致切到第2栏后切不回/整页点不动，地图与航线窗口全无响应）----
        nav = BoxLayout(orientation='horizontal', spacing=4, size_hint_y=None, height='44dp')
        self._btn_p1 = Button(text='① 全部飞机', font_size='15sp', background_color=ACCENT)
        self._btn_p2 = Button(text='② 单架飞机', font_size='15sp')
        self._btn_p3 = Button(text='③ 任务航线', font_size='15sp')
        self._btn_p4 = Button(text='④ 运行日志', font_size='15sp')
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
        body0 = BoxLayout(orientation='vertical', spacing=8, padding=(4, 4),
                          size_hint_y=None)
        body0.bind(minimum_height=body0.setter('height'))
        body0.add_widget(self._section_title('一、全队操作', (0.18, 0.4, 0.72, 1)))
        body0.add_widget(self._build_fleet_ops())
        body0.add_widget(self._section_title('二、队形编队', (0.18, 0.4, 0.72, 1)))
        body0.add_widget(self._build_formation())
        sv0.add_widget(body0)

        # ---- 页② 单架飞机：内容量小，直接 BoxLayout 铺满（不套外层 ScrollView，
        #      彻底避开安卓页面级滚动布局黑屏/空白）----
        body1 = BoxLayout(orientation='vertical', spacing=8, padding=(6, 6))
        body1.add_widget(self._section_title('单机操作（选机/起飞/降落/解锁/上锁/返航/投弹/切模式）',
                                            (0.18, 0.4, 0.72, 1)))
        body1.add_widget(self._build_single())

        # ---- 页③ 任务航线：同②，直接 BoxLayout 铺满（任务表 200dp 滚动保留为唯一内层）----
        body2 = BoxLayout(orientation='vertical', spacing=8, padding=(6, 6))
        body2.add_widget(self._section_title('任务航线（下载/上传/地图设点/坐标换算/航点）',
                                            (0.18, 0.4, 0.72, 1)))
        body2.add_widget(self._build_mission())

        # ---- 页③ 运行日志（单独一栏，长按可选中复制 + 清空）----
        logbox3 = BoxLayout(orientation='vertical', spacing=6, padding=(4, 4))
        self._lbl_log = TextInput(text='', readonly=True, font_size='15sp',
                                  background_color=(0.12, 0.14, 0.12, 1),
                                  foreground_color=(0.75, 0.85, 0.75, 1),
                                  cursor_color=(0.9, 0.95, 0.9, 1), multiline=True)
        b_clear = Button(text='清空日志', font_size='16sp', size_hint_y=None, height=INPUT_H)
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

    def _clear_log(self):
        self._log_text = ''
        self._lbl_log.text = ''

    def _section_title(self, text, color):
        return Label(text=text, font_size='18sp', bold=True, color=color,
                     size_hint_y=None, height='32dp', halign='left', valign='middle')

    def _h_cell(self, btn):
        return btn

    # ---------------- 一、全队操作 ----------------
    def _build_fleet_ops(self):
        g = GridLayout(cols=2, spacing=6, size_hint_y=None, height='380dp')
        g.add_widget(self._mk_btn('全部解锁', DANGER, lambda: self._confirm(
            '全部解锁', '对全部 N 架机执行解锁（ARM）？\n确认飞机已就位、无人在桨区内。',
            lambda: self._swarm_act('解锁', self.fleet.arm_all, True))))
        g.add_widget(self._mk_btn('全部上锁', DANGER, lambda: self._confirm(
            '全部上锁', '对全部在线机执行上锁（DISARM）？\n仅应在地面执行。',
            lambda: self._swarm_act('上锁', self.fleet.arm_all, False))))
        g.add_widget(self._mk_btn('全部起飞', OK, lambda: self._confirm(
            '全部起飞', '全部 N 架按高度 %s m 同时起飞？' % self._tof_alt(),
            lambda: self._swarm_act('起飞', self.fleet.takeoff_all, self._tof_alt()))))
        g.add_widget(self._mk_btn('全部降落', DANGER, lambda: self._confirm(
            '全部降落', '全部 N 架立即降落（LAND）？',
            lambda: self._swarm_act('降落', self.fleet.land_all))))
        g.add_widget(self._mk_btn('全部返航', DANGER, lambda: self._confirm(
            '全部返航', '全部 N 架返航（RTL）回各自起飞点？',
            lambda: self._swarm_act('返航', self.fleet.rtl_all))))
        g.add_widget(self._mk_btn('全部投弹', DANGER, lambda: self._confirm(
            '全部投弹', '对全部 N 架同时发投弹指令（舵机6 PWM2000）？',
            lambda: self._swarm_act('投弹', self.fleet.bomb_all))))
        g.add_widget(self._mk_btn('全部切自动·各自任务', ACCENT, lambda: self._swarm_act(
            '切自动', self.fleet.auto_all)))
        mrow = BoxLayout(orientation='horizontal', spacing=6, size_hint_y=None, height=INPUT_H)
        self._sp_mode_all = Spinner(text='自动(3)', values=MODE_SPINNER_VALUES,
                                    font_size='16sp', size_hint_x=0.6)
        b = self._mk_btn('全部切模式', ACCENT, lambda: self._swarm_act(
            '切模式', self.fleet.set_mode_all, self._sp_mode_all_mode(),
            label='切模式→%s' % self._sp_mode_all.text))
        mrow.add_widget(self._sp_mode_all)
        mrow.add_widget(b)
        g.add_widget(mrow)
        # 起飞高度输入（放在最后一格）
        g.add_widget(self._mk_hbox([Label(text='起飞高度m', font_size='15sp',
                                          size_hint_x=0.5),
                                    self._alt_tof_in()]))
        return g

    def _alt_tof_in(self):
        self._tof = TextInput(text='20', font_size='17sp', multiline=False,
                              input_filter='float', size_hint_x=0.5)
        return self._tof

    def _tof_alt(self):
        try:
            return float(self._tof.text)
        except Exception:
            return 20.0

    # ---------------- 二、队形编队 ----------------
    def _build_formation(self):
        b = BoxLayout(orientation='vertical', spacing=6, size_hint_y=None)
        b.add_widget(self._mk_hbox([
            Label(text='全队高度m', font_size='15sp', size_hint_x=0.3),
            self._fm_alt_in(),
            self._mk_btn('开始编队', OK, self._on_formation_start, size_hint_x=0.2),
            self._mk_btn('暂停编队', DANGER, self._on_formation_stop, size_hint_x=0.2),
        ]))
        b.add_widget(self._mk_hbox([
            Label(text='前/左右/小组 m', font_size='15sp', size_hint_x=0.44),
            TextInput(text=str(self.cfg['formation'].get('spacing_f', 5)), font_size='16sp',
                      multiline=False, input_filter='float', size_hint_x=0.18),
            TextInput(text=str(self.cfg['formation'].get('spacing_l', 5)), font_size='16sp',
                      multiline=False, input_filter='float', size_hint_x=0.18),
            TextInput(text=str(self.cfg['formation'].get('spacing_g', 10)), font_size='16sp',
                      multiline=False, input_filter='float', size_hint_x=0.2),
        ]))
        presets = ['一字横排', '人字形', '前三角', '后三角', '梯形', '三角群']
        pg = GridLayout(cols=3, spacing=6, size_hint_y=None, height='110dp')
        for name in presets:
            pg.add_widget(self._mk_btn(name, (0.3, 0.3, 0.35, 1),
                                       lambda n=name: self._on_preset(n), height='40dp'))
        b.add_widget(pg)
        return b

    def _fm_alt_in(self):
        self._fm_alt = TextInput(text='30', font_size='17sp', multiline=False,
                                 input_filter='float', size_hint_x=0.3)
        return self._fm_alt

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

    # ---------------- 三、单机操作 ----------------
    def _build_single(self):
        b = BoxLayout(orientation='vertical', spacing=6, size_hint_y=None)
        top = BoxLayout(orientation='horizontal', spacing=6, size_hint_y=None, height=INPUT_H)
        self._sp_sys = Spinner(text='1号机', values=['%d号机' % i for i in range(1, 11)],
                               font_size='17sp', size_hint_x=0.42)
        self._sp_sys.bind(text=self._on_sys_changed)
        self._lbl_veh = Label(text='未选择', font_size='15sp', halign='left', valign='middle')
        top.add_widget(self._sp_sys)
        top.add_widget(self._lbl_veh)
        b.add_widget(top)

        g = GridLayout(cols=2, spacing=6, size_hint_y=None, height='330dp')
        g.add_widget(self._mk_btn('单机起飞', OK, lambda: self._confirm(
            '单机起飞', '%s 按 %s m 起飞？' % (self._sel_name(), self._tof_alt()),
            lambda: self._single_act('起飞', self.fleet.takeoff, self._tof_alt()))))
        g.add_widget(self._mk_btn('单机降落', DANGER, lambda: self._confirm(
            '单机降落', '%s 立即降落？' % self._sel_name(),
            lambda: self._single_act('降落', self.fleet.land))))
        g.add_widget(self._mk_btn('单机解锁', DANGER, lambda: self._confirm(
            '单机解锁', '%s 解锁？' % self._sel_name(),
            lambda: self._single_act('解锁', self.fleet.arm, True))))
        g.add_widget(self._mk_btn('单机上锁', DANGER, lambda: self._confirm(
            '单机上锁', '%s 上锁（仅地面）？' % self._sel_name(),
            lambda: self._single_act('上锁', self.fleet.arm, False))))
        g.add_widget(self._mk_btn('单机返航', DANGER, lambda: self._confirm(
            '单机返航', '%s 返航 RTL？' % self._sel_name(),
            lambda: self._single_act('返航', self.fleet.rtl))))
        g.add_widget(self._mk_btn('单机投弹', DANGER, lambda: self._confirm(
            '单机投弹', '%s 投弹（舵机6 PWM2000）？' % self._sel_name(),
            lambda: self._single_act('投弹', self.fleet.bomb))))
        mrow = BoxLayout(orientation='horizontal', spacing=6, size_hint_y=None, height=INPUT_H)
        self._sp_mode_one = Spinner(text='自动(3)', values=MODE_SPINNER_VALUES,
                                    font_size='15sp', size_hint_x=0.6)
        mrow.add_widget(self._sp_mode_one)
        mrow.add_widget(self._mk_btn('本机切模式', ACCENT, self._on_single_mode, size_hint_x=0.4))
        g.add_widget(mrow)
        b.add_widget(g)
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

    def _on_single_mode(self, _x):
        mode = self._sp_mode_one_mode()
        self._single_act('切模式', self.fleet.set_mode, mode)

    def _single_act(self, label, fn, *args):
        if not self.fleet.connected:
            self._append_log('未连接')
            return
        try:
            ok = fn(self._sel_sysid(), *args)
            self._append_log('%s %s：%s' % (self._sel_name(), label,
                                           '指令已发送' if ok else '发送失败'))
        except Exception as e:
            self._append_log('%s %s 失败：%s' % (self._sel_name(), label, e))

    # ---------------- 四、任务航点 ----------------
    def _build_mission(self):
        b = BoxLayout(orientation='vertical', spacing=6, size_hint_y=None)
        r1 = BoxLayout(orientation='horizontal', spacing=4, size_hint_y=None, height=INPUT_H)
        r1.add_widget(self._mk_btn('下载任务', ACCENT, self._on_download_mission, size_hint_x=0.25))
        r1.add_widget(self._mk_btn('上传任务', ACCENT, lambda: self._confirm(
            '上传任务', '把当前任务（%d 条）写入 %s？' % (self._mission_len(), self._sel_name()),
            self._on_upload_mission), size_hint_x=0.25))
        r1.add_widget(self._mk_btn('清除任务', GRAY, self._on_clear_mission, size_hint_x=0.25))
        r1.add_widget(self._mk_btn('地图设点', (0.15, 0.6, 0.35, 1), self._on_open_map,
                                   size_hint_x=0.25))
        b.add_widget(r1)

        r2 = BoxLayout(orientation='horizontal', spacing=6, size_hint_y=None, height=INPUT_H)
        self._wp_lat = TextInput(hint_text='纬度', font_size='16sp', multiline=False,
                                 input_filter='float', size_hint_x=0.24)
        self._wp_lon = TextInput(hint_text='经度', font_size='16sp', multiline=False,
                                 input_filter='float', size_hint_x=0.24)
        self._wp_alt = TextInput(hint_text='高度m', font_size='16sp', multiline=False,
                                 input_filter='float', size_hint_x=0.2)
        r2.add_widget(self._wp_lat)
        r2.add_widget(self._wp_lon)
        r2.add_widget(self._wp_alt)
        r2.add_widget(self._mk_btn('加航点', ACCENT, self._on_add_wp, size_hint_x=0.16))
        r2.add_widget(self._mk_btn('插投弹', DANGER, self._on_add_bomb, size_hint_x=0.16))
        b.add_widget(r2)

        r3 = BoxLayout(orientation='horizontal', spacing=6, size_hint_y=None, height=INPUT_H)
        r3.add_widget(self._mk_btn('坐标换算（高斯X/Y→经纬回填）', (0.55, 0.4, 0.2, 1),
                                   self._on_open_coord, size_hint_x=1.0))
        b.add_widget(r3)

        self._mission_scroll = ScrollView(size_hint_y=None, height='200dp')
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
        v = self.fleet.vehicle(self._sel_sysid())
        rows = v.mission if v else []
        self._mission_box.clear_widgets()
        sel = self._sel_seq
        for it in rows:
            cmd = vehicles.MAV_CMD_ZH.get(it['cmd'], 'M%g' % it['cmd'])
            pos = '' if it['cmd'] == 184 else ' %.6f,%.6f %sm' % (it['lat'], it['lon'], it['alt'])
            txt = '#%d %s%s' % (it['seq'], cmd, pos)
            row = Button(text=txt, font_size='14sp', height='34dp', size_hint_y=None,
                         background_color=(0.35, 0.5, 0.35, 1) if sel == it['seq'] else
                         (0.25, 0.3, 0.38, 1))
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
        self.fleet.download_mission(self._sel_sysid())

    def _on_upload_mission(self):
        if not self.fleet.connected:
            self._append_log('未连接')
            return
        self._append_log('正在上传 %s 任务…' % self._sel_name())
        self.fleet.upload_mission(self._sel_sysid())

    def _on_clear_mission(self, _x):
        if not self.fleet.connected:
            self._append_log('未连接')
            return
        self.fleet.clear_mission(self._sel_sysid())
        self._refresh_mission_table()

    def _on_add_wp(self, _x):
        try:
            lat = float(self._wp_lat.text)
            lon = float(self._wp_lon.text)
            alt = float(self._wp_alt.text)
        except Exception:
            self._append_log('加航点失败：纬度/经度/高度未填全')
            return
        self.fleet.append_waypoint(self._sel_sysid(), lat, lon, alt)
        self._refresh_mission_table()

    def _on_add_bomb(self, _x):
        if self._sel_seq is None:
            self._append_log('请先在任务表点选一个航点，再「插投弹」')
            return
        self.fleet.add_bomb_after(self._sel_sysid(), self._sel_seq)
        self._refresh_mission_table()

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
                lbl = Label(text='--', font_size='15sp', size_hint_x=None, width='66dp')
                self._sat_box.add_widget(lbl)
        for w, s in zip(reversed(self._sat_box.children), sysids):
            v = self.fleet.fleet[s]
            if v.online and v.satellites is not None:
                w.text = '%d:%d' % (s, v.satellites)
                w.color = OK
            else:
                w.text = '%d:--' % s
                w.color = GRAY

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
    def _mk_btn(self, text, color, on_release, size_hint_x=1, height=BTN_H):
        b = Button(text=text, font_size='16sp', background_color=color,
                   size_hint_y=None, height=height, size_hint_x=size_hint_x)
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

    def _swarm_act(self, label, fn, *args, **kw):
        if not self.fleet.connected:
            self._append_log('未连接')
            return
        try:
            n = fn(*args) if not kw else fn(*args, **kw)
            if label == '切自动':
                self._append_log('全部切 AUTO：各机执行各自任务')
            elif label == '切模式':
                self._append_log('%s' % kw.get('label', ''))
            else:
                self._append_log('全队%s：指令已发送 %d 架' % (label, n))
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