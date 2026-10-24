[app]

# 应用名（显示在手机桌面上）
title = AHUT 晚寝签到

# 包名：org.ahut.ahutsign，改 domain 可避免和别人的应用冲突
package.name = ahutsign
package.domain = org.ahut

# 源码目录就是本文件夹
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,otf,txt,json

version = 1.1

# certifi 负责 HTTPS 证书；openssl 让 Python 的 ssl/urllib 能走 https
# charset-normalizer 必须固定在 3.3.2：
#   3.5.x 开始发布 android_24_arm64_v8a 专用轮子，而 p4a 最后装包时没带 --platform，
#   pip 会判定"不支持当前平台"直接失败（日志里的 charset_normalizer-...-android_24...whl）。
#   3.3.2 还有 py3-none-any 通用轮子，p4a 走纯 Python 路径即可正常安装。
requirements = python3,kivy,certifi,openssl,charset-normalizer==3.3.2

# 竖屏
orientation = portrait
fullscreen = 0

# 需要联网
android.permissions = INTERNET

# 保留返回键/后台行为由 Kivy 处理
android.allow_backup = True

# 兼容老机型
android.minapi = 24
android.api = 34
android.ndk = 25b

# 只打 arm64（近几年的手机都是 arm64），构建时间和 APK 体积都能少一半
android.archs = arm64-v8a

# 自动接受 Android SDK 许可（云构建需要）
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
