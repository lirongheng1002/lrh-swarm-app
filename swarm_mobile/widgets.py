"""通用 UI 控件：圆角按钮、紧凑输入框等，统一 APP 视觉风格。
"""
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.properties import ListProperty, NumericProperty, StringProperty
from kivy.metrics import dp


class RoundedButton(Button):
    """圆角按钮：background_color 即填充色，支持圆角半径与描边。"""

    radius = NumericProperty('8dp')
    border_color = ListProperty([0, 0, 0, 0])
    border_width = NumericProperty('1dp')

    def __init__(self, **kwargs):
        # 去掉 Kivy 默认渐变背景图，避免圆角被覆盖成直角
        kwargs.setdefault('background_normal', '')
        kwargs.setdefault('background_down', '')
        kwargs.setdefault('background_disabled_normal', '')
        kwargs.setdefault('background_disabled_down', '')
        kwargs.setdefault('border', (0, 0, 0, 0))
        # 默认不透明深灰底：按钮四角圆角外不露透明识别区（领导要求消除透明框）
        kwargs.setdefault('background_color', (0.3, 0.32, 0.36, 1))
        super().__init__(**kwargs)
        self._bg = None
        self._border = None
        self.bind(pos=self._draw, size=self._draw,
                  background_color=self._draw, radius=self._draw,
                  border_color=self._draw, border_width=self._draw,
                  state=self._draw)
        Clock.schedule_once(self._draw, 0)

    def _draw(self, *args):
        # 空一帧保证尺寸有效
        self.canvas.before.clear()
        with self.canvas.before:
            # 按下时轻微压暗
            col = self.background_color
            if self.state == 'down':
                col = [max(0, c * 0.75) for c in col[:3]] + [col[3]]
            Color(*col)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size,
                                        radius=[dp(self.radius)] * 4)
            Color(*self.border_color)
            self._border = Line(rounded_rectangle=(
                self.x, self.y, self.width, self.height, dp(self.radius)),
                width=dp(self.border_width))


class CompactTextInput(TextInput):
    """紧凑输入框：根据数字/文字宽度自适应占位，减小上下 padding。"""

    def __init__(self, **kwargs):
        kwargs.setdefault('font_size', '15sp')
        kwargs.setdefault('multiline', False)
        kwargs.setdefault('halign', 'center')
        kwargs.setdefault('padding_y', (dp(6), dp(6)))
        kwargs.setdefault('background_normal', '')
        kwargs.setdefault('background_active', '')
        kwargs.setdefault('background_color', [0.18, 0.2, 0.22, 1])
        kwargs.setdefault('foreground_color', [0.95, 0.95, 0.95, 1])
        kwargs.setdefault('hint_text_color', [0.55, 0.55, 0.55, 1])
        kwargs.setdefault('cursor_color', [0.9, 0.95, 1, 1])
        super().__init__(**kwargs)
        self.bind(text=self._resize)
        Clock.schedule_once(self._resize, 0)

    def _resize(self, *args):
        # 根据文本长度给出一个合适的宽度：hint/内容不会截断即可
        # 宽度由外部 layout 决定，这里只保证 padding_x 让文字居中
        text = self.text if self.text else self.hint_text
        # 每个字符约 0.55 * font_size，留点边距
        fw = self.font_size * 0.55
        needed = max(len(text) * fw, self.font_size * 3)
        pad = max(0, (self.width - needed) / 2)
        self.padding_x = (pad, pad)


# 延迟导入，避免模块顶层循环依赖
from kivy.clock import Clock  # noqa: E402
