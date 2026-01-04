import os
import time
import subprocess
import re
import yt_dlp
from utils import hms_to_seconds, seconds_to_hms, parse_ffmpeg_time, run_ffprobe, STARTUPINFO

# === ОБРЕЗКА (CUT) ===
def cut_worker(files, start_str, end_str, suffix, queue, cancel_event):
    total = len(files)
    start_sec = hms_to_seconds(start_str)
    end_sec = hms_to_seconds(end_str)
    dur = end_sec - start_sec

    if dur <= 0:
        queue.put(("cut", "error", "Конечное время должно быть больше начального"))
        return

    for idx, path in enumerate(files, start=1):
        # Проверка отмены ПЕРЕД запуском файла
        if cancel_event.is_set():
            queue.put(("cut", "status", "Операция отменена"))
            return

        queue.put(("cut", "update_index", (idx, total)))

        folder, fname = os.path.split(path)
        name, ext = os.path.splitext(fname)
        outname = os.path.join(folder, f"{name}{suffix}{ext}")

        cmd = [
            "ffmpeg", "-hide_banner", "-y",
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
                # Проверка отмены ВО ВРЕМЯ работы процесса
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
        # Проверка отмены ПЕРЕД запуском файла
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

        cmd = ["ffmpeg", "-hide_banner", "-y", "-i", path,  
                "-c:v", "libx264", "-movflags", "+faststart", 
                "-profile:v", "high", "-pix_fmt", "yuv420p", 
                "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
        
        if crf: cmd += ["-crf", crf]
        if preset and preset != "copy": cmd += ["-preset", preset]

        scale_filter = None
        if res_mode == "custom":
            if res_custom: scale_filter = res_custom
        elif res_mode and res_mode != "copy":
            if ":-1" in res_mode:
                target_size = res_mode.split(":")[0]  
                scale_filter = f"-1:{target_size}" if is_vertical else f"{target_size}:-1"
            else:
                scale_filter = res_mode
        
        if scale_filter: cmd += ["-vf", f"scale={scale_filter}"]
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
                # Проверка отмены ВО ВРЕМЯ процесса
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
            queue.put(("conv", "error", f"Start fail: {e}"))
            continue

    queue.put(("conv", "done", None))


# === ЗАГРУЗКА (YOUTUBE) ===
def download_worker(url, folder, queue, cancel_event):
    # 1. ЛОГГЕР (теперь не совсем тихий, чтобы вы видели ошибки)
    class MyLogger:
        def debug(self, msg): 
            if cancel_event.is_set(): raise Exception("CANCELED_BY_USER")
            # print(f"[DEBUG] {msg}") # Раскомментируйте, если нужно видеть всё
        def info(self, msg): 
            if cancel_event.is_set(): raise Exception("CANCELED_BY_USER")
            print(f"[INFO] {msg}")
        def warning(self, msg): 
            print(f"[WARNING] {msg}")
        def error(self, msg): 
            print(f"[ERROR] {msg}")

    def clean_ansi(text):
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    current_files = set()

    def progress_hook(d):
        if cancel_event.is_set():
            raise Exception("CANCELED_BY_USER")
        
        if 'filename' in d:
            current_files.add(d['filename'])

        if d['status'] == 'downloading':
            p_str = d.get('_percent_str', '0%')
            s_str = d.get('_speed_str', '0KiB/s')
            p_clean = clean_ansi(p_str).strip()
            s_clean = clean_ansi(s_str).strip()
            
            p_match = re.search(r'(\d+\.?\d*)%', p_clean)
            pct_value = p_match.group(1) if p_match else "0"
            
            queue.put(("dl", "status", f"Загрузка: {pct_value}% | {s_clean}"))
            try:
                queue.put(("dl", "progress", int(float(pct_value))))
            except: pass

    # 4. НАСТРОЙКИ (ydl_opts)
    ydl_opts = {
        # Формат: mp4, до 1080p
        'format': 'bestvideo[height<=1080][vcodec^=avc1]+bestaudio[acodec^=mp4a]/bestvideo+bestaudio/best[height<=1080]', 
        'outtmpl': os.path.join(folder, '%(title)s.%(ext)s'), 
        'merge_output_format': 'mp4', 
        
        # СВЯЗКА ХУКОВ И ЛОГГЕРА
        'progress_hooks': [progress_hook], 
        'logger': MyLogger(), 
        
        'nooverwrites': True, # Не перезаписывать существующие файлы
        'continuedl': True, # Продолжать докачку
        'nocheckcertificate': True, # Игнорировать ошибки сертификатов
        'geo_bypass': True, # Обход гео-блокировок
        'restrictfilenames': True, # Ограниченные имена файлов
        'quiet': False, # True - Отключить весь вывод в консоль
        'no_warnings': True, # Отключить предупреждения
    }

    # 5. ЗАПУСК
    try:
        queue.put(("dl", "status", "Анализ ссылки..."))
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if cancel_event.is_set(): raise Exception("CANCELED_BY_USER")
            ydl.download([url])
            
        queue.put(("dl", "done", None))

    except Exception as e:
        if "CANCELED_BY_USER" in str(e):
            print("\n[SYSTEM] Процесс прерван пользователем. Очистка...")
            queue.put(("dl", "status", "Загрузка отменена"))
            
            time.sleep(0.7) # Даем системе чуть больше времени закрыть файлы
            
            for f in current_files:
                for ext in ['', '.part', '.ytdl', '.temp', '.f137', '.f251', '.f136']:
                    path_to_del = f + ext if ext != '' else f
                    if os.path.exists(path_to_del):
                        try:
                            os.remove(path_to_del)
                            print(f"[CLEANUP] Удален мусор: {path_to_del}")
                        except Exception as err:
                            print(f"[CLEANUP] Не удалось удалить {path_to_del}: {err}")
            
            # ВАЖНО: Отправляем сигнал 'error', чтобы UI разблокировал кнопки
            queue.put(("dl", "error", "Загрузка была остановлена пользователем"))
            
        else:
            queue.put(("dl", "error", f"Ошибка: {str(e)}"))

    # На всякий случай печатаем пустую строку, чтобы "вернуть" консоль
    print("\n")