"""MAVLink 指令封装（ArduPilot Copter）"""
import math

# Copter 模式号
MODE_AUTO = 3
MODE_GUIDED = 4
MODE_LOITER = 5
MODE_RTL = 6
MODE_LAND = 9

# MAVLink 常量
FRAME_GLOBAL_RELATIVE_ALT = 3
TYPE_MASK_POS_YAW = 0x2E        # 只用位置+偏航（忽略速度/加速度/偏航率）
MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
COMP_AP = 1


def _cmd_long(bus, sysid, command, p1=0, p2=0, p3=0, p4=0, p5=0, p6=0, p7=0):
    mav = bus.get_mav(sysid)
    if mav is None:
        return False
    msg = mav.command_long_encode(sysid, COMP_AP, command, 0,
                                  p1, p2, p3, p4, p5, p6, p7)
    return bus.send(sysid, msg)


def set_mode(bus, sysid, custom_mode):
    """切换飞行模式（176 DO_SET_MODE）"""
    return _cmd_long(bus, sysid, 176, MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                     float(custom_mode))


def arm(bus, sysid, on=True, force=False):
    # force=True → param2=21196 强制解锁（跳过预启动检查，慎重使用）
    p2 = 21196.0 if force else 0.0
    return _cmd_long(bus, sysid, 400, 1.0 if on else 0.0, p2)


def takeoff(bus, sysid, alt_m):
    return _cmd_long(bus, sysid, 22, 0, 0, 0, 0, 0, 0, alt_m)


def rtl(bus, sysid):
    return set_mode(bus, sysid, MODE_RTL)


def land(bus, sysid):
    return set_mode(bus, sysid, MODE_LAND)


def bomb_drop(bus, sysid, servo=6, pwm=2000, count=1, time_s=1):
    """投弹：DO_REPEAT_SERVO(184) 舵机触发投放"""
    return _cmd_long(bus, sysid, 184, float(servo), float(pwm),
                     float(count), float(time_s))


def change_speed(bus, sysid, mps):
    """DO_CHANGE_SPEED(178)：设巡航速度（param1=0=巡航/起飞，param2=速度 m/s）"""
    return _cmd_long(bus, sysid, 178, 0.0, float(mps))


def guided_target(bus, sysid, lat, lon, alt_m, yaw_deg=None):
    """引导目标（86 SET_POSITION_TARGET_GLOBAL_INT，仅位置+偏航，负载极小）"""
    mav = bus.get_mav(sysid)
    if mav is None:
        return False
    yaw = math.radians(yaw_deg) if yaw_deg is not None else 0.0
    msg = mav.set_position_target_global_int_encode(
        0, sysid, COMP_AP, FRAME_GLOBAL_RELATIVE_ALT, TYPE_MASK_POS_YAW,
        int(lat * 1e7), int(lon * 1e7), alt_m,
        0, 0, 0, 0, 0, 0, yaw, 0)
    return bus.send(sysid, msg)


def set_message_interval(bus, sysid, msgid, interval_us):
    return _cmd_long(bus, sysid, 511, float(msgid), float(interval_us))


def set_current_wp(bus, sysid, seq):
    """把任务当前航点设为 seq（41 MISSION_SET_CURRENT）"""
    mav = bus.get_mav(sysid)
    if mav is None:
        return False
    msg = mav.mission_set_current_encode(sysid, COMP_AP, seq)
    return bus.send(sysid, msg)


def disperse(bus, sysid, seq=None):
    """离散：可选先跳转到指定航点，再切 AUTO 执行各自任务"""
    if seq is not None:
        set_current_wp(bus, sysid, seq)
    return set_mode(bus, sysid, MODE_AUTO)


def throttle_downlink(bus, sysid):
    """下行限流：只保留必要消息（解决 4G 拥堵的关键之一）。
    msgid -> 微秒间隔；0 = 停止发送该消息"""
    plan = {
        33: 500000,       # GLOBAL_POSITION_INT  2Hz（编队必需）
        0: 1000000,       # HEARTBEAT            1Hz
        1: 1000000,       # SYS_STATUS           1Hz
        30: 0,            # ATTITUDE             关闭
        74: 0,            # VFR_HUD              关闭
        24: 0,            # GPS_RAW_INT          关闭
        65: 0,            # RC_CHANNELS          关闭
        36: 5000000,      # SERVO_OUTPUT_RAW     0.2Hz
        147: 5000000,     # BATTERY_STATUS       0.2Hz
    }
    for msgid, us in plan.items():
        set_message_interval(bus, sysid, msgid, us)
    return True
