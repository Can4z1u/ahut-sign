# AHUT 晚寝签到 · 安卓 APK（自带 Python 环境）

这个文件夹是一个**可以直接打出安卓 APK** 的完整工程：APK 里自带 Python 3 + Kivy，
装到手机上打开就能签到，**不需要装 Pydroid、Termux 或任何 Python**。

## 为什么要在云端打？

APK 必须用 Linux + Android SDK/NDK + python-for-android 编译。Windows 电脑上没有这些工具链，
所以这里用 **GitHub Actions 免费云构建**：上传代码 → 点一下 → 15~25 分钟后下载 APK。
全程不用装任何东西，也不用懂 Linux。

## 一、打出 APK（约 20 分钟，只需操作一次）

1. 注册/登录 [GitHub](https://github.com)（免费）。
2. 右上角 **+ → New repository**，名字随便填（例如 `ahut-sign`），选 **Private** 或 Public，
   然后 **Create repository**。
3. 在新仓库页面点 **uploading an existing file**，把本文件夹里的**全部内容**拖进去
   （包括 `.github` 文件夹，它是隐藏的，在 Windows 里需要开启"显示隐藏项目"才能看到）；
   点 **Commit changes**。
4. 打开仓库顶部的 **Actions** 标签 → 左侧 **Build Android APK** → 右侧 **Run workflow** → 绿色按钮。
5. 等 15~25 分钟（第一次下载 NDK 会久一点），刷新页面，点进这次运行，页面底部
   **Artifacts** 里下载 `ahut-sign-apk`，解压得到 `ahutsign-1.0-...-debug.apk`。
6. 把 APK 传到手机（微信/QQ/USB 都行）→ 点击安装 → 允许"安装未知来源应用"。

> 构建失败的话，点开失败的那一步看日志，多半是网络抖动，重新 Run 一次即可。

## 二、手机上的使用

1. 打开「AHUT 晚寝签到」；
2. 填学号（会记住），密码没改过就留空；
3. 点 **开 始 签 到**，1~3 秒看到 `✔ 流程结束：签到成功`；
4. 21:20 之后才能签，早了会提示「未到签到时间」。

## 三、工程结构

| 文件 | 说明 |
|---|---|
| `main.py` | Kivy 界面（学号、密码、按钮、日志） |
| `signer.py` | 签到逻辑：登录、签名、六步、重试、IPv4 优先（与电脑版同一套） |
| `buildozer.spec` | 打包配置（包名 `org.ahut.ahutsign`，需要 INTERNET 权限） |
| `.github/workflows/build-apk.yml` | 云端构建脚本 |

## 四、已知情况

- APK 约 40 MB，第一次启动要 5~10 秒（解压 Python 环境），之后正常；
- 用的是 **debug 签名**，自己安装没问题，但**不能上架应用商店**；
- 手机系统可能限制后台，切到别的应用太久会被杀（签到时别切走）；
- 中文字体借用系统自带字体（`/system/fonts/NotoSansCJK-Regular.ttc` 等），绝大多数安卓机都有；
- 想改包名/图标：改 `buildozer.spec` 里的 `package.name`、`package.domain`，图标放 `icon.png` 并加
  `icon.filename = %(source.dir)s/icon.png`。

## 五、如果你有 Linux 云服务器（不用 GitHub）

```bash
sudo apt update && sudo apt install -y python3-pip openjdk-17-jdk unzip git
pip install buildozer cython
git clone <你的仓库> && cd ahut-sign
buildozer android debug          # 产物在 bin/*.apk
```

## 六、更快的替代方案（不想等 20 分钟）

- **Pydroid 3**：手机装 Pydroid 3，把 `签到.py` 拷进去点运行，5 分钟能用（需要 Python App）；
- **Termux + Termux:Widget**：桌面一键按钮（见根目录 `安卓安装说明.md`）。

区别：本工程的 APK 是「装完即用、桌面上就是一个图标」；上面两个方案要先装一个 Python App。
