import os
import time
import subprocess
import re
import sys 
from pathlib import Path  
import yt_dlp
from utils import hms_to_seconds, seconds_to_hms, parse_ffmpeg_time, run_ffprobe, STARTUPINFO

# === ОБРЕЗКА (CUT) ===
def cut_worker(files, start_str, end_str, suffix, queue, cancel_event):
    total = len(files)
    start_sec = hms_to_seconds(start_str)
    end_sec = hms_to_seconds(end_str)
    dur = end_sec - start_sec

    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent
    
    ffmpeg_exe = str((base_path / "ffmpeg" / "bin" / "ffmpeg.exe").absolute())

    if dur <= 0:
        queue.put(("cut", "error", "Конечное время должно быть больше начального"))
        return

    for idx, path in enumerate(files, start=1):
        if cancel_event.is_set():
            queue.put(("cut", "status", "Операция отменена"))
            return

        queue.put(("cut", "update_index", (idx, total)))
        folder, fname = os.path.split(path)
        name, ext = os.path.splitext(fname)
        outname = os.path.join(folder, f"{name}{suffix}{ext}")

        cmd = [
            ffmpeg_exe, "-hide_banner", "-y",
            "-ss", start_str, "-i", path,
            "-t", seconds_to_hms(dur),
            "-c", "copy", "-map_metadata", "-1", outname
        ]

        try:
            proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True, startupinfo=STARTUPINFO)
            while True:
                if cancel_event.is_set():
                    proc.terminate()
                    queue.put(("cut", "status", "Обрезка прервана"))
                    return
                line = proc.stderr.readline()
                if not line:
                    if proc.poll() is not None: break
                    time.sleep(0.05)
                    continue
                cur = parse_ffmpeg_time(line)
                if cur is not None:
                    pct = (cur - start_sec) / dur * 100 if dur > 0 else 0
                    queue.put(("cut", "progress", int(pct)))
            queue.put(("cut", "progress", 100))
        except Exception as e:
            queue.put(("cut", "error", str(e)))
            continue
    queue.put(("cut", "done", None))

# === КОНВЕРТАЦИЯ (CONVERT) ===
def convert_worker(files, settings, queue, cancel_event):
    total = len(files)
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent
    
    ffmpeg_exe = str((base_path / "ffmpeg" / "bin" / "ffmpeg.exe").absolute())

    for idx, path in enumerate(files, start=1):
        if cancel_event.is_set():
            queue.put(("conv", "status", "Операция отменена"))
            return

        queue.put(("conv", "update_index", (idx, total)))
        folder, fname = os.path.split(path)
        name, ext = os.path.splitext(fname)
        outname = os.path.join(folder, f"{name}{settings.get('suffix')}.{settings.get('out_format')}")

        probe = run_ffprobe(path)
        dur = float(probe.get("format", {}).get("duration", 0))
        
        # Настройки видео/аудио
        cmd = [ffmpeg_exe, "-hide_banner", "-y", "-i", path, "-c:v", "libx264", "-movflags", "+faststart"]
        
        # Защита от нечетных разрешений (pad)
        res_mode = settings.get('resolution')
        if res_mode and res_mode != "copy":
            if ":-1" in res_mode:
                size = res_mode.split(":")[0]
                cmd += ["-vf", f"scale='trunc(oh*a/2)*2:{size}'" if "height" in res_mode else f"scale='{size}:trunc(ow/a/2)*2'"]
            else:
                cmd += ["-vf", f"scale={res_mode}:force_original_aspect_ratio=decrease,pad='ceil(iw/2)*2:ceil(ih/2)*2'"]

        cmd += ["-map_metadata", "-1", outname]

        try:
            proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True, startupinfo=STARTUPINFO)
            while True:
                if cancel_event.is_set():
                    proc.terminate()
                    return
                line = proc.stderr.readline()
                if not line:
                    if proc.poll() is not None: break
                    continue
                cur = parse_ffmpeg_time(line)
                if cur is not None and dur > 0:
                    queue.put(("conv", "progress", int((cur / dur) * 100)))
            queue.put(("conv", "progress", 100))
        except Exception as e:
            queue.put(("conv", "error", str(e)))
    queue.put(("conv", "done", None))

# === ЗАГРУЗКА (YOUTUBE) ===
def download_worker(url, folder, queue, cancel_event):
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent

    # Пути
    ffmpeg_bin_dir = (base_path / "ffmpeg" / "bin").absolute()
    ffmpeg_exe = (ffmpeg_bin_dir / "ffmpeg.exe").absolute()
    
    # 1. Принудительно добавляем путь в PATH текущего процесса
    os.environ["PATH"] = str(ffmpeg_bin_dir) + os.pathsep + os.environ.get("PATH", "")

    class MyLogger:
        def debug(self, msg): 
            if cancel_event.is_set(): raise Exception("CANCELED")
        def info(self, msg): print(f"[INFO] {msg}")
        def warning(self, msg): print(f"[WARN] {msg}")
        def error(self, msg): print(f"[ERR] {msg}")

    def progress_hook(d):
        if cancel_event.is_set(): raise Exception("CANCELED")
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%').replace('%','')
            try:
                queue.put(("dl", "progress", int(float(p))))
                queue.put(("dl", "status", f"Загрузка: {p}% | {d.get('_speed_str','?') }"))
            except: pass

    ydl_opts = {
        # Передаем ПРЯМОЙ путь к файлу ffmpeg.exe, а не к папке
        'ffmpeg_location': str(ffmpeg_exe),
        # Смягчаем формат: ищем лучший mp4, если нет - любой лучший слиянием
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': os.path.join(folder, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'progress_hooks': [progress_hook],
        'logger': MyLogger(),
        'nocheckcertificate': True,
        'quiet': False
    }

    try:
        queue.put(("dl", "status", "Запуск..."))
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        queue.put(("dl", "done", None))
    except Exception as e:
        status = "Отменено" if "CANCELED" in str(e) else f"Ошибка: {str(e)}"
        queue.put(("dl", "error", status))