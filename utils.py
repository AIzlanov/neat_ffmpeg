import re
import json
import subprocess
import os
import sys

# Скрытие окна консоли на Windows
STARTUPINFO = None
if os.name == 'nt':
    STARTUPINFO = subprocess.STARTUPINFO()
    STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW

def hms_to_seconds(t: str) -> float:
    try:
        parts = [float(x) for x in t.split(":")]
        if len(parts) == 3:
            return parts[0]*3600 + parts[1]*60 + parts[2]
        elif len(parts) == 2:
            return parts[0]*60 + parts[1]
        return parts[0]
    except ValueError:
        return 0.0

def seconds_to_hms(s: float) -> str:
    s = int(round(s))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"

FFMPEG_TIME_RE = re.compile(r"time=(\d+:\d+:\d+(?:\.\d+)?)")

def parse_ffmpeg_time(line: str):
    if not line: return None
    m = FFMPEG_TIME_RE.search(line)
    if m:
        return hms_to_seconds(m.group(1))
    return None

def run_ffprobe(path: str) -> dict:
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            path
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, startupinfo=STARTUPINFO)
        return json.loads(out)
    except Exception as e:
        return {"error": str(e)}

def format_probe_info(probe: dict) -> str:
    if not probe: return "No info"
    if "error" in probe: return f"Error:\n{probe['error']}"

    lines = []
    fmt = probe.get("format", {})
    if fmt:
        lines.append(f"Format: {fmt.get('format_long_name','?')}")
        size = int(fmt.get("size", 0)) / 1024 / 1024
        lines.append(f"Size: {size:.2f} MB")
        dur = float(fmt.get("duration", 0))
        lines.append(f"Duration: {dur:.2f} s")
        br = fmt.get("bit_rate")
        if br: lines.append(f"Bitrate: {int(br)/1000:.0f} kbps")

    for s in probe.get("streams", []):
        ctype = s.get("codec_type")
        if ctype == "video":
            lines.append("\n[VIDEO]")
            lines.append(f" Codec: {s.get('codec_name')}")
            lines.append(f" Res: {s.get('width')}x{s.get('height')}")
            if s.get("r_frame_rate"): lines.append(f" FPS: {s.get('r_frame_rate')}")
        elif ctype == "audio":
            lines.append("\n[AUDIO]")
            lines.append(f" Codec: {s.get('codec_name')}")
            lines.append(f" Hz: {s.get('sample_rate')}")
    
    return "\n".join(lines)