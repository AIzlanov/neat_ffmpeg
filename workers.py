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

    # Находим путь к ffmpeg для портативной версии
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent
    
    # Прямой путь к экзешнику для функции обрезки
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
            "-ss", start_str,
            "-i", path,
            "-t", seconds_to_hms(dur),
            "-c", "copy",
            "-map_metadata", "-1",
            outname
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
    
    # Прямой путь к исполняемому файлу ffmpeg
    ffmpeg_exe = str((base_path / "ffmpeg" / "bin" / "ffmpeg.exe").absolute())

    crf = settings.get('crf')
    preset = settings.get('preset')
    res_mode = settings.get('resolution') 
    res_custom = settings.get('resolution_custom')
    fps = settings.get('fps')
    acodec = settings.get('acodec')
    abitrate = settings.get('abitrate')
    suffix = settings.get('suffix')
    out_fmt = settings.get('out_format')

    for idx, path in enumerate(files, start=1):
        if cancel_event.is_set():
            queue.put(("conv", "status", "Операция отменена"))
            return

        queue.put(("conv", "update_index", (idx, total)))

        folder, fname = os.path.split(path)
        name, ext = os.path.splitext(fname)
        outname = os.path.join(folder, f"{name}{suffix}.{out_fmt}")

        probe = run_ffprobe(path)
        dur = 0.0
        width = height = 0
        rotation = 0.0
        
        try:
            if "format" in probe: 
                dur = float(probe["format"].get("duration", 0))
            for s in probe.get("streams", []):
                if s.get("codec_type") == "video":
                    width = int(s.get("width", 0))
                    height = int(s.get("height", 0))
                    tags = s.get("tags", {})
                    rot_val = tags.get("rotate") or tags.get("Rotate")
                    if rot_val:
                        try: rotation = float(rot_val)
                        except: pass
                    side_data = s.get("side_data_list", [])
                    for data_item in side_data:
                        if "rotation" in data_item:
                            try:
                                rotation = float(data_item["rotation"])
                                break 
                            except: pass
                    break
        except Exception as e: 
            print(f"Probe error: {e}")

        if abs(rotation) in (90, 270):
            width, height = height, width

        is_vertical = height > width

        cmd = [ffmpeg_exe, "-hide_banner", "-y", "-i", path,  
                "-c:v", "libx264", "-movflags", "+faststart", 
                "-profile:v", "high", "-pix_fmt", "yuv420p", 
                "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
        
        if crf: cmd += ["-crf", crf]
        if preset and preset != "copy": cmd += ["-preset", preset]

        scale_filter = None
        if res_mode == "custom":
            if res_custom: 
                # Исправлено: принудительно делаем стороны четными для h264
                scale_filter = f"scale={res_custom}:force_original_aspect_ratio=decrease,pad='ceil(iw/2)*2:ceil(ih/2)*2'"
        elif res_mode and res_mode != "copy":
            if ":-1" in res_mode:
                target_size = res_mode.split(":")[0]  
                # Исправлено: математика с округлением до четного числа для вертикальных/горизонтальных видео
                if is_vertical:
                    scale_filter = f"scale='trunc(oh*a/2)*2:{target_size}'"
                else:
                    scale_filter = f"scale='{target_size}:trunc(ow/a/2)*2'"
            else:
                scale_filter = f"scale={res_mode}:force_original_aspect_ratio=decrease,pad='ceil(iw/2)*2:ceil(ih/2)*2'"
        
        if scale_filter: cmd += ["-vf", scale_filter]
        if fps and fps != "copy": cmd += ["-r", fps]

        if acodec != "copy":
            cmd += ["-c:a", acodec]
            if abitrate and abitrate != "copy": cmd += ["-b:a", abitrate]
        else:
            cmd += ["-c:a", "copy"]

        cmd += ["-map_metadata", "-1", outname]

        try:
            proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True, bufsize=1, startupinfo=STARTUPINFO)
            while True:
                if cancel_event.is_set():
                    proc.terminate()
                    queue.put(("conv", "status", "Конвертация прервана"))
                    return

                line = proc.stderr.readline()
                if not line:
                    if proc.poll() is not None: break
                    time.sleep(0.05)
                    continue
                
                cur = parse_ffmpeg_time(line)
                if cur is not None and dur > 0:
                    pct = int((cur / dur) * 100)
                    queue.put(("conv", "progress", max(0, min(100, pct))))
            queue.put(("conv", "progress", 100))
        except Exception as e:
            error_msg = f"Ошибка FFmpeg на файле {name}: {str(e)}"
            queue.put(("conv", "error", error_msg))
            print(f"!!! Ошибка конвертации !!!\nКоманда: {' '.join(cmd)}\nОшибка: {e}")
            continue

    queue.put(("conv", "done", None))


