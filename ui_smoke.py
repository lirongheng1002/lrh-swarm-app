"""UI 层冒烟：验证 Kivy 界面构建、按钮回调、模式解析、航点编辑等不抛异常。
（无真机/无服务器也能跑；窗口会自动打开并约 2 秒后自动关闭）
运行：python ui_smoke.py
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kivy.clock import Clock

from swarm_mobile.app import SwarmMobileApp


class UIProbe(SwarmMobileApp):

    def build(self):
        root = super().build()
        Clock.schedule_once(self._probe, 1.2)
        return root

    def _probe(self, _dt):
        try:
            # 1) 界面已构建（关键控件存在）
            for attr in ('_host_in', '_port_in', '_btn_conn', '_lbl_status',
                         '_lbl_fm', '_sat_box', '_sp_mode_all', '_sp_sys',
                         '_lbl_veh', '_sp_mode_one', '_wp_lat', '_wp_lon',
                         '_wp_alt', '_mission_box'):
                assert hasattr(self, attr), '缺少控件 %s' % attr

            # 2) 模式解析
            assert self._parse_mode('自动(3)') == 3
            assert self._parse_mode('降落(9)') == 9

            # 3) 航点本地编辑（未连接）
            self._wp_lat.text = '30.5'
            self._wp_lon.text = '120.6'
            self._wp_alt.text = '25'
            self._on_add_wp('x')
            assert self._mission_len() == 1, '加航点后任务数 %s' % self._mission_len()
            self._refresh_mission_table()
            assert len(self._mission_box.children) >= 1, '任务表无行渲染'

            # 4) 任务行点选
            self._on_mission_row(0)
            assert self._sel_seq == 0

            # 5) 插投弹（选中航点后）
            self._on_add_bomb('x')
            assert self._mission_len() == 2, '插投弹后任务数 %s' % self._mission_len()

            # 6) 清除任务
            self._on_clear_mission('x')
            assert self._mission_len() == 0

            # 7) 队形预设 + 单机切换 + 编队启停（未连接，仅逻辑路径）
            self._on_preset('人字形')
            self._sp_sys.text = '3号机'
            assert self._sel_sysid() == 3
            self._on_formation_start('x')   # 未连接应提示且不崩
            self._on_formation_stop('x')

            # 8) 连接路径（连不上也不应抛——重连线程后台退避）
            self._host_in.text = '127.0.0.1'
            self._port_in.text = '15650'
            self._on_connect('x')

            print('UI SMOKE: ALL PASS (界面构建/回调/模式/航点/编队/连接路径)')
        except Exception:
            traceback.print_exc()
            print('UI SMOKE: FAIL')
        finally:
            Clock.schedule_once(lambda _x: self.stop(), 0.8)


if __name__ == '__main__':
    UIProbe().run()