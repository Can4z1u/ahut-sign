# -*- coding: utf-8 -*-
"""
AHUT 晚寝签到 · 安卓 App（Kivy 版）

- 用 buildozer 打包成 APK，里面自带 Python 3 运行环境，装上就能用，不需要装 Python；
- 签到逻辑全部在 signer.py（和电脑版、命令行版是同一套）；
- 界面：学号、密码、按钮、日志框；
- 定时：用 Android AlarmManager 设一个系统闹钟，到点由系统把 App 拉起来自动签到
  （Kivy 的定时器在后台会被系统冻结，所以必须走系统闹钟）。
"""

import os
import random
import threading
import traceback
from datetime import datetime, timedelta

# 安卓没有系统证书库，HTTPS 会报证书错误；用 certifi 自带的证书链。
# 注意：必须直接赋值（不能 setdefault，运行时可能已被设成一个目录）。
try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    os.environ["SSL_CERT_DIR"] = os.path.dirname(certifi.where())
except Exception:
    pass

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.text import LabelBase
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

import signer

# Kivy 自带字体没有中文，借安卓系统里的中文字体；找不到也不至于崩，只是会显示方块。
CJK_FONTS = [
    "/system/fonts/NotoSansCJK-Regular.ttc",
    "/system/fonts/NotoSansSC-Regular.otf",
    "/system/fonts/NotoSansHans-Regular.otf",
    "/system/fonts/DroidSansFallback.ttf",
    "/system/fonts/DroidSansChinese.ttf",
    "/system/fonts/NanumGothic.ttf",
]


def register_cjk_font():
    for path in CJK_FONTS:
        if os.path.exists(path):
            try:
                # 直接把默认字体名换掉，所有控件（含输入框）都会用中文字体
                LabelBase.register(name="Roboto", fn_regular=path)
                return path
            except Exception:
                continue
    return None


register_cjk_font()

# ---------------------------------------------------------------- 系统闹钟
# 全部包在 try/except 里：不在安卓上运行（比如电脑调试）时安全返回。

ANDROID_ACTIVITY = "org.kivy.android.PythonActivity"
ALARM_REQUEST_CODE = 1001


def _pending_intent():
    from jnius import autoclass
    activity = autoclass(ANDROID_ACTIVITY).mActivity
    Intent = autoclass("android.content.Intent")
    PendingIntent = autoclass("android.app.PendingIntent")

    intent = Intent()
    intent.setClassName(activity.getPackageName(), ANDROID_ACTIVITY)
    intent.putExtra("autosign", "1")
    try:
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK)
    except Exception:
        pass

    flags = PendingIntent.FLAG_UPDATE_CURRENT
    immutable = getattr(PendingIntent, "FLAG_IMMUTABLE", None)
    if immutable is not None:
        flags |= int(immutable)
    return activity, PendingIntent.getActivity(activity, ALARM_REQUEST_CODE, intent, flags)


def next_run_time(hour=21, minute=20):
    now = datetime.now()
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if when <= now:
        when += timedelta(days=1)
    return when


def parse_window(text, default=((21, 21), (21, 25))):
    """解析 "21:21-21:25" → ((21, 21), (21, 25))；解析失败就用默认值。"""
    try:
        left, right = str(text).split("-")
        h1, m1 = (int(x) for x in left.strip().split(":"))
        h2, m2 = (int(x) for x in right.strip().split(":"))
        if (0 <= h1 < 24 and 0 <= m1 < 60 and 0 <= h2 < 24 and 0 <= m2 < 60
                and (h2, m2) >= (h1, m1)):
            return (h1, m1), (h2, m2)
    except Exception:
        pass
    return default


def next_random_time(start, end):
    """在 [start, end] 时间窗里随机取一个时刻（精确到秒）；窗口已过就取明天。"""
    now = datetime.now()
    lo = now.replace(hour=start[0], minute=start[1], second=0, microsecond=0)
    hi = now.replace(hour=end[0], minute=end[1], second=0, microsecond=0)
    if now >= hi:
        lo += timedelta(days=1)
        hi += timedelta(days=1)
    span = max(0, int((hi - lo).total_seconds()))
    return lo + timedelta(seconds=random.randint(0, span))


def set_alarm(when):
    """在 when 这个时刻让系统拉起 App。返回 None 表示失败。"""
    try:
        from jnius import autoclass
        activity, pending = _pending_intent()
        Context = autoclass("android.content.Context")
        AlarmManager = autoclass("android.app.AlarmManager")

        alarm = activity.getSystemService(Context.ALARM_SERVICE)
        trigger = int(when.timestamp() * 1000)
        try:
            alarm.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, trigger, pending)
        except Exception:
            # Android 13+ 没给「精确闹钟」权限时的退路：允许延迟十几分钟
            alarm.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, trigger, pending)
        return when
    except Exception:
        return None


