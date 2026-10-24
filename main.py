# -*- coding: utf-8 -*-
"""
AHUT 晚寝签到 · 安卓 App（Kivy 版）

- 用 buildozer 打包成 APK，里面自带 Python 3 运行环境，装上就能用，不需要装 Python；
- 签到逻辑全部在 signer.py（和电脑版、命令行版是同一套）；
- 只有界面是新的：学号、密码、按钮、日志框。
"""

import os
import threading
import traceback

# 安卓没有系统证书库，HTTPS 会报证书错误；用 certifi 自带的证书链。
# 注意：必须直接赋值（不能 setdefault，运行时可能已被设成一个目录）。
try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    os.environ["SSL_CERT_DIR"] = os.path.dirname(certifi.where())
except Exception:
    pass

from kivy.app import App
from kivy.clock import mainthread
from kivy.core.text import LabelBase
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
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


class SignApp(App):
    title = "AHUT 晚寝签到"
    running = False

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
        if result.get("success"):
            self.status.text = f"签到成功{cost}"
            self.append(f"✔ 流程结束：签到成功{cost}")
        elif result.get("unknown"):
            self.status.text = "结果未知，请到系统核实"
            self.append("! 结果未知，请到考勤系统核实")
        else:
            errs = "；".join(dict.fromkeys([e for e in result.get("errors", []) if e]))
            self.status.text = f"签到失败{cost}"
            self.append(f"✘ 流程结束：签到失败{('（' + errs + '）') if errs else ''}")

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
