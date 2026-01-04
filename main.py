import os
import sys
from pathlib import Path
from ui.app import FFmpegApp

def setup_ffmpeg_path():
    # Определяем базовый путь: если запущено как .exe — берем путь к .exe,
    # если как скрипт — берем путь к файлу main.py
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent

    # Путь к папке с бинарниками ffmpeg
    ffmpeg_bin_path = base_path / "ffmpeg" / "bin"
    
    if ffmpeg_bin_path.exists():
        bin_dir = str(ffmpeg_bin_path.absolute())
        # Добавляем путь в начало PATH текущего окружения, если его там еще нет
        if bin_dir not in os.environ["PATH"]:
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]
    else:
        # Опционально: можно вывести в консоль для отладки, если папка не найдена
        print(f"Warning: FFmpeg bin directory not found at {ffmpeg_bin_path}")

# Инициализируем пути перед запуском интерфейса
setup_ffmpeg_path()

# Запуск основного приложения
def main():
    app = FFmpegApp()
    app.mainloop()

if __name__ == "__main__":
    main()