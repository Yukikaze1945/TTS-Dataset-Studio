# TTS Dataset Studio

[English](README.en.md) · 简体中文

TTS Dataset Studio 是一个面向 Windows 的轻量 TTS 素材截取与字幕整理工作站。
它把音视频导入、波形预览、多字幕轨、非破坏区间、增益控制和 FFmpeg 导出放在
同一个界面中，目标是让“随手截一句可训练语音”不再需要启动完整视频剪辑软件。

> 当前版本：`v0.1.0-alpha.1`。这是预发布版本，请在重要操作前保存工程。

## 主要功能

- 拖入视频或音频，自动关联同目录下的 SRT、ASS 和 VTT 字幕。
- mpv 视频预览、纯音频波形预览以及可缩放多字幕轨时间线。
- 字幕和导出区间自由调整，支持多选、吸附、撤销与重做。
- WAV、FLAC、MP3 导出，支持采样率、声道、位深、增益、淡入淡出和命名模板。
- 字幕文本自动命名音频并可生成同名 UTF-8 TXT。
- D/F 逐帧移动、C 保存原视频静帧、Windows 右键菜单安装。
- 可选接入 MOSS-Transcribe-Diarize，对选中区间生成时间戳和说话人字幕。

## 安装

### Windows 便携版

从 [Releases](https://github.com/Yukikaze1945/TTS-Dataset-Studio/releases) 下载
`TTS-Dataset-Studio-*-windows-x64.zip`，解压后直接运行
`TTS Dataset Studio.exe`。便携包已经包含 FFmpeg、ffprobe 和 mpv。

如需开始菜单快捷方式和 Win11 文件右键菜单，在解压目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\Install.ps1
```

### 从源码启动

要求 Windows 10/11 x64、Python 3.11–3.14、[uv](https://docs.astral.sh/uv/)；
FFmpeg/ffprobe 必须位于 `PATH`，mpv 可选。

```powershell
git clone https://github.com/Yukikaze1945/TTS-Dataset-Studio.git
cd TTS-Dataset-Studio
uv sync --extra dev --frozen
uv run tts-dataset-studio
```

## 基础工作流

1. 将视频或音频拖入素材库或时间轴。
2. 点击字幕，或使用 `I` / `O` 创建导出区间。
3. 拖动字幕或区间边缘修正时间；在右侧调整增益和导出预设。
4. 按 `E` 导出音频和可选 TXT。
5. 使用 `Ctrl+S` 保存 `.ttds` 工程；原媒体和原字幕不会被修改。

## 快捷键

| 快捷键 | 功能 |
| --- | --- |
| Space | 播放/暂停 |
| I / O | 设置入点/出点 |
| Enter | 播放当前字幕或区间 |
| E | 按当前预设导出 |
| X | 删除选中的导出区间 |
| D / F | 上一帧/下一帧 |
| C | 保存当前原视频静帧 |
| G | 使用选中区间和导出字幕轨生成 IndexTTS2 语音 |
| Ctrl+S | 保存工程 |
| Ctrl+Z / Ctrl+Shift+Z | 撤销/重做 |
| Alt+滚轮 | 缩放时间线 |
| ? | 显示快捷键帮助 |

## MOSS ASR（可选）

MOSS、PyTorch 和模型权重不包含在仓库或便携包中。准备好
[MOSS-Transcribe-Diarize](https://github.com/OpenMOSS/MOSS-Transcribe-Diarize)
环境后，可通过以下任一方式让软件发现它：

1. 设置环境变量 `MOSS_TRANSCRIBE_DIARIZE_HOME`。
2. 放在任意磁盘的 `moss-asr\MOSS-Transcribe-Diarize`。
3. 在“文件 → 高级设置 → ASR”中手动选择目录、Python 和模型。

加载模型后，选择一个或多个导出区间并点击“识别选中片段”。取消识别不会卸载模型。

## IndexTTS2 语音引擎（可选）

IndexTTS2、PyTorch、CUDA 和模型权重不会上传到仓库，也不会打进便携版。软件按以下顺序发现外部环境：

1. 环境变量 `INDEX_TTS_HOME`。
2. 用户目录或程序相邻目录下的 `index-tts`。
3. Windows 固定磁盘根目录下的 `index-tts`。
4. “文件 → 高级设置 → 语音引擎”中手动指定的目录。

默认环境布局为：

```text
index-tts/
├── .venv/Scripts/python.exe
├── indextts/infer_v2.py
└── checkpoints/config.yaml
```

加载语音引擎后，指定一个导出字幕轨并选择一个或多个区间，按 `G` 即可用每个区间的原始声音作为参考音频生成语音。生成结果会加入“AI 生成”音轨；该音轨支持移动、非破坏裁边、删除、撤销/重做以及 Mute/Solo 同步试听。工程保存后，生成文件位于同名 `.ttds.assets/generated` 目录。

可执行本机 GPU 冒烟测试：

```powershell
.\scripts\index-tts-smoke.ps1 -IndexTtsRoot X:\index-tts
```

## 开发与测试

```powershell
uv sync --extra dev --frozen
uv run ruff check src tests
uv run pytest
```

构建完整便携包：

```powershell
.\scripts\fetch-runtime.ps1
.\scripts\build-release.ps1 -Version 0.1.0-alpha.1
```

## 已知限制

- 首发仅支持 Windows 10/11 x64。
- 单个时间线只打开一个源素材，不支持素材拼接、转场或视频成片导出。
- MOSS ASR 依赖用户自己的 Python/CUDA/模型环境。
- IndexTTS2 依赖用户自己的 Python/CUDA/模型环境；便携版只包含协议 worker。
- V1 不包含降噪、说话人分离、质量评分和训练框架专用 metadata。

## 许可证

项目源码采用 [MIT License](LICENSE)。便携版包含的 Qt/PySide6、FFmpeg、mpv
及其他组件遵循各自许可证，详见 [第三方声明](THIRD_PARTY_NOTICES.md)。
