# -*- coding: utf-8 -*-
"""
AHUT 晚寝签到 · 命令行版（安卓 Pydroid 3 / Termux 可用）

与电脑版 晚寝签到.pyw 的签到逻辑完全一致（同一套登录 / 签名 / 六步 / 重试），
只是去掉了 tkinter 界面，改成在终端里输出进度，适合手机直接运行。

用法（Pydroid 3 里点 ▶ 直接跑，或 Termux 里 python 签到.py）：
    python 签到.py                  # 用 签到配置.json 里记住的学号
    python 签到.py 259034324        # 指定学号
    python 签到.py 259034324 密码    # 指定学号和密码
    python 签到.py --test           # 演练：只走到"取宿舍位置"，不真正提交签到
    python 签到.py --delay 0        # 全速，不模拟人工停顿
    python 签到.py --no-log         # 不写日志文件（手机存储只读时用）

配置文件 签到配置.json 和电脑版通用，可以直接复制过来。
"""

import base64
import hashlib
import http.cookiejar
import json
import os
import random
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

# ---------------------------------------------------------------- 基础常量

APP_NAME = "AHUT 晚寝签到"
APP_VERSION = "1.1-cli"
DEFAULT_PASSWORD = "Ahgydx@920"
SUGGEST_TIME = "21:20:00"

# Pydroid 3 里没法给脚本传参数：第一次运行前把学号填在这里（填过就会存进配置文件，
# 以后直接点 ▶ 即可；改过密码再填 PASSWORD）。
STUDENT_ID = ""
PASSWORD = ""

# 每步间隔、提交前等待（秒）；可用 --delay 或配置项覆盖
STEP_DELAY = (0.05, 0.15)
SIGN_DELAY = (0.8, 2.0)

API_BASE_URL = "https://xskq.ahut.edu.cn/api"

# 客户端凭证（来自原项目，学校前端内置的 client_id / secret）
BASIC_AUTH = (
    "Basic Zmx5c291cmNlX3dpc2VfYXBwOkRBNzg4YXNkVURqbmFzZF9mbHlzb3VyY2VfZHNkYWREQUlVaXV3cWU="
)

WEB_DICT = {
    "token_api": f"{API_BASE_URL}/flySource-auth/oauth/token",
    "task_id_api": (
        f"{API_BASE_URL}/flySource-yxgl/dormSignTask/getStudentTaskPage"
        "?userDataType=student&current=1&size=15"
    ),
    "auth_check_api": (
        f"{API_BASE_URL}/flySource-base/wechat/getWechatMpConfig"
        "?configUrl=https://xskq.ahut.edu.cn/wise/pages/ssgl/dormsign"
        "?taskId={TASK_ID}&autoSign=1&scanSign=0&userId={STUDENT_ID}"
    ),
    "api_log_api": (
        f"{API_BASE_URL}/flySource-base/apiLog/save"
        "?menuTitle=%E6%99%9A%E5%AF%9D%E7%AD%BE%E5%88%B0"
    ),
    "location_api": (
        f"{API_BASE_URL}/flySource-yxgl/dormSignTask/getTaskByIdForApp"
        "?taskId={TASK_ID}&signDate={DATE}"
    ),
    "sign_in_api": f"{API_BASE_URL}/flySource-yxgl/dormSignRecord/stuSign",
    "unsigned_api": (
        f"{API_BASE_URL}/flySource-yxgl/dormSignStu/getWqdStudentPage"
        "?taskId={TASK_ID}&xhOrXm=&nowDate={DATE}&userDataType=student&current=1&size=100"
    ),
}

