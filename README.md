# AutoSrt

## 概要

`AutoSrt` 是一个用于将视频自动转录并将字幕烧录到视频中的小型脚本。它会：

- 提取视频中的音频（使用 `ffmpeg`）。
- 调用 Groq 音频转录服务生成带时间戳的转录结果。
- 将转录结果转换为标准 SRT 文件。
- 使用 `ffmpeg` 将 SRT 烧录（硬字幕）回视频。

该脚本支持单文件处理、批量处理（当未提供输入文件时会扫描当前目录）以及可选的原文件覆盖（`--overwrite`）。

## 功能亮点

- 自动将转录结果导出为 `.srt`。
- 默认输出到仓库根目录下的 `output/`（文件名与原视频相同）。
- 可选 `--overwrite`：在生成成功后原子替换原视频文件（在源文件同目录创建临时文件再用 `os.replace` 替换）。
- 批量处理：当不指定输入文件时，会扫描当前目录并处理常见视频格式：`.mp4, .mkv, .mov, .avi, .flv, .webm`。
- 转录重试机制：网络请求失败时自动重试，最多3次，带渐进式等待时间。
- 智能硬件加速：自动检测系统硬件（NVIDIA/AMD/Intel GPU）并启用相应的硬件加速编码（NVENC/QSV/VAAPI/VideoToolbox）。

## 要求

- Python 3.x
- `ffmpeg`（需在 `PATH` 中）
- 网络连接（用于调用 Groq API）
- Python 依赖：`groq`（或你使用的转录客户端）

## 安装示例

macOS (Homebrew)：

```bash
brew install ffmpeg
pip3 install groq
```

或使用你的虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 使用说明

处理单个文件（输出到 `output/`）：

```bash
python3 main.py "your_video.mp4"
```

覆盖原视频（危险，建议先备份）：

```bash
python3 main.py --overwrite "your_video.mp4"
```

批量处理当前目录下所有支持的文件：

```bash
python3 main.py
```

批量处理并覆盖原视频（非常危险，慎用）：

```bash
python3 main.py --overwrite
```

## CLI 参数

- `video_file` (optional): 指定要处理的单个视频文件路径。如果省略，脚本会处理当前目录下所有支持的文件。
- `--overwrite`: 若设置，生成的视频将覆盖原视频（使用临时文件后原子替换）。
- `--embed-mode`: 指定字幕嵌入模式，可选值：
	- `burn`（默认）：将字幕烧录（硬字幕）到视频画面中。
	- `soft`：将 SRT 作为外挂字幕轨道加入到输出容器（不烧录，用户可在播放器中开关字幕）。
	- `both`：同时生成一个外挂字幕容器以及一个烧录字幕的版本（烧录文件名会带 `_burned` 后缀）。
- `--no-hwaccel`: 禁用硬件加速，使用软件编码（默认启用硬件加速）。

