# LRH 手机集群控制 APP v1.0.1 界面与功能优化变更说明

## 修改文件

1. `swarm_mobile/app.py` —— 主界面重构与功能修复
2. `swarm_mobile/mapview.py` —— 地图手势缩放与控件优化
3. `swarm_mobile/widgets.py` —— 新增统一圆角控件（RoundedButton / CompactTextInput）
4. `buildozer.spec` —— 版本号更新至 1.0.1

---

## 一、全部飞机控制栏（页①）

### 修复
- **第一栏被压缩/重叠**：原因为 `_build_fleet_ops()` 外层 `BoxLayout` 与内部 `alts` 未设置固定高度，导致 `ScrollView` 的 `minimum_height` 计算错误。现在所有容器均显式设置高度，布局不再压缩。
- **菜单栏上缩重叠**：导航栏固定在根布局，不参与 `ScrollView` 滚动；切页逻辑稳定。

### 优化
- 全队操作区重构为 **4 行 × 4 列** 网格：
  - 行1：全部解锁 / 全部上锁 / 全部起飞 / 全部降落
  - 行2：全部返航 / 全部投弹 / 切自动任务 / 全部切模式
  - 行3：起飞高度 + 输入框 + 确定 + m
  - 行4：全队高度 + 输入框 + 确定 + m
- 文本框改用 `CompactTextInput`，根据内容自适应宽度，避免占位过大。
- 速度参数独立为紧凑单行（飞行速度 / 全队航速）。
- 所有按钮统一使用 `RoundedButton`，圆角风格一致。

---

## 二、单架飞机控制栏（页②）

### 修复
- **本机切模式点击无响应**：原 `Popup` 使用纵向长列表 + `ScrollView`，在安卓上容易点不动。改为 **2 列紧凑网格弹窗**，模式按钮直接可点。
- 同时修复了 **全部切模式** 无反应问题（与单机共用同一套弹窗组件 `_mode_popup`）。

### 优化
- 控制元素整体下移：顶部保留选机行，中间用占位 + 权重把按钮区推到屏幕中下部。
- 6 个操作按钮与底部「本机切模式」全部圆润。

---

## 三、任务航线控制（页③）

### 修复
- **移除缩放滑条**：地图缩放改为 **双指捏合/张开** 手势（pinch-to-zoom），单指点击仍可设航点。

### 优化
- 地图顶栏改为「坐标 + zoom 等级 + 关闭按钮」，提示文字改为「双指捏合缩放，点击地图设为航点」。
- 航线控件区输入框改用 `CompactTextInput`，宽度比例协调。
- 所有功能按钮圆润并统一字号/高度（40dp）。
- 任务表行按钮也改为圆角。

---

## 四、全局

- 新增 `swarm_mobile/widgets.py`：
  - `RoundedButton`：自定义圆角、背景色、按下变暗、可选描边。
  - `CompactTextInput`：紧凑输入框，文字居中，padding 更小。
- 所有按钮（连接、断开、导航、清空日志、确认弹窗、坐标换算弹窗、任务表行）统一圆润。
- 删除已废弃的 `_alt_tof_in` / `_spd_one_in` / `_spd_all_in` 辅助方法，简化代码。
- 按功能类型重新归类布局，避免重叠。

---

## 五、验证

- Python 语法检查：`py_compile` 通过 `app.py` / `mapview.py` / `widgets.py` / `fleet.py`。
- 核心逻辑验证：手动启动 `mock_relay.py` 后，`set_mode_all(3)` 与 `set_mode(2,4)` 均返回成功，MAVLink 指令发送正常。
- 本地 APK 构建：当前环境 `buildozer` 未安装 Android target，建议通过项目已有 `.github/workflows/build-apk.yml` 在 GitHub Actions 上构建 v1.0.1 APK。
