import os
import sys
import subprocess
import json
import argparse
import tempfile
import platform
from groq import Groq

GROQ_API_KEY = "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"




def get_video_info(video_path):
    """获取视频文件信息，包括码率、时长等"""
    try:
        # 使用 ffprobe 获取视频信息
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=bit_rate,duration,width,height",
            "-of", "json", video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            info = json.loads(result.stdout)
            if "streams" and len(info["streams"]) > 0:
                stream = info["streams"][0]
                bitrate = int(stream.get("bit_rate", 0))
                duration = float(stream.get("duration", 0))
                width = int(stream.get("width", 0))
                height = int(stream.get("height", 0))

                # 如果码率为0，尝试从格式信息获取
                if bitrate == 0:
                    cmd2 = ["ffprobe", "-v", "error", "-show_entries", "format=bit_rate",
                           "-of", "json", video_path]
                    result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=30)
                    if result2.returncode == 0:
                        format_info = json.loads(result2.stdout)
                        bitrate = int(format_info.get("format", {}).get("bit_rate", 0))

                return {
                    "bitrate": bitrate,
                    "duration": duration,
                    "width": width,
                    "height": height,
                    "size": os.path.getsize(video_path) if os.path.exists(video_path) else 0
                }
    except Exception as e:
        print(f"获取视频信息失败: {e}")

    return None

def calculate_bitrate(video_info):
    """根据视频信息和目标质量计算合适的输出码率"""
    if not video_info or video_info["duration"] == 0:
        return None

    original_bitrate = video_info["bitrate"]

    # 如果无法获取原始码率，使用基于分辨率的默认码率
    if original_bitrate == 0:
        resolution = video_info["width"] * video_info["height"]
        if resolution >= 3840 * 2160:  # 4K
            original_bitrate = 20_000_000  # 20 Mbps
        elif resolution >= 1920 * 1080:  # 1080p
            original_bitrate = 8_000_000  # 8 Mbps
        elif resolution >= 1280 * 720:  # 720p
            original_bitrate = 4_000_000  # 4 Mbps
        else:
            original_bitrate = 2_000_000  # 2 Mbps

    # 根据分辨率调整目标码率
    if video_info["width"] * video_info["height"] >= 3840 * 2160:  # 4K
        target_bitrate = original_bitrate
        max_bitrate = target_bitrate * 1.2
        buffer_size = max_bitrate * 0.5
    elif video_info["width"] * video_info["height"] >= 1920 * 1080:  # 1080p
        target_bitrate = original_bitrate
        max_bitrate = target_bitrate * 1.2
        buffer_size = max_bitrate * 0.5
    else:
        target_bitrate = original_bitrate
        max_bitrate = target_bitrate * 1.2
        buffer_size = max_bitrate * 0.5

    return {
        "bitrate": int(target_bitrate),
        "max_bitrate": int(max_bitrate),
        "buffer_size": int(buffer_size)
    }

def get_ffmpeg_hwaccel_args(no_hwaccel=False):
    if no_hwaccel:
        return []

    system = platform.system()
    if system == "Linux":
        # Linux系统使用AMD/NVIDIA/Intel GPU加速
        return ["-hwaccel", "auto"]
    elif system == "Windows":
        # Windows系统使用GPU加速
        return ["-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11"]
    elif system == "Darwin":  # macOS
        # macOS使用VideoToolbox硬件加速
        return ["-hwaccel", "videotoolbox"]
    else:
        # 其他系统不启用硬件加速
        return []

def test_ffmpeg_hwaccel():
    """测试ffmpeg硬件加速是否可用"""
    try:
        # 尝试使用硬件加速执行一个简单的命令
        test_cmd = ["ffmpeg", "-hwaccels"]
        result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and "videotoolbox" in result.stdout or "cuda" in result.stdout or "qsv" in result.stdout:
            return True
    except:
        pass
    return False

