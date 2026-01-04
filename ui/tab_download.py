import tkinter as tk
from tkinter import ttk, messagebox
import threading
import os
from workers import download_worker

class DownloadTab(ttk.Frame):
    def __init__(self, parent, queue):
        super().__init__(parent)
        self.queue = queue
        self.processing = False
        # Тот самый флаг отмены
        self.cancel_event = threading.Event()
        self._build_ui()

    def _build_ui(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Поле ввода ссылки
        ttk.Label(main_frame, text="Ссылка на видео (YouTube):").pack(anchor="w", pady=(0, 5))
        
        # Рамка для строки ввода (чтобы в будущем добавить иконки, если захотите)
        entry_frame = ttk.Frame(main_frame)
        entry_frame.pack(fill="x", pady=(0, 15))

        self.entry_url = ttk.Entry(entry_frame)
        self.entry_url.pack(fill="x")
        
        # --- ФИКС: Вставка правой кнопкой мыши (как вы просили) ---
        self.entry_url.bind("<Button-1>", self._quick_paste)

        # Выбор папки для сохранения
        lbl_folder = ttk.Label(main_frame, text="Папка для сохранения:")
        lbl_folder.pack(anchor="w", pady=(0, 5))

        folder_frame = ttk.Frame(main_frame)
        folder_frame.pack(fill="x", pady=(0, 15))

        self.entry_folder = ttk.Entry(folder_frame)
        self.entry_folder.pack(side="left", fill="x", expand=True)
        # Ставим папку "Downloads" или текущую по умолчанию
        default_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.entry_folder.insert(0, default_dir)

        btn_browse = ttk.Button(folder_frame, text="Выбрать...", command=self.browse_folder)
        btn_browse.pack(side="left", padx=(5, 0))

        # --- КНОПКИ УПРАВЛЕНИЯ ---
        btns_frame = ttk.Frame(main_frame)
        btns_frame.pack(anchor="w", pady=(0, 15))

        self.btn_start = ttk.Button(btns_frame, text="Скачать видео", command=self.start)
        self.btn_start.pack(side="left", padx=(0, 10))

        # НОВАЯ КНОПКА: Остановить
        self.btn_stop = ttk.Button(btns_frame, text="Остановить", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left")

        # Прогресс и статус
        self.lbl_status = ttk.Label(main_frame, text="Готов к работе")
        self.lbl_status.pack(anchor="w", pady=(0, 5))

        self.progress = ttk.Progressbar(main_frame, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x")

    def _quick_paste(self, event):
        """Быстрая вставка по правой кнопке мыши"""
        try:
            text = self.clipboard_get()
            if text:
                self.entry_url.delete(0, tk.END)
                self.entry_url.insert(0, text)
        except: pass
        return "break"

    def browse_folder(self):
        import tkinter.filedialog as fd
        d = fd.askdirectory()
        if d:
            self.entry_folder.delete(0, tk.END)
            self.entry_folder.insert(0, d)

    def start(self):
        url = self.entry_url.get().strip()
        folder = self.entry_folder.get().strip()

        if not url or not folder:
            messagebox.showwarning("Внимание", "Заполните все поля")
            return

        # Подготовка к запуску
        self.processing = True
        self.cancel_event.clear() # СБРАСЫВАЕМ ФЛАГ ПЕРЕД СТАРТОМ
        
        self.btn_start.config(state="disabled") # Выключаем старт
        self.btn_stop.config(state="normal")    # Включаем стоп
        self.progress['value'] = 0
        self.lbl_status.config(text="Запуск...")

        # Запуск потока (передаем cancel_event!)
        thread = threading.Thread(
            target=download_worker, 
            args=(url, folder, self.queue, self.cancel_event), 
            daemon=True
        )
        thread.start()

    def stop(self):
        """Метод вызывается при нажатии кнопки 'Остановить'"""
        if self.processing:
            self.cancel_event.set() # ПОДНИМАЕМ ФЛАГ ОТМЕНЫ
            self.btn_stop.config(state="disabled")
            self.lbl_status.config(text="Остановка... (докачиваем фрагмент)")

    def handle_message(self, msg_type, data):
        """Обработка сигналов из очереди"""
        if msg_type == "status":
            self.lbl_status.config(text=data)
        elif msg_type == "progress":
            self.progress['value'] = data
        elif msg_type in ("done", "error"):
            # Возвращаем кнопки в исходное состояние
            self.processing = False
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            
            if msg_type == "done":
                self.lbl_status.config(text="Завершено успешно")
                messagebox.showinfo("Готово", "Видео скачано!")
                self.entry_url.delete(0, tk.END) # Очищаем после успеха
            else:
                self.lbl_status.config(text=f"Ошибка: {data}")
                messagebox.showerror("Ошибка", data)