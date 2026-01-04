import tkinter as tk
from tkinter import ttk
import queue
from ui.tab_cut import CutTab
from ui.tab_convert import ConvertTab
from ui.tab_download import DownloadTab

class FFmpegApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Neat FFmpeg")
        self.geometry("900x650")
        
        # Единая очередь сообщений
        self.queue = queue.Queue()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        # Инициализация вкладок
        self.tab_cut = CutTab(self.notebook, self.queue)
        self.tab_conv = ConvertTab(self.notebook, self.queue)
        self.tab_download = DownloadTab(self.notebook, self.queue)

        self.notebook.add(self.tab_download, text="Скачивание")
        self.notebook.add(self.tab_cut, text="Обрезка")
        self.notebook.add(self.tab_conv, text="Конвертация")

        # Запуск цикла чтения очереди
        self.after(100, self.process_queue)

    def process_queue(self):
        try:
            while True:
                # task_type: "cut" или "conv"
                # msg_type: "progress", "error", "done"...
                task_type, msg_type, data = self.queue.get_nowait()
                
                if task_type == "cut":
                    self.tab_cut.handle_message(msg_type, data)
                elif task_type == "conv":
                    self.tab_conv.handle_message(msg_type, data)
                elif task_type == "dl":
                    self.tab_download.handle_message(msg_type, data)
                    
        except queue.Empty:
            pass
        
        self.after(100, self.process_queue)