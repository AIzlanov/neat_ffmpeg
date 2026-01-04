import tkinter as tk
from tkinter import ttk, filedialog
from utils import run_ffprobe, format_probe_info

class FileListWidget(ttk.Frame):
    def __init__(self, parent, info_text_widget, title="Файлы:"):
        super().__init__(parent)
        self.files = []
        self.info_widget = info_text_widget
        
        ttk.Label(self, text=title).pack(anchor="w")
        
        self.listbox = tk.Listbox(self, height=10)
        self.listbox.pack(fill="x", pady=5)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        btns = ttk.Frame(self)
        btns.pack(fill="x")
        
        ttk.Button(btns, text="Добавить", command=self._add).pack(side="left")
        ttk.Button(btns, text="Удалить", command=self._remove).pack(side="left", padx=5)
        ttk.Button(btns, text="Очистить", command=self._clear).pack(side="left")

    def _add(self):
        paths = filedialog.askopenfilenames()
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.listbox.insert(tk.END, p)

    def _remove(self):
        for idx in reversed(self.listbox.curselection()):
            del self.files[idx]
            self.listbox.delete(idx)

    def _clear(self):
        self.files.clear()
        self.listbox.delete(0, tk.END)

    def _on_select(self, event):
        sel = self.listbox.curselection()
        if not sel: return
        path = self.listbox.get(sel[0])
        
        # Обновляем инфо-панель (которая передана извне)
        if self.info_widget:
            self.info_widget.config(state="normal")
            self.info_widget.delete("1.0", tk.END)
            # Запускаем ffprobe синхронно (можно вынести в thread если тормозит)
            data = run_ffprobe(path)
            text = format_probe_info(data)
            self.info_widget.insert(tk.END, text)
            self.info_widget.config(state="disabled")

    def get_files(self):
        return self.files