# === ЗАГРУЗКА (YOUTUBE) ===
def download_worker(url, folder, queue, cancel_event):
    # 1. ОПРЕДЕЛЯЕМ ПУТЬ СТРОГО К ФАЙЛУ
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent

    # Важно: указываем путь именно к ffmpeg.exe, а не просто к папке
    ffmpeg_exe_path = base_path / "ffmpeg" / "bin" / "ffmpeg.exe"
    ffmpeg_exe_str = str(ffmpeg_exe_path.absolute())

    # Отладка в консоль (проверь это при запуске exe)
    print(f"--- YT-DLP DEBUG ---")
    print(f"Looking for ffmpeg at: {ffmpeg_exe_str}")
    print(f"Exists: {ffmpeg_exe_path.exists()}")
    print(f"--------------------")

    class MyLogger:
        def debug(self, msg): 
            if cancel_event.is_set(): raise Exception("CANCELED_BY_USER")
        def info(self, msg): 
            if cancel_event.is_set(): raise Exception("CANCELED_BY_USER")
        def warning(self, msg): print(f"[WARNING] {msg}")
        def error(self, msg): print(f"[ERROR] {msg}")

    def clean_ansi(text):
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    current_files = set()

    def progress_hook(d):
        if cancel_event.is_set(): raise Exception("CANCELED_BY_USER")
        if 'filename' in d: current_files.add(d['filename'])
        if d['status'] == 'downloading':
            p_clean = clean_ansi(d.get('_percent_str', '0%')).strip()
            s_clean = clean_ansi(d.get('_speed_str', '0KiB/s')).strip()
            p_match = re.search(r'(\d+\.?\d*)%', p_clean)
            pct_value = p_match.group(1) if p_match else "0"
            queue.put(("dl", "status", f"Загрузка: {pct_value}% | {s_clean}"))
            try: queue.put(("dl", "progress", int(float(pct_value))))
            except: pass

    # НАСТРОЙКИ (ydl_opts)
    ydl_opts = {
        'ffmpeg_location': ffmpeg_exe_str, # ТЕПЕРЬ ПЕРЕДАЕМ ПУТЬ К EXE
        # Упростили формат, чтобы не было ошибки "Requested format is not available"
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', 
        'outtmpl': os.path.join(folder, '%(title)s.%(ext)s'), 
        'merge_output_format': 'mp4', 
        'progress_hooks': [progress_hook], 
        'logger': MyLogger(), 
        'nooverwrites': True,
        'continuedl': True,
        'nocheckcertificate': True,
        'quiet': False,
    }

    try:
        queue.put(("dl", "status", "Анализ ссылки..."))
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if cancel_event.is_set(): raise Exception("CANCELED_BY_USER")
            ydl.download([url])
        queue.put(("dl", "done", None))
    except Exception as e:
        if "CANCELED_BY_USER" in str(e):
            queue.put(("dl", "status", "Загрузка отменена"))
            time.sleep(0.7)
            for f in current_files:
                for ext in ['', '.part', '.ytdl', '.temp']:
                    p = f + ext if ext != '' else f
                    if os.path.exists(p):
                        try: os.remove(p)
                        except: pass
            queue.put(("dl", "error", "Загрузка остановлена"))
        else:
            queue.put(("dl", "error", f"Ошибка: {str(e)}"))