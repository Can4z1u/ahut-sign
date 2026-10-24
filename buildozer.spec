[app]

# 应用名（显示在手机桌面上）
title = AHUT 晚寝签到

# 包名：org.ahut.ahutsign，改 domain 可避免和别人的应用冲突
package.name = ahutsign
package.domain = org.ahut

# 源码目录就是本文件夹
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,otf,txt,json

version = 1.0

# certifi 负责 HTTPS 证书；openssl 让 Python 的 ssl/urllib 能走 https
requirements = python3,kivy,certifi,openssl

# 竖屏
orientation = portrait
fullscreen = 0

# 需要联网
android.permissions = INTERNET

# 保留返回键/后台行为由 Kivy 处理
android.allow_backup = True

# 兼容老机型
android.minapi = 21

# 自动接受 Android SDK 许可（云构建需要）
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