def extract_audio(video_path, audio_path, no_hwaccel=False):
    # 使用 ffmpeg 提取音频（可选择硬件加速）
    hwaccel_args = get_ffmpeg_hwaccel_args(no_hwaccel)
    cmd = ["ffmpeg", "-y"] + hwaccel_args + ["-i", video_path]
    # 音频处理不使用硬件加速以保证兼容性
    cmd.extend(["-vn", "-acodec", "mp3", "-q:a", "2", audio_path])
    subprocess.run(cmd, check=True)

def transcribe(audio_path):
    client = Groq(api_key=GROQ_API_KEY)
    with open(audio_path, "rb") as file:
        transcription = client.audio.transcriptions.create(
            file=file,
            model="whisper-large-v3-turbo",
            language="zh",
            response_format="verbose_json",
            timestamp_granularities=["segment"],
            temperature=0.0
        )
    return transcription

def srt_timestamp(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def save_srt(transcription, srt_path):
    segments = transcription.segments
    with open(srt_path, "w", encoding="utf-8") as f:
        for idx, seg in enumerate(segments, 1):
            start = srt_timestamp(seg["start"])
            end = srt_timestamp(seg["end"])
            text = seg["text"].strip()
            f.write(f"{idx}\n{start} --> {end}\n{text}\n\n")


def burn_subtitles(video_path, srt_path, out_path, no_hwaccel=False):
    """使用 ffmpeg 将 SRT 烧录到视频中，生成 out_path。"""

    # 获取原视频信息用于码率计算
    video_info = get_video_info(video_path)
    if video_info:
        print(f"原视频信息: 分辨率 {video_info['width']}x{video_info['height']}, "
              f"码率: {video_info['bitrate']//1000 if video_info['bitrate'] > 0 else '未知'} kbps, "
              f"大小: {video_info['size']/1024/1024:.1f} MB")

    # 根据原视频计算输出码率
    bitrate_settings = calculate_bitrate(video_info) if video_info else None

    # 使用字幕过滤烧录（ass/utf-8 支持取决于 ffmpeg 构建），这里强制转码 srt 为 UTF-8 临时文件以保证兼容性
    tmp_srt = srt_path + ".utf8.srt"
    try:
        with open(srt_path, "r", encoding="utf-8", errors="replace") as src, open(tmp_srt, "w", encoding="utf-8") as dst:
            dst.write(src.read())
        # ffmpeg 字幕过滤器期望一个可能包含特殊字符的路径
        # 对于 Windows 路径（包含反斜杠和冒号），我们需要转义
        # 反斜杠和冒号，并且在使用 -vf 传递时需要用单引号包裹整个参数
        # 示例: subtitles='E\:\\path\\to\\file.srt'
        def escape_subtitles_path(p):
            # ffmpeg 过滤器解析：转义反斜杠和冒号
            escaped = p.replace("\\", "\\\\")
            escaped = escaped.replace(":", "\\:")
            # 同样转义单引号，通过关闭和使用 '\'' 序列
            if "'" in escaped:
                escaped = escaped.replace("'", "\\'")
            return escaped

        # Use absolute path for safety
        abs_tmp = os.path.abspath(tmp_srt)
        vf_arg = f"subtitles='{escape_subtitles_path(abs_tmp)}'"

        hwaccel_args = get_ffmpeg_hwaccel_args(no_hwaccel)
        cmd = ["ffmpeg", "-y"] + hwaccel_args + ["-i", video_path]
        # 仅在未禁用硬件加速的情况下使用硬件加速编码
        if not no_hwaccel:
            # 设置视频编码器使用硬件加速（如果系统支持）
            system = platform.system()
            if system == "Linux":
                # Linux使用硬件加速编码
                cmd.extend(["-c:v", "h264_nvenc" if "nvidia" in " ".join(hwaccel_args) else "h264_vaapi"])
            elif system == "Windows":
                # Windows使用硬件加速编码
                cmd.extend(["-c:v", "h264_qsv"])  # Intel QSV (快速解码重编码)
            elif system == "Darwin":  # macOS
                # macOS使用硬件加速编码
                cmd.extend(["-c:v", "h264_videotoolbox"])
            else:
                # 其他系统使用软件编码
                cmd.extend(["-c:v", "libx264"])
        else:
            # 软件编码
            cmd.extend(["-c:v", "libx264"])

        # 设置视频码率参数（基于原视频码率计算）
        if bitrate_settings:
            cmd.extend([
                "-b:v", f"{bitrate_settings['bitrate'] // 1000}k",
                "-maxrate", f"{bitrate_settings['max_bitrate'] // 1000}k",
                "-bufsize", f"{bitrate_settings['buffer_size'] // 1000}k"
            ])
            print(f"设置视频码率: {bitrate_settings['bitrate'] // 1000} kbps (最大: {bitrate_settings['max_bitrate'] // 1000} kbps)")
        else:
            # 默认设置（如果无法获取原视频信息）
            cmd.extend([
                "-crf", "23",  # 默认质量参数
                "-preset", "medium"  # 编码速度和质量的平衡
            ])

        cmd.extend(["-vf", vf_arg, "-c:a", "copy", out_path])
        print(f"执行命令: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        print(f"已生成带字幕视频: {out_path}")
    except subprocess.CalledProcessError as e:
        print(f"烧录字幕失败: {e}")
    except Exception as e:
        print(f"处理字幕或输出时出错: {e}")
    finally:
        # 清理临时 srt
        try:
            if os.path.exists(tmp_srt):
                os.remove(tmp_srt)
        except Exception:
            pass

def find_videos_in_cwd():
    exts = {'.mp4', '.mkv', '.mov', '.avi', '.flv', '.webm'}
    files = []
    for f in sorted(os.listdir(os.getcwd())):
        if os.path.isfile(f) and os.path.splitext(f)[1].lower() in exts:
            files.append(os.path.abspath(f))
    return files


def embed_soft_subtitles(video_path, srt_path, out_path):
    """将 SRT 作为外挂字幕轨道添加到视频容器中（不烧录）。
    通过 ffmpeg 将原始视频复制流并将 srt 以字幕流形式加入输出文件。
    注意：目标容器需支持字幕流（例如 mp4 可能需要 mov_text 或使用 mkv）。
    """
    _, ext = os.path.splitext(out_path)
    ext = ext.lower()

    # 选择合适的字幕 codec
    if ext in ('.mp4', '.mov'):
        # mov_text 是 mp4/mov 的常见内置字幕格式
        subtitle_codec = 'mov_text'
        map_sub = ['-c:s', subtitle_codec]
    elif ext in ('.mkv', '.webm'):
        # mkv 支持 srt 编码为 srt
        map_sub = ['-c:s', 'srt']
    else:
        map_sub = ['-c:s', 'mov_text']

    # 使用硬件加速进行软字幕嵌入
    hwaccel_args = get_ffmpeg_hwaccel_args()
    cmd = ["ffmpeg", "-y"] + hwaccel_args + ["-i", video_path, "-i", srt_path]
    cmd.extend([
        "-map", "0", "-map", "1",
        # 视频流复制（保持原始编码），但使用硬件加速处理
        "-c:v", "copy",
        "-c:a", "copy",
    ] + map_sub + [out_path])

    try:
        subprocess.run(cmd, check=True)
        print(f"已将外挂字幕添加到: {out_path}")
    except subprocess.CalledProcessError as e:
        print(f"添加外挂字幕失败: {e}")

def main():
    parser = argparse.ArgumentParser(description="Extract audio, transcribe and burn subtitles into a video.")
    parser.add_argument("video_file", nargs='?', help="Path to the input video file (optional). If omitted, process all videos in current directory.")
    parser.add_argument("--overwrite", action="store_true", help="If set, overwrite the original video with the subtitled version (safe replace)")
    parser.add_argument("--embed-mode", choices=["burn", "soft", "both"], default="burn",
                        help="Subtitle embedding mode: 'burn' = hardcode subtitles into video (default), 'soft' = add as separate subtitle track, 'both' = generate both.")
    parser.add_argument("--no-hwaccel", action="store_true", help="Disable hardware acceleration")
    args = parser.parse_args()

    # 检测和打印硬件加速状态
    has_hwaccel_support = test_ffmpeg_hwaccel()
    if args.no_hwaccel:
        print("已禁用硬件加速")
    elif has_hwaccel_support:
        print(f"检测到硬件加速支持 ({platform.system()})")
    else:
        print("未检测到硬件加速支持，使用软件处理")
    targets = []
    if args.video_file:
        targets = [args.video_file]
    else:
        targets = find_videos_in_cwd()
        if not targets:
            print("当前目录下未找到视频文件。")
            return

    for video_path in targets:
        print(f"处理: {video_path}")
        base = os.path.splitext(video_path)[0]
        audio_path = base + ".mp3"
        srt_path = base + ".srt"

        try:
            print("  正在提取音频...")
            extract_audio(video_path, audio_path, args.no_hwaccel)
            print("  正在转录...")
            transcription = transcribe(audio_path)
            print("  正在保存 SRT 字幕...")
            save_srt(transcription, srt_path)
            print(f"  SRT 字幕已保存到: {srt_path}")

            # 删除临时音频文件
            try:
                if os.path.exists(audio_path):
                    os.remove(audio_path)
                    print(f"  临时音频文件已删除: {audio_path}")
            except Exception as e:
                print(f"  删除临时音频文件时出错: {e}")

            # 嵌入或添加外挂字幕到视频（根据 --embed-mode 决定行为）
            try:
                if args.overwrite:
                    dir_name = os.path.dirname(video_path) or "."
                    tmp_fd, tmp_path = tempfile.mkstemp(prefix=".subbed_tmp_", suffix=os.path.splitext(video_path)[1], dir=dir_name)
                    os.close(tmp_fd)
                    try:
                        if args.embed_mode in ("burn", "both"):
                            burn_subtitles(video_path, srt_path, tmp_path, args.no_hwaccel)
                        else:
                            embed_soft_subtitles(video_path, srt_path, tmp_path)
                        os.replace(tmp_path, video_path)
                        print(f"  已覆盖原视频: {video_path}")
                    except Exception:
                        try:
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                        except Exception:
                            pass
                        raise
                else:
                    out_dir = os.path.join(os.getcwd(), "output")
                    try:
                        os.makedirs(out_dir, exist_ok=True)
                    except Exception:
                        pass
                    original_name = os.path.basename(video_path)
                    subbed_out = os.path.join(out_dir, original_name)
                    if args.embed_mode == "burn":
                        burn_subtitles(video_path, srt_path, subbed_out, args.no_hwaccel)
                        print(f"  已生成带字幕视频 (烧录): {subbed_out}")
                    elif args.embed_mode == "soft":
                        embed_soft_subtitles(video_path, srt_path, subbed_out)
                        print(f"  已生成带外挂字幕视频: {subbed_out}")
                    else:  # both
                        # 先产出带外挂字幕的容器
                        embed_soft_subtitles(video_path, srt_path, subbed_out)
                        print(f"  已生成带外挂字幕视频: {subbed_out}")
                        # 再产出烧录版本，带后缀以免覆盖
                        burned_name = os.path.join(out_dir, os.path.splitext(original_name)[0] + "_burned" + os.path.splitext(original_name)[1])
                        burn_subtitles(video_path, srt_path, burned_name, args.no_hwaccel)
                        print(f"  已生成带烧录字幕视频: {burned_name}")
            except Exception as e:
                print(f"  嵌入字幕时出错: {e}")
        except Exception as e:
            print(f"处理 {video_path} 时发生错误: {e}")

if __name__ == "__main__":
    main()