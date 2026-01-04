import tkinter as tk
from tkinter import ttk, messagebox
import threading
from workers import convert_worker
from ui.common import FileListWidget

class ConvertTab(ttk.Frame):
    def __init__(self, parent, queue):
        super().__init__(parent)
        self.queue = queue
        self.processing = False
        # Создаем флаг отмены
        self.cancel_event = threading.Event()
        self._build_ui()

    def _build_ui(self):
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill="both", expand=True, padx=5, pady=5)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned, width=300)
        paned.add(left, weight=3)
        paned.add(right, weight=1)

        # Правая часть: Инфо
        ttk.Label(right, text="Инфо:").pack(anchor="w")
        self.info_text = tk.Text(right, width=30, height=20, state="disabled")
        self.info_text.pack(fill="both", expand=True)

        # Левая часть: Список файлов
        self.file_widget = FileListWidget(left, self.info_text)
        self.file_widget.pack(fill="x")

        # Настройки
        grp = ttk.LabelFrame(left, text="Параметры конвертации")
        grp.pack(fill="x", pady=10)

        def add_combo(parent, label, vals, default, row, col):
            ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=5, pady=2)
            cb = ttk.Combobox(parent, values=vals, width=12)
            cb.set(default)
            cb.grid(row=row, column=col+1, sticky="w", padx=5, pady=2)
            return cb

        self.cb_crf = add_combo(grp, "CRF:", [str(i) for i in range(16, 41)], "26", 0, 0)
        self.cb_preset = add_combo(grp, "Preset:", ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"], "veryslow", 0, 2)
        self.cb_res = add_combo(grp, "Resolution:", ["copy", "1920:-1", "1600:-1", "1280:-1", "1080:-1", "720:-1", "custom"], "1600:-1", 1, 0)
        
        self.entry_res_custom = ttk.Entry(grp, width=12)
        self.entry_res_custom.grid(row=1, column=2, padx=5, sticky="w") 

        self.cb_fps = add_combo(grp, "FPS:", ["copy", "24", "30", "60"], "24", 2, 0)
        self.cb_fmt = add_combo(grp, "Output fmt:", ["mp4", "mkv", "mov"], "mp4", 2, 2)
        self.cb_acodec = add_combo(grp, "A. Codec:", ["copy", "aac", "mp3", "pcm_s16le", "opus", "flac"], "aac", 3, 0)
        self.cb_abitrate = add_combo(grp, "A. Bitrate:", ["copy", "96k", "128k", "160k", "192k", "256k", "320k"], "128k", 3, 2)

        sf = ttk.Frame(left)
        sf.pack(fill="x", pady=5)
        ttk.Label(sf, text="Приписка:").pack(side="left")
        self.entry_suffix = ttk.Entry(sf, width=15)
        self.entry_suffix.insert(0, "_conv")
        self.entry_suffix.pack(side="left", padx=5)

        # --- КНОПКИ УПРАВЛЕНИЯ ---
        btn_frame = ttk.Frame(left)
        btn_frame.pack(anchor="w", pady=10)

        self.btn_start = ttk.Button(btn_frame, text="Конвертировать", command=self.start)
        self.btn_start.pack(side="left", padx=(0, 5))

        self.btn_stop = ttk.Button(btn_frame, text="Остановить", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left")

        # Статус и Прогресс
        status_frame = ttk.Frame(left)
        status_frame.pack(fill="x", pady=5)
        self.lbl_status = ttk.Label(status_frame, text="Файл 0 из 0")
        self.lbl_status.pack(side="left")
        
        self.progress = ttk.Progressbar(left, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x")

    def start(self):
        files = self.file_widget.get_files()
        if not files:
            messagebox.showerror("Ошибка", "Нет файлов для обработки.")
            return
        if self.processing: return

        self.processing = True
        self.cancel_event.clear() # Сбрасываем флаг отмены
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        
        self.progress['value'] = 0
        self.lbl_status.config(text=f"Подготовка... (Всего файлов: {len(files)})")

        settings = {
            "crf": self.cb_crf.get(),
            "preset": self.cb_preset.get(),
            "resolution": self.cb_res.get(),
            "resolution_custom": self.entry_res_custom.get(),
            "fps": self.cb_fps.get(),
            "out_format": self.cb_fmt.get(),
            "acodec": self.cb_acodec.get(),
            "abitrate": self.cb_abitrate.get(),
            "suffix": self.entry_suffix.get()
        }

        # Передаем cancel_event в аргументы!
        threading.Thread(target=convert_worker, args=(files, settings, self.queue, self.cancel_event), daemon=True).start()

    def stop(self):
        if self.processing:
            self.cancel_event.set()
            self.btn_stop.config(state="disabled")
            self.lbl_status.config(text="Прерывание...")

    def handle_message(self, msg_type, data):
        if msg_type == "update_index":
            idx, total = data
            self.lbl_status.config(text=f"Обработка файла {idx} из {total}")
            self.progress['value'] = 0
            
        elif msg_type == "progress":
            self.progress['value'] = data
            
        elif msg_type == "status":
            self.lbl_status.config(text=data)
            # Если в статусе пришло сообщение о прерванной работе, разблокируем кнопки
            if "прервана" in data or "отменена" in data:
                self.processing = False
                self.btn_start.config(state="normal")
                self.btn_stop.config(state="disabled")

        elif msg_type == "done":
            self.processing = False
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.progress['value'] = 100
            self.lbl_status.config(text="Конвертация завершена!")
            messagebox.showinfo("Готово", "Все файлы обработаны.")
            
        elif msg_type == "error":
            self.processing = False
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            messagebox.showerror("Ошибка ffmpeg", data)