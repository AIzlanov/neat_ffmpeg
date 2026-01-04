import tkinter as tk
from tkinter import ttk, messagebox
import threading
from workers import cut_worker
from ui.common import FileListWidget

class CutTab(ttk.Frame):
    def __init__(self, parent, queue):
        super().__init__(parent)
        self.queue = queue
        self.processing = False
        self.cancel_event = threading.Event()
        self._build_ui()

    def _build_ui(self):
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill="both", expand=True, padx=5, pady=5)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned, width=300)
        paned.add(left, weight=3)
        paned.add(right, weight=1)

        ttk.Label(right, text="Инфо:").pack(anchor="w")
        self.info_text = tk.Text(right, width=30, height=20, state="disabled")
        self.info_text.pack(fill="both", expand=True)

        self.file_widget = FileListWidget(left, self.info_text)
        self.file_widget.pack(fill="x")

        # Тайминг
        t_frame = ttk.LabelFrame(left, text="Тайминг")
        t_frame.pack(fill="x", pady=10)
        
        ttk.Label(t_frame, text="Начало:").grid(row=0, column=0, padx=5, pady=5)
        self.entry_start = ttk.Entry(t_frame, width=10)
        self.entry_start.insert(0, "00:00:00")
        self.entry_start.grid(row=0, column=1)

        ttk.Label(t_frame, text="Конец:").grid(row=0, column=2, padx=5)
        self.entry_end = ttk.Entry(t_frame, width=10)
        self.entry_end.insert(0, "00:00:00")
        self.entry_end.grid(row=0, column=3)

        sf_frame = ttk.Frame(left)
        sf_frame.pack(fill="x", pady=5)
        ttk.Label(sf_frame, text="Приписка:").pack(side="left")
        self.entry_suffix = ttk.Entry(sf_frame, width=15)
        self.entry_suffix.insert(0, "_cut")
        self.entry_suffix.pack(side="left", padx=5)

        # Кнопки
        btn_frame = ttk.Frame(left)
        btn_frame.pack(anchor="w", pady=10)

        self.btn_start = ttk.Button(btn_frame, text="Обрезать", command=self.start)
        self.btn_start.pack(side="left", padx=(0, 5))

        self.btn_stop = ttk.Button(btn_frame, text="Остановить", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left")

        # Статус
        status_frame = ttk.Frame(left)
        status_frame.pack(fill="x", pady=5)
        self.lbl_status = ttk.Label(status_frame, text="Файл 0 из 0")
        self.lbl_status.pack(side="left")

        self.progress = ttk.Progressbar(left, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x")

    def start(self):
        files = self.file_widget.get_files()
        if not files:
            messagebox.showerror("Ошибка", "Нет файлов")
            return
        if self.processing: return

        self.processing = True
        self.cancel_event.clear()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        
        self.lbl_status.config(text=f"Запуск... (Всего: {len(files)})")
        
        # ВАЖНО: Добавили self.cancel_event в кортеж args
        args = (
            files,
            self.entry_start.get(),
            self.entry_end.get(),
            self.entry_suffix.get(),
            self.queue,
            self.cancel_event
        )
        threading.Thread(target=cut_worker, args=args, daemon=True).start()

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
            if "прервана" in data or "отменена" in data:
                self.processing = False
                self.btn_start.config(state="normal")
                self.btn_stop.config(state="disabled")

        elif msg_type == "done":
            self.processing = False
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.progress['value'] = 100
            self.lbl_status.config(text="Обрезка завершена!")
            messagebox.showinfo("Готово", "Все файлы обрезаны.")
            
        elif msg_type == "error":
            self.processing = False
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            messagebox.showerror("Ошибка", data)