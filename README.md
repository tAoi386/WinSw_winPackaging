# WinSw_winPackaging

[![Windows tests and build](https://github.com/tAoi386/WinSw_winPackaging/actions/workflows/windows.yml/badge.svg)](https://github.com/tAoi386/WinSw_winPackaging/actions/workflows/windows.yml)

基于 WinSW 的 Windows 服务可视化部署工具，用于管理多个 Java JAR 项目。当前版本 **0.3.1**。

## 功能

- 每个项目独立部署，支持 Windows 服务创建、启动、停止、重启和删除。
- 批量更新 JAR，保存任务完整源路径，更新前校验并等待服务停止。
- 实时 stdout / stderr 控制台，保留异常堆栈，独立查看 WinSW 诊断日志。
- 日志支持暂停、查找、清屏、UTF-8 / GB18030 切换和滚动文件读取。
- 默认保留最近 2,000 行，可增加到 100,000 行；完整磁盘日志可以打开目录查看。
- 单 EXE 发行，内置管理员权限声明，不依赖独立启动器或 Python 环境。

## 获取程序

进入 [GitHub Actions](https://github.com/tAoi386/WinSw_winPackaging/actions/workflows/windows.yml)，选择成功运行的构建，从 **Artifacts** 下载 `WinSw_winPackaging-Windows` 并解压，里面只有一个 `WinSw_winPackaging.exe`。下载 Actions artifact 通常需要登录 GitHub。

构建产物、历史备份、业务 JAR 和运行日志不提交到 Git。

## 使用

1. 将 `WinSw_winPackaging.exe` 复制到 Windows 服务器，双击确认管理员权限提示，或右键“以管理员身份运行”。
2. 打开“配置”，选择 JDK 的 `bin` 目录（包含 `java.exe`）、WinSW 可执行文件以及应用根目录。配置窗口支持从 GitHub 下载 WinSW。
3. 填写唯一服务ID、显示名称、JAR、端口和内存，创建后选中服务并启动。
4. 右侧控制台及“日志”页显示启动输出；“上传更新”页可批量替换 JAR。

服务器需安装适合业务 JAR 的 JDK，WinSW 的运行要求以所选版本为准。管理器 EXE 已包含 Python/Qt 环境。

设置存储在当前用户目录的 `.winsw-manager/config.json`。默认服务根目录为 `.winsw-manager/apps`；将应用根目录配置留空可恢复默认值。

```text
应用根目录/
└── myapp/
    ├── myapp.exe       # 此服务的 WinSW 包装器
    ├── myapp.xml
    ├── application.jar
    └── logs/
```

管理器本身只有一个 EXE；创建服务仍会生成各服务运行所需的文件。

## 操作说明

- **删除服务**仅停止选定服务，确认卸载后清理其目录；停止/卸载失败不继续删除，不使用全局 Java 进程终止命令。
- **更新 JAR**先校验再停止服务；停止失败不覆盖文件。原 XML 和已有同名 JAR 备份为 `.bak`，启动失败会显示错误。
- **更新 XML 配置**仅调整日志配置，保留 JDK、启动参数、环境变量和自定义节点。
- **清屏**不删除磁盘日志；**清空磁盘日志**会清空对应文件，执行前提示确认。
- **Running**是 Windows 服务状态，应用是否就绪请检查启动日志或业务健康检查。

WinSW 将 stdout 和 stderr 写入独立文件，无法恢复两路输出精确的原始交错顺序。历史按文件修改顺序加载，实时按观察顺序追加；滚动策略已经删除的历史无法恢复。应用若只写自定义业务日志文件，需要配置它同时输出到控制台。

## 开发和测试

Windows + Python **3.11 或更新版本**。CI 覆盖 Python 3.11 和 3.13。

```powershell
git clone https://github.com/tAoi386/WinSw_winPackaging.git
cd WinSw_winPackaging
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python main.py
```

实际管理 Windows 服务需要管理员权限。测试使用临时目录和模拟服务 API，不会启停或删除真实业务服务。

## 单文件打包

```powershell
python -m PyInstaller --noconfirm winsw.spec
python scripts/verify_build.py dist/WinSw_winPackaging.exe
```

生成 `dist/WinSw_winPackaging.exe`。验证脚本检查输出目录仅有单个 EXE、管理员权限声明和内置 Qt 环境。

推送 `main` 或提交 Pull Request 后自动执行 Windows 测试，通过后构建 EXE 并上传 Actions artifact。也支持在 Actions 页面手动运行。

## 项目结构

```text
core/              服务生命周期、日志读取、配置、WinSW 下载
ui/                PyQt5 窗口、控制台、后台任务
tests/             核心与 Qt 回归测试
scripts/           构建产物检查
.github/workflows/ Windows 自动测试与构建
main.py            应用入口
winsw.spec         单 EXE 打包配置
admin.manifest     管理员权限声明
```

## 变更与许可

详见 [CHANGELOG.md](CHANGELOG.md)。测试覆盖服务删除隔离、启停失败、JAR 回滚、日志轮转、配置保存失败等场景；真实业务 JAR 的服务器安装/卸载仍需实际环境验收。

本仓库保留原有 [Apache License 2.0](LICENSE)。第三方组件遵循各自许可，参见 [PyQt](https://www.riverbankcomputing.com/software/pyqt/)、[Qt](https://www.qt.io/)、[WinSW](https://github.com/winsw/winsw)；仓库许可证不替代依赖的许可证。