UA_LIST = [
    "Mozilla/5.0 (Linux; Android 15; MIX Fold 4 Build/TKQ1.240502.001; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.137 Mobile Safari/537.36 "
    "MicroMessenger/8.0.61.2660(0x28003D37) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
    "Mozilla/5.0 (Linux; Android 15; LYA-AL10 Build/HUAWEILYA-AL10; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.137 Mobile Safari/537.36 "
    "MicroMessenger/8.0.61.2660(0x28003D37) WeChat/arm64 Weixin NetType/5G Language/zh_CN ABI/arm64",
    "Mozilla/5.0 (Linux; Android 15; SM-S938B Build/TP1A.240205.004; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.137 Mobile Safari/537.36 "
    "MicroMessenger/8.0.61.2660(0x28003D37) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.61(0x18003D29) "
    "NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.61(0x18003D29) "
    "NetType/5G Language/zh_CN",
]


# ---------------------------------------------------------------- 网络层加速
# 学校域名同时有 IPv6 和 IPv4 地址。很多手机网络（尤其蜂窝数据）没有可用的 IPv6
# 通路，系统会先连 IPv6、干等 21 秒超时后才回落 IPv4 —— 这是"每个请求都卡 20 秒"
# 的根因。下面让 IPv4 地址排前面，并在启动时后台试连一次自动纠偏。

_API_HOST = urlparse(API_BASE_URL).hostname or "xskq.ahut.edu.cn"
_PREFER_V4 = True
_orig_getaddrinfo = socket.getaddrinfo


def _fast_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    infos = _orig_getaddrinfo(host, port, family, type, proto, flags)
    if len(infos) > 1:
        prefer = socket.AF_INET if _PREFER_V4 else socket.AF_INET6
        infos = sorted(infos, key=lambda i: 0 if i[0] == prefer else 1)
    return infos


socket.getaddrinfo = _fast_getaddrinfo


def _probe_address_family(timeout=1.5):
    """后台试连一次，确认本机走 IPv4 还是 IPv6。"""
    global _PREFER_V4
    try:
        infos = _orig_getaddrinfo(_API_HOST, 443, type=socket.SOCK_STREAM)
    except Exception:
        return
    if len(infos) < 2:
        return
    winner = []
    lock = threading.Lock()

    def attempt(family, sockaddr):
        sock = None
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(sockaddr)
        except Exception:
            return
        finally:
            if sock is not None:
                sock.close()
        with lock:
            if not winner:
                winner.append(family)

    threads = [threading.Thread(target=attempt, args=(item[0], item[4]), daemon=True)
               for item in infos]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout + 0.5)
    if winner:
        _PREFER_V4 = winner[0] == socket.AF_INET


# ---------------------------------------------------------------- 路径与配置

def data_dir():
    """优先用脚本所在目录（命令行版）；Kivy 应用会用 use_dir() 改成 App 私有目录。"""
    candidates = [
        os.path.dirname(os.path.abspath(__file__)),
        os.path.join(os.path.expanduser("~"), ".ahut_signin"),
    ]
    for folder in candidates:
        try:
            os.makedirs(folder, exist_ok=True)
            probe = os.path.join(folder, ".write_test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("1")
            os.remove(probe)
            return folder
        except Exception:
            continue
    return os.getcwd()


APP_DIR = data_dir()
CONFIG_PATH = os.path.join(APP_DIR, "签到配置.json")
LOG_PATH = os.path.join(APP_DIR, "签到日志.txt")
NO_LOG = False


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _delay_span(value, default):
    """把数字或 [最小, 最大] 统一成 (最小, 最大) 秒。"""
    try:
        if isinstance(value, (int, float)):
            v = max(0.0, float(value))
            return (v, v)
        if isinstance(value, (list, tuple)) and value:
            lo = max(0.0, float(value[0]))
            hi = max(lo, float(value[1])) if len(value) > 1 else lo
            return (lo, hi)
    except (TypeError, ValueError, IndexError):
        pass
    return default


# ---------------------------------------------------------------- 算法部分

def password_md5(pwd):
    return hashlib.md5(pwd.encode("utf-8")).hexdigest()


def generate_sign(url, token):
    """访问令牌签名：与 token、URL 路径、时间戳三重绑定。"""
    if not token:
        return ""
    parsed = urlparse(url)
    api = parsed.path + "?sign="
    timestamp = int(time.time() * 1000)
    inner_hash = hashlib.md5(f"{timestamp}{token}".encode("utf-8")).hexdigest()
    final_hash = hashlib.md5(f"{api}{inner_hash}".encode("utf-8")).hexdigest()
    encoded_time = base64.b64encode(str(timestamp).encode("utf-8")).decode("utf-8")
    return f"{final_hash}1.{encoded_time}"


def generate_sign_code(ts_ms):
    """签到报文 signCode：复刻 Java Date.toString() 时间串再 MD5。"""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) + timedelta(hours=8)
    weeks = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    time_str = (
        f"{weeks[dt.weekday()]} {months[dt.month - 1]} {dt.day:02d} {dt.year} "
        f"{dt.strftime('%H:%M:%S')} GMT+0800 (中国标准时间)"
    )
    return hashlib.md5(time_str.encode("utf-8")).hexdigest()