def cancel_alarm():
    try:
        from jnius import autoclass
        activity, pending = _pending_intent()
        Context = autoclass("android.content.Context")
        AlarmManager = autoclass("android.app.AlarmManager")
        alarm = activity.getSystemService(Context.ALARM_SERVICE)
        alarm.cancel(pending)
        pending.cancel()
        return True
    except Exception:
        return False


def launched_by_alarm():
    """这次启动是不是闹钟拉起来的（Intent 里带 autosign=1）。"""
    try:
        from jnius import autoclass
        activity = autoclass(ANDROID_ACTIVITY).mActivity
        extra = activity.getIntent().getStringExtra("autosign")
        return str(extra) == "1" if extra is not None else False
    except Exception:
        return False


def parse_hhmm(text, default=(21, 20)):
    try:
        parts = str(text).strip().split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if 0 <= hour < 24 and 0 <= minute < 60:
            return hour, minute
    except Exception:
        pass
    return default


class SignApp(App):
    title = "AHUT 晚寝签到"
    running = False
    auto_triggered = False

    def build(self):
        signer.use_dir(self.user_data_dir)      # 配置和日志放到 App 私有目录
        self.cfg = signer.load_config()

        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))

        root.add_widget(Label(text="AHUT 晚寝签到", font_size=sp(22),
                              size_hint_y=None, height=dp(40)))

        root.add_widget(Label(text="学号", size_hint_y=None, height=dp(22),
                              font_size=sp(14), halign="left", text_size=(None, None)))

        self.entry_sid = TextInput(
            text=str(self.cfg.get("student_id") or ""),
            multiline=False, input_type="number", font_size=sp(20),
            size_hint_y=None, height=dp(48),
        )
        root.add_widget(self.entry_sid)

        root.add_widget(Label(text="密码（没改过就留空 = 初始密码）", size_hint_y=None,
                              height=dp(22), font_size=sp(14)))

        self.entry_pwd = TextInput(
            text=str(self.cfg.get("password") or ""),
            multiline=False, password=True, font_size=sp(20),
            size_hint_y=None, height=dp(48),
        )
        root.add_widget(self.entry_pwd)

        # 自动签到开关
        auto_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(38))
        self.chk_auto = CheckBox(active=bool(self.cfg.get("auto_sign")),
                                 size_hint_x=None, width=dp(44))
        self.chk_auto.bind(active=self.on_auto_toggle)
        auto_row.add_widget(self.chk_auto)
        auto_row.add_widget(Label(text="每天 21:21~21:25 之间随机自动签到",
                                  font_size=sp(14), halign="left", valign="middle"))
        root.add_widget(auto_row)

        self.auto_status = Label(text="", font_size=sp(12), color=(0.4, 0.4, 0.4, 1),
                                 size_hint_y=None, height=dp(22), halign="left")
        root.add_widget(self.auto_status)

        self.btn = Button(text="开 始 签 到", font_size=sp(20),
                          size_hint_y=None, height=dp(56),
                          background_normal="", background_color=(0.1, 0.44, 0.77, 1))
        self.btn.bind(on_release=lambda *_: self.start())
        root.add_widget(self.btn)

        self.status = Label(text="21:20 之后使用 · 密码没改过就留空", font_size=sp(14),
                            size_hint_y=None, height=dp(24))
        root.add_widget(self.status)

        self.log_label = Label(text="", font_size=sp(13), halign="left", valign="top",
                               size_hint_y=None)
        self.log_label.bind(width=lambda *_: setattr(
            self.log_label, "text_size", (self.log_label.width, None)))
        self.log_label.bind(texture_size=lambda *_: setattr(
            self.log_label, "height", self.log_label.texture_size[1]))
        self.scroll = ScrollView(bar_width=dp(3))
        self.scroll.add_widget(self.log_label)
        root.add_widget(self.scroll)

        self.append("准备就绪，点上面的按钮开始。")

        # 每次启动都把闹钟重新挂上（手机重启会清空闹钟，靠这里恢复）
        self.refresh_auto_status()

        # 闹钟拉起来的：稍等界面就绪后自动签到
        if launched_by_alarm():
            self.auto_triggered = True
            self.append("· 定时任务触发，自动开始签到…")
            Clock.schedule_once(lambda dt: self.start(), 1.0)

        return root

    # ---------- 界面小工具 ----------

    def append(self, text):
        self.log_label.text += text + "\n"
        self.scroll.scroll_y = 0

    @mainthread
    def ui_log(self, level, msg):
        icon = {"ok": "✔", "err": "✘", "warn": "!", "info": "·"}.get(level, "·")
        self.append(f"{icon} {msg}")

    @mainthread
    def ui_done(self, result):
        self.running = False
        self.btn.disabled = False
        self.btn.text = "开 始 签 到"
        elapsed = result.get("elapsed")
        cost = f"（{elapsed:.1f} 秒）" if elapsed else ""
        success = bool(result.get("success"))
        if success:
            self.status.text = f"签到成功{cost}"
            self.append(f"✔ 流程结束：签到成功{cost}")
        elif result.get("unknown"):
            self.status.text = "结果未知，请到系统核实"
            self.append("! 结果未知，请到考勤系统核实")
        else:
            errs = "；".join(dict.fromkeys([e for e in result.get("errors", []) if e]))
            self.status.text = f"签到失败{cost}"
            self.append(f"✘ 流程结束：签到失败{('（' + errs + '）') if errs else ''}")

        if self.cfg.get("auto_sign") and self.auto_triggered:
            self.auto_triggered = False
            if success:
                when = set_alarm(next_random_time(*self.auto_window()))
                if when:
                    self.auto_status.text = f"下次自动签到：{when:%m-%d %H:%M:%S}"
            else:
                # 失败（断网/未到时间等）：10 分钟后再试一次，最多试到 22:50
                retry_at = datetime.now() + timedelta(minutes=10)
                if retry_at.hour < 23:
                    if set_alarm(retry_at):
                        self.auto_status.text = f"失败了，{retry_at:%H:%M} 再试一次"

    # ---------- 自动签到 ----------

    def auto_window(self):
        """每天随机签到的时间窗，默认 21:21~21:25，可在 签到配置.json 里改 auto_window。"""
        return parse_window(self.cfg.get("auto_window") or "21:21-21:25")

    def refresh_auto_status(self):
        if not self.cfg.get("auto_sign"):
            cancel_alarm()
            self.auto_status.text = "自动签到已关闭"
            return
        when = set_alarm(next_random_time(*self.auto_window()))
        if when:
            self.auto_status.text = f"下次自动签到：{when:%m-%d %H:%M:%S}"
        else:
            self.auto_status.text = "自动签到已开启，但系统闹钟设置失败（检查权限）"

    def on_auto_toggle(self, checkbox, active):
        # build() 里设置初始值时也会触发一次，保持幂等即可
        if not hasattr(self, "cfg"):
            return
        self.cfg["auto_sign"] = bool(active)
        signer.save_config(self.cfg)
        if active:
            when = set_alarm(next_random_time(*self.auto_window()))
            self.auto_status.text = (f"下次自动签到：{when:%m-%d %H:%M:%S}" if when
                                     else "已开启，但系统闹钟设置失败（检查权限）")
            if when:
                self.append(f"· 已开启自动签到，下次 {when:%m-%d %H:%M}")
        else:
            cancel_alarm()
            self.auto_status.text = "自动签到已关闭"
            self.append("· 已关闭自动签到")

    # ---------- 签到动作 ----------

    def start(self):
        if self.running:
            return
        sid = (self.entry_sid.text or "").strip()
        pwd = (self.entry_pwd.text or "").strip()
        if not sid.isdigit() or len(sid) < 6:
            self.status.text = "学号必须是纯数字（例如 259034324）"
            self.append("✘ 学号格式不对，请检查")
            return

        self.cfg["student_id"] = sid
        signer.save_config(self.cfg)

        self.running = True
        self.btn.disabled = True
        self.btn.text = "签 到 中 …"
        self.status.text = "正在签到，请稍候…"
        self.append("────────────")
        threading.Thread(target=self.worker, args=(sid, pwd), daemon=True).start()

    def worker(self, sid, pwd):
        result = {"success": False, "unknown": False, "errors": ["未知异常"]}
        try:
            result = signer.Signer(sid, pwd, self.ui_log, self.cfg).run()
        except Exception:
            self.ui_log("err", "程序异常：\n" + traceback.format_exc())
        finally:
            self.ui_done(result)

    # ---------- 生命周期 ----------

    def on_pause(self):
        return True     # 切到后台不退出（签到可能正在进行）

    def on_resume(self):
        pass


if __name__ == "__main__":
    SignApp().run()
