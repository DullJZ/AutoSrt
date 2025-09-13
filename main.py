import os
import sys
import subprocess
import json
import argparse
import tempfile
from groq import Groq

GROQ_API_KEY = "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"

def extract_audio(video_path, audio_path):
    # 使用 ffmpeg 提取音频
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "mp3", audio_path
    ]
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

def burn_subtitles(video_path, srt_path, out_path):
    """使用 ffmpeg 将 SRT 烧录到视频中，生成 out_path。"""
    # 使用字幕过滤烧录（ass/utf-8 支持取决于 ffmpeg 构建），这里强制转码 srt 为 UTF-8 临时文件以保证兼容性
    tmp_srt = srt_path + ".utf8.srt"
    try:
        with open(srt_path, "r", encoding="utf-8", errors="replace") as src, open(tmp_srt, "w", encoding="utf-8") as dst:
            dst.write(src.read())

        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"subtitles={tmp_srt}",
            "-c:a", "copy",
            out_path
        ]
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

    cmd = [
        'ffmpeg', '-y', '-i', video_path, '-i', srt_path,
        '-map', '0', '-map', '1',
        '-c:v', 'copy', '-c:a', 'copy',
    ] + map_sub + [out_path]

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
    args = parser.parse_args()
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
            extract_audio(video_path, audio_path)
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
                            burn_subtitles(video_path, srt_path, tmp_path)
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
                        burn_subtitles(video_path, srt_path, subbed_out)
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
                        burn_subtitles(video_path, srt_path, burned_name)
                        print(f"  已生成带烧录字幕视频: {burned_name}")
            except Exception as e:
                print(f"  嵌入字幕时出错: {e}")
        except Exception as e:
            print(f"处理 {video_path} 时发生错误: {e}")

if __name__ == "__main__":
    main()