def generate_stu_task_id(lat, lng, acc, date, task_id, file_id=""):
    """签到报文 stuTaskId：把定位信息封成 MD5，服务端据此防篡改。"""
    data = {
        "latitude": str(lat),
        "longitude": str(lng),
        "locationAccuracy": str(acc),
        "signDate": date,
        "taskId": task_id,
        "fileId": file_id,
    }
    return hashlib.md5(
        json.dumps(data, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def now_info():
    t = time.localtime()
    weeks = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return {
        "date": time.strftime("%Y-%m-%d", t),
        "time": time.strftime("%H:%M:%S", t),
        "weekday": weeks[t.tm_wday],
    }


# ---------------------------------------------------------------- 日志输出

LEVEL_ICON = {"ok": "✔", "err": "✘", "warn": "!", "info": "·"}


def write_log_line(line):
    if NO_LOG:
        return
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def setup_stdout():
    """终端编码不是 UTF-8 时（比如 Windows 的 GBK 控制台）也别把日志吞掉。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def make_logger():
    def log(level, msg):
        stamp = datetime.now().strftime("%H:%M:%S")
        icon = LEVEL_ICON.get(level, "·")
        line = f"[{stamp}] {icon} {msg}"
        try:
            print(line, flush=True)
        except UnicodeEncodeError:
            # 老终端编不出 ✔ ✘，退化成纯文本标记
            plain = {"ok": "[OK]", "err": "[X]", "warn": "[!]"}.get(level, "-")
            try:
                print(f"[{stamp}] {plain} {msg}", flush=True)
            except Exception:
                pass
        except Exception:
            pass
        write_log_line(line)
    return log


# ---------------------------------------------------------------- 签到核心

def _json_loads(text):
    try:
        return json.loads(text)
    except Exception:
        return None


class Signer:
    """单人签到执行器（同步、带重试）。"""

    MAX_RETRIES = 4          # 单步最大重试
    MAX_TOKEN_RETRIES = 3    # token 失效额外重登次数

    def __init__(self, student_id, password, log, cfg=None):
        self.sid = str(student_id).strip()
        self.sid_int = int(self.sid)
        self.password = (password or "").strip() or DEFAULT_PASSWORD
        self.log = log
        cfg = cfg if isinstance(cfg, dict) else {}
        self.step_delay = _delay_span(cfg.get("step_delay"), STEP_DELAY)
        self.sign_delay = _delay_span(cfg.get("sign_delay"), SIGN_DELAY)
        self.token = ""
        self.username = ""
        self.task_id = None
        self.room_id = ""
        self.lat = 0.0
        self.lng = 0.0
        self.ua = random.choice(UA_LIST)
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    # ---------- 请求工具 ----------

    def base_headers(self):
        return {
            "User-Agent": self.ua,
            "authorization": BASIC_AUTH,
            "Content-Type": "application/json;charset=UTF-8",
            "X-Requested-With": "com.tencent.mm",
            "Origin": "https://xskq.ahut.edu.cn",
            "Referer": (
                "https://xskq.ahut.edu.cn/wise/pages/ssgl/dormsign"
                f"?&userId={self.sid_int}"
            ),
        }

    def signed_headers(self, url):
        headers = self.base_headers()
        if self.token:
            headers["flysource-auth"] = f"bearer {self.token}"
            headers["flysource-sign"] = generate_sign(url, self.token)
        return headers

    def http(self, method, url, headers=None, params=None, json_body=None, timeout=30):
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        req_headers = self.base_headers()
        if headers:
            req_headers.update(headers)
        data = None
        if json_body is not None:
            data = json.dumps(
                json_body, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        elif method.upper() == "POST":
            data = b""
        req = urllib.request.Request(
            url=url, data=data, headers=req_headers, method=method.upper()
        )
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                raw = resp.read().decode("utf-8", errors="ignore")
            parsed = _json_loads(raw)
            if parsed is None:
                parsed = {"code": -1, "msg": raw}
            return status, parsed
        except urllib.error.HTTPError as e:
            status = getattr(e, "code", 0)
            try:
                raw = e.read().decode("utf-8", errors="ignore")
            except Exception:
                raw = ""
            parsed = _json_loads(raw) if raw else None
            if parsed is None:
                parsed = {"code": -1, "msg": raw or str(e)}
            return status, parsed
        except Exception as e:  # 网络错误
            return 0, {"code": -1, "msg": str(e)}

    # ---------- 工具判断 ----------

    @staticmethod
    def is_auth_fail(msg):
        msg = msg or ""
        return any(k in msg for k in ("请求未授权", "缺失身份信息", "鉴权失败"))

    def relogin(self, msg):
        self.log("warn", f"登录状态失效（{msg or '未授权'}），重新登录…")
        self.token = ""
        return {"success": False, "step": 0, "msg": "token失效"}

    # ---------- 签到报文 ----------

    def sign_body(self):
        sign_lat = round(self.lat + round(random.uniform(-0.01, 0.01), 6), 6)
        sign_lng = round(self.lng + round(random.uniform(-0.01, 0.01), 6), 6)
        accuracy = round(random.uniform(25, 35), 2)
        today = now_info()["date"]
        return {
            "signType": 0,
            "taskId": self.task_id,
            "signLat": sign_lat,
            "signLng": sign_lng,
            "locationAccuracy": accuracy,
            "stuTaskId": generate_stu_task_id(
                sign_lat, sign_lng, accuracy, today, self.task_id
            ),
            "scanCode": "",
            "scanType": "",
            "roomId": self.room_id,
            "signKey": self.room_id,
            "signCode": generate_sign_code(int(time.time())),
        }

    # ---------- 单步执行 ----------

    def step(self, index):
        # ① 登录
        if index == 0:
            self.log("info", "① 登录考勤系统，获取 token")
            params = {
                "tenantId": "000000",
                "username": self.sid_int,
                "password": password_md5(self.password),
                "type": "account",
                "grant_type": "password",
                "scope": "all",
            }
            status, data = self.http(
                "POST", WEB_DICT["token_api"], params=params,
                headers=self.base_headers()
            )
            if isinstance(data, dict) and data.get("refresh_token"):
                self.token = data["refresh_token"]
                self.username = data.get("userName") or ""
                self.log("ok", f"登录成功：{self.username or self.sid}")
                return {"success": True, "step": 1, "msg": ""}
            desc = ""
            if isinstance(data, dict):
                desc = (data.get("error_description") or data.get("msg")
                        or data.get("error") or "")
            if "Bad credentials" in desc or "用户名或密码错误" in desc:
                desc = "密码错误（若改过密码，请在密码框里填写新密码）"
            self.log("err", f"登录失败：{desc or '服务器无响应，请检查网络'}")
            return {"success": False, "step": -1, "msg": desc or "登录失败"}

        # ② 今天的签到任务
        if index == 1:
            self.log("info", "② 获取今天的晚寝签到任务")
            url = WEB_DICT["task_id_api"]
            status, data = self.http("GET", url, headers=self.signed_headers(url))
            if data.get("code") == 200:
                records = (data.get("data") or {}).get("records") or []
                task_id = records[0].get("taskId") if records else None
                if task_id:
                    self.task_id = task_id
                    self.log("ok", f"今天的任务 ID：{task_id}")
                    return {"success": True, "step": 2, "msg": ""}
                self.log("err", "接口没有返回签到任务：今天可能没有晚寝签到任务")
                return {"success": False, "step": -1, "msg": "无签到任务"}
            msg = str(data.get("msg") or "")
            if self.is_auth_fail(msg):
                return self.relogin(msg)
            self.log("warn", f"获取任务失败：{msg or ('HTTP ' + str(status))}")
            return {"success": False, "step": 1, "msg": msg or f"HTTP {status}"}

        # ③ 微信端环境
        if index == 2:
            self.log("info", "③ 校验微信端环境（让服务端认为来自微信）")
            url = WEB_DICT["auth_check_api"].format(
                TASK_ID=self.task_id, STUDENT_ID=self.sid_int
            )
            status, data = self.http("GET", url, headers=self.signed_headers(url))
            if data.get("code") == 200:
                self.log("ok", "微信端环境校验通过")
                return {"success": True, "step": 3, "msg": ""}
            msg = str(data.get("msg") or "")
            if self.is_auth_fail(msg):
                return self.relogin(msg)
            self.log("warn", f"微信端环境校验失败：{msg or ('HTTP ' + str(status))}")
            return {"success": False, "step": 2, "msg": msg or f"HTTP {status}"}

        # ④ 打开签到时间窗口
        if index == 3:
            self.log("info", "④ 打开签到页面（写入访问日志）")
            url = WEB_DICT["api_log_api"]
            status, data = self.http("POST", url, headers=self.signed_headers(url))
            if status == 200:
                self.log("ok", "签到页面已打开")
                return {"success": True, "step": 4, "msg": ""}
            msg = str(data.get("msg") or "")
            self.log("warn", f"打开签到页面失败：{msg or ('HTTP ' + str(status))}")
            return {"success": False, "step": 3, "msg": msg or f"HTTP {status}"}

        # ⑤ 取宿舍登记位置
        if index == 4:
            self.log("info", "⑤ 获取你登记的宿舍位置")
            url = WEB_DICT["location_api"].format(
                TASK_ID=self.task_id, DATE=now_info()["date"]
            )
            status, data = self.http("GET", url, headers=self.signed_headers(url))
            if data.get("code") == 200:
                vo = (data.get("data") or {}).get("dormitoryRegisterVO") or {}
                try:
                    self.lat = float(vo.get("locationLat") or 0)
                    self.lng = float(vo.get("locationLng") or 0)
                except (TypeError, ValueError):
                    self.lat = self.lng = 0.0
                self.room_id = str(vo.get("roomId") or "")
                if not self.lat or not self.lng or not self.room_id:
                    self.log(
                        "err",
                        "没取到宿舍坐标/房间号（roomId 为空）：你名下可能没有宿舍登记，无法签到",
                    )
                    return {"success": False, "step": -1, "msg": "无宿舍登记"}
                self.log("ok", f"宿舍位置已获取（房间号 {self.room_id}）")
                return {"success": True, "step": 5, "msg": ""}
            msg = str(data.get("msg") or "")
            if self.is_auth_fail(msg):
                return self.relogin(msg)
            self.log("warn", f"获取宿舍位置失败：{msg or ('HTTP ' + str(status))}")
            return {"success": False, "step": 4, "msg": msg or f"HTTP {status}"}

        # ⑥ 提交签到
        if index == 5:
            delay = round(random.uniform(*self.sign_delay), 1)
            if delay > 0:
                self.log("info", f"⑥ 提交晚寝签到（等待 {delay:.1f} 秒，模拟人工）")
                time.sleep(delay)
            else:
                self.log("info", "⑥ 提交晚寝签到")
            url = WEB_DICT["sign_in_api"]
            status, data = self.http(
                "POST", url, json_body=self.sign_body(),
                headers=self.signed_headers(url)
            )
            msg = str(data.get("msg") or "")
            code = data.get("code")
            if code == 200 or "您今天已完成签到" in msg:
                extra = "（今天此前已经签过）" if "已完成" in msg else ""
                self.log("ok", f"签到成功{extra}")
                return {"success": True, "step": 6, "msg": ""}
            if self.is_auth_fail(msg):
                return self.relogin(msg)
            if "未到签到时间" in msg:
                self.log("err", "服务器提示「未到签到时间」，请在 21:20 之后再运行")
                return {"success": False, "step": -1, "msg": "未到签到时间"}
            if status == 200 and not msg:
                self.log("warn", "服务器返回空结果，无法确认是否成功，请到系统核实")
                return {"success": False, "step": -1, "msg": "结果未知", "unknown": True}
            self.log("warn", f"签到未成功：{msg or ('code=' + str(code))}")
            return {"success": False, "step": 5, "msg": msg or f"code={code}"}

        return {"success": False, "step": -1, "msg": "未知步骤"}

    # ---------- 结果核对 ----------

    def verify(self):
        try:
            url = WEB_DICT["unsigned_api"].format(
                TASK_ID=self.task_id, DATE=now_info()["date"]
            )
            _, data = self.http("GET", url, headers=self.signed_headers(url), timeout=20)
            text = json.dumps(data, ensure_ascii=False)
            if self.sid in text:
                self.log("warn", "附加核对：未签到名单（前 100 条）里仍能搜到你的学号，"
                                 "请务必到考勤系统确认！")
            else:
                self.log("info", "附加核对：未签到名单（前 100 条）里没有你的学号（仅供参考）")
        except Exception:
            pass

    # ---------- 主流程 ----------

    def run(self, dry_run=False):
        started = time.time()
        t = now_info()
        self.log("info", f"开始签到：学号 {self.sid}，{t['date']} {t['time']} {t['weekday']}")
        if t["time"] < SUGGEST_TIME:
            self.log("warn", f"现在是 {t['time']}，早于 {SUGGEST_TIME}，"
                             f"如果服务器还没开放时段会提示「未到签到时间」")
        step, retries, token_retries = 0, 0, 0
        errors = []
        unknown = False
        limit = 5 if dry_run else 6      # --test：只走到取位置，不提交
        while retries < self.MAX_RETRIES and 0 <= step < limit:
            result = self.step(step)
            step = result["step"]
            unknown = bool(result.get("unknown"))
            if not result["success"]:
                if result.get("msg"):
                    errors.append(result["msg"])
                if step == 0 and token_retries < self.MAX_TOKEN_RETRIES:
                    token_retries += 1
                else:
                    retries += 1
                if 0 <= step < limit:
                    time.sleep(round(random.uniform(*self.step_delay), 2))

        success = (step == limit)
        if success and not dry_run:
            self.verify()
        elapsed = time.time() - started
        self.log("info", f"总耗时 {elapsed:.1f} 秒")
        return {"success": success, "dry_run": dry_run, "unknown": unknown,
                "errors": errors, "elapsed": elapsed}


# ---------------------------------------------------------------- 供 Kivy 应用使用

def use_dir(path):
    """把配置/日志目录切到 App 私有目录（安卓上就是 /data/user/0/<包名>/files）。"""
    global APP_DIR, CONFIG_PATH, LOG_PATH
    os.makedirs(path, exist_ok=True)
    APP_DIR = path
    CONFIG_PATH = os.path.join(path, "签到配置.json")
    LOG_PATH = os.path.join(path, "签到日志.txt")
