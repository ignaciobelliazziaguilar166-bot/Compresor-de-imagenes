import os
import sys
import subprocess
import threading
import queue
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageOps
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageOps


def rgb_hex(r, g, b):
    return f"{chr(35)}{r:02x}{g:02x}{b:02x}"


class ImageOptimizationEngine:
    SUPPORTED_INPUTS = {
        ".jpg", ".jpeg", ".png", ".webp", ".bmp",
        ".tiff", ".tif", ".ico", ".ppm", ".pgm", ".gif"
    }

    ICO_SIZES_MAP = {
        "Todos (16px a 256px)": [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        "Estandar (16px, 32px, 48px, 256px)": [(16, 16), (32, 32), (48, 48), (256, 256)],
        "Alta Resolucion (256x256)": [(256, 256)],
        "Mediano (64x64)": [(64, 64)],
        "Pequeno (32x32)": [(32, 32)],
        "Miniatura (16x16)": [(16, 16)]
    }

    @staticmethod
    def prepare_square_rgba(img, target_size=256):
        img = img.convert("RGBA")
        w, h = img.size
        max_side = max(w, h, target_size)
        ratio = min(max_side / w, max_side / h)
        new_w = max(1, int(round(w * ratio)))
        new_h = max(1, int(round(h * ratio)))
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (max_side, max_side), (0, 0, 0, 0))
        offset_x = (max_side - new_w) // 2
        offset_y = (max_side - new_h) // 2
        canvas.paste(resized, (offset_x, offset_y), resized)
        if max_side != target_size:
            canvas = canvas.resize((target_size, target_size), Image.Resampling.LANCZOS)
        return canvas

    @staticmethod
    def flatten_to_rgb(img, bg_color=(255, 255, 255)):
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, bg_color)
            background.paste(rgba, mask=rgba.split()[3])
            return background
        return img.convert("RGB")

    @classmethod
    def process_image(cls, source_path, output_dir, options):
        src = Path(source_path)
        target_format = options["format"].upper()
        quality = int(options["quality"])
        strip_metadata = options["strip_metadata"]
        smart_png = options["smart_png"]
        max_dimension = options["max_dimension"]
        ico_preset = options["ico_preset"]

        ext_map = {
            "ICO": ".ico",
            "WEBP": ".webp",
            "PNG": ".png",
            "JPEG": ".jpg",
            "BMP": ".bmp",
            "TIFF": ".tiff",
            "PDF": ".pdf"
        }
        out_ext = ext_map.get(target_format, ".webp")
        out_path = Path(output_dir) / f"{src.stem}{out_ext}"

        counter = 1
        while out_path.exists() and out_path.resolve() == src.resolve():
            out_path = Path(output_dir) / f"{src.stem}_optimizado_{counter}{out_ext}"
            counter += 1

        with Image.open(src) as raw_img:
            img = ImageOps.exif_transpose(raw_img)
            exif_data = img.info.get("exif") if not strip_metadata else None
            icc_profile = img.info.get("icc_profile") if not strip_metadata else None

            if max_dimension > 0 and target_format != "ICO":
                w, h = img.size
                if max(w, h) > max_dimension:
                    scale = max_dimension / float(max(w, h))
                    new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)

            save_kwargs = {}
            if exif_data and target_format in ("JPEG", "WEBP", "PNG", "TIFF"):
                save_kwargs["exif"] = exif_data
            if icc_profile and target_format in ("JPEG", "WEBP", "PNG", "TIFF"):
                save_kwargs["icc_profile"] = icc_profile

            if target_format == "ICO":
                sizes = cls.ICO_SIZES_MAP.get(ico_preset, [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
                max_ico = max(s[0] for s in sizes)
                ico_img = cls.prepare_square_rgba(img, target_size=max_ico)
                ico_img.save(out_path, format="ICO", sizes=sizes)

            elif target_format == "WEBP":
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA" if "A" in img.mode or "transparency" in img.info else "RGB")
                if quality == 100:
                    save_kwargs.update({"lossless": True, "quality": 100, "method": 6})
                else:
                    save_kwargs.update({"lossless": False, "quality": quality, "method": 6})
                img.save(out_path, format="WEBP", **save_kwargs)

            elif target_format == "JPEG":
                rgb_img = cls.flatten_to_rgb(img)
                subsampling = 0 if quality >= 90 else 2
                save_kwargs.update({
                    "quality": quality,
                    "optimize": True,
                    "progressive": True,
                    "subsampling": subsampling
                })
                rgb_img.save(out_path, format="JPEG", **save_kwargs)

            elif target_format == "PNG":
                png_img = img
                if smart_png and quality < 100:
                    colors = max(16, int((quality / 100.0) * 256))
                    if png_img.mode not in ("RGBA", "RGB", "P"):
                        png_img = png_img.convert("RGBA")
                    if png_img.mode == "RGBA":
                        png_img = png_img.quantize(colors=colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
                    elif png_img.mode == "RGB":
                        png_img = png_img.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
                save_kwargs.update({
                    "optimize": True,
                    "compress_level": 9
                })
                png_img.save(out_path, format="PNG", **save_kwargs)

            elif target_format == "TIFF":
                if img.mode not in ("RGB", "RGBA", "L"):
                    img = img.convert("RGBA" if "A" in img.mode else "RGB")
                save_kwargs.update({"compression": "tiff_adobe_deflate"})
                img.save(out_path, format="TIFF", **save_kwargs)

            elif target_format == "BMP":
                bmp_img = cls.flatten_to_rgb(img)
                bmp_img.save(out_path, format="BMP")

            elif target_format == "PDF":
                pdf_img = cls.flatten_to_rgb(img)
                pdf_img.save(out_path, format="PDF", resolution=150.0, quality=quality, optimize=True)

        orig_size = src.stat().st_size
        new_size = out_path.stat().st_size
        return out_path, orig_size, new_size


class ProfessionalImageSuite(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Suite Profesional de Conversion y Compresion de Imagenes")
        self.geometry("1180x720")
        self.minsize(1020, 640)

        self.bg_primary = rgb_hex(15, 23, 42)
        self.bg_secondary = rgb_hex(30, 41, 59)
        self.bg_surface = rgb_hex(51, 65, 85)
        self.text_primary = rgb_hex(248, 250, 252)
        self.text_secondary = rgb_hex(148, 163, 184)
        self.accent_blue = rgb_hex(37, 99, 235)
        self.accent_hover = rgb_hex(29, 78, 216)
        self.success_green = rgb_hex(22, 163, 74)
        self.border_color = rgb_hex(71, 85, 105)

        self.configure(bg=self.bg_primary)
        self.files_map = {}
        self.task_queue = queue.Queue()
        self.is_processing = False

        self.format_var = tk.StringVar(value="ICO")
        self.quality_var = tk.IntVar(value=88)
        self.quality_label_var = tk.StringVar(value="88%")
        self.ico_preset_var = tk.StringVar(value="Todos (16px a 256px)")
        self.smart_png_var = tk.BooleanVar(value=True)
        self.strip_meta_var = tk.BooleanVar(value=True)
        self.resize_var = tk.StringVar(value="Original (Sin cambios)")
        self.output_dir_var = tk.StringVar(value=str(Path.home() / "Desktop" / "Imagenes_Optimizadas"))
        self.status_var = tk.StringVar(value="Sistema listo. Agregue imagenes para comenzar.")
        self.stats_var = tk.StringVar(value="Archivos: 0 | Ahorro Total: 0.00 KB (0.0%)")

        self._setup_styles()
        self._build_interface()
        self._on_format_change()

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("TFrame", background=self.bg_primary)
        style.configure("Sidebar.TFrame", background=self.bg_secondary)
        style.configure("Card.TFrame", background=self.bg_secondary, relief="flat")

        style.configure(
            "TLabel",
            background=self.bg_primary,
            foreground=self.text_primary,
            font=("Segoe UI", 10)
        )
        style.configure(
            "Sidebar.TLabel",
            background=self.bg_secondary,
            foreground=self.text_primary,
            font=("Segoe UI", 10)
        )
        style.configure(
            "Muted.TLabel",
            background=self.bg_secondary,
            foreground=self.text_secondary,
            font=("Segoe UI", 9)
        )
        style.configure(
            "Header.TLabel",
            background=self.bg_primary,
            foreground=self.text_primary,
            font=("Segoe UI", 15, "bold")
        )
        style.configure(
            "Section.TLabel",
            background=self.bg_secondary,
            foreground=self.text_primary,
            font=("Segoe UI", 11, "bold")
        )

        style.configure(
            "Primary.TButton",
            background=self.accent_blue,
            foreground=self.text_primary,
            borderwidth=0,
            focusthickness=0,
            font=("Segoe UI", 10, "bold"),
            padding=(14, 9)
        )
        style.map(
            "Primary.TButton",
            background=[("active", self.accent_hover), ("disabled", self.bg_surface)],
            foreground=[("disabled", self.text_secondary)]
        )

        style.configure(
            "Action.TButton",
            background=self.bg_surface,
            foreground=self.text_primary,
            borderwidth=0,
            focusthickness=0,
            font=("Segoe UI", 9, "bold"),
            padding=(12, 7)
        )
        style.map(
            "Action.TButton",
            background=[("active", self.border_color), ("disabled", self.bg_secondary)],
            foreground=[("disabled", self.text_secondary)]
        )

        style.configure(
            "Success.TButton",
            background=self.success_green,
            foreground=self.text_primary,
            borderwidth=0,
            focusthickness=0,
            font=("Segoe UI", 11, "bold"),
            padding=(16, 11)
        )
        style.map(
            "Success.TButton",
            background=[("active", rgb_hex(21, 128, 61)), ("disabled", self.bg_surface)],
            foreground=[("disabled", self.text_secondary)]
        )

        style.configure(
            "TCheckbutton",
            background=self.bg_secondary,
            foreground=self.text_primary,
            font=("Segoe UI", 9),
            focusthickness=0
        )
        style.map(
            "TCheckbutton",
            background=[("active", self.bg_secondary)],
            foreground=[("disabled", self.text_secondary)]
        )

        style.configure(
            "TCombobox",
            fieldbackground=self.bg_surface,
            background=self.bg_surface,
            foreground=self.text_primary,
            arrowcolor=self.text_primary,
            borderwidth=0,
            padding=6
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.bg_surface), ("disabled", self.bg_primary)],
            foreground=[("readonly", self.text_primary), ("disabled", self.text_secondary)],
            selectbackground=[("readonly", self.accent_blue)],
            selectforeground=[("readonly", self.text_primary)]
        )

        style.configure(
            "Treeview",
            background=self.bg_secondary,
            foreground=self.text_primary,
            fieldbackground=self.bg_secondary,
            borderwidth=0,
            rowheight=30,
            font=("Segoe UI", 9)
        )
        style.configure(
            "Treeview.Heading",
            background=self.bg_surface,
            foreground=self.text_primary,
            borderwidth=0,
            font=("Segoe UI", 9, "bold"),
            padding=(8, 7)
        )
        style.map(
            "Treeview",
            background=[("selected", self.accent_blue)],
            foreground=[("selected", self.text_primary)]
        )

        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=self.bg_secondary,
            background=self.accent_blue,
            borderwidth=0,
            thickness=10
        )

        style.configure(
            "Horizontal.TScale",
            background=self.bg_secondary,
            troughcolor=self.bg_surface
        )

    def _build_interface(self):
        main_container = ttk.Frame(self, padding=16)
        main_container.pack(fill="both", expand=True)
        main_container.columnconfigure(1, weight=1)
        main_container.rowconfigure(1, weight=1)

        header_frame = ttk.Frame(main_container)
        header_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        ttk.Label(
            header_frame,
            text="CONVERSOR Y COMPRESOR PROFESIONAL DE IMAGENES",
            style="Header.TLabel"
        ).pack(side="left")
        ttk.Label(
            header_frame,
            textvariable=self.stats_var,
            font=("Segoe UI", 10, "bold"),
            foreground=self.text_secondary
        ).pack(side="right")

        sidebar = ttk.Frame(main_container, style="Sidebar.TFrame", padding=18, width=330)
        sidebar.grid(row=1, column=0, sticky="ns", padx=(0, 16))
        sidebar.grid_propagate(False)

        ttk.Label(sidebar, text="CONFIGURACION DE SALIDA", style="Section.TLabel").pack(anchor="w", pady=(0, 12))

        ttk.Label(sidebar, text="Formato de Destino:", style="Sidebar.TLabel").pack(anchor="w")
        self.format_combo = ttk.Combobox(
            sidebar,
            textvariable=self.format_var,
            values=["ICO", "WEBP", "PNG", "JPEG", "TIFF", "BMP", "PDF"],
            state="readonly",
            font=("Segoe UI", 10)
        )
        self.format_combo.pack(fill="x", pady=(4, 14))
        self.format_combo.bind("<<ComboboxSelected>>", self._on_format_change)

        self.ico_frame = ttk.Frame(sidebar, style="Sidebar.TFrame")
        self.ico_frame.pack(fill="x", pady=(0, 14))
        ttk.Label(self.ico_frame, text="Resoluciones de Icono (.ico):", style="Sidebar.TLabel").pack(anchor="w")
        self.ico_combo = ttk.Combobox(
            self.ico_frame,
            textvariable=self.ico_preset_var,
            values=list(ImageOptimizationEngine.ICO_SIZES_MAP.keys()),
            state="readonly",
            font=("Segoe UI", 9)
        )
        self.ico_combo.pack(fill="x", pady=(4, 0))

        ttk.Label(sidebar, text="PARAMETROS DE COMPRESION", style="Section.TLabel").pack(anchor="w", pady=(6, 10))

        quality_header = ttk.Frame(sidebar, style="Sidebar.TFrame")
        quality_header.pack(fill="x")
        ttk.Label(quality_header, text="Calidad Visual:", style="Sidebar.TLabel").pack(side="left")
        ttk.Label(
            quality_header,
            textvariable=self.quality_label_var,
            style="Sidebar.TLabel",
            font=("Segoe UI", 10, "bold")
        ).pack(side="right")

        self.quality_scale = ttk.Scale(
            sidebar,
            from_=10,
            to=100,
            orient="horizontal",
            command=self._on_quality_slide
        )
        self.quality_scale.set(88)
        self.quality_scale.pack(fill="x", pady=(6, 4))
        ttk.Label(
            sidebar,
            text="85% - 92% ofrece reduccion maxima sin perdida visual.",
            style="Muted.TLabel"
        ).pack(anchor="w", pady=(0, 12))

        self.smart_png_check = ttk.Checkbutton(
            sidebar,
            text="Cuantizacion inteligente PNG (256 colores + Alfa)",
            variable=self.smart_png_var
        )
        self.smart_png_check.pack(anchor="w", pady=(0, 8))

        self.strip_meta_check = ttk.Checkbutton(
            sidebar,
            text="Eliminar metadatos EXIF innecesarios",
            variable=self.strip_meta_var
        )
        self.strip_meta_check.pack(anchor="w", pady=(0, 14))

        ttk.Label(sidebar, text="Escala Maxima (Opcional):", style="Sidebar.TLabel").pack(anchor="w")
        self.resize_combo = ttk.Combobox(
            sidebar,
            textvariable=self.resize_var,
            values=[
                "Original (Sin cambios)",
                "3840 px (4K UHD)",
                "2560 px (QHD)",
                "1920 px (Full HD)",
                "1280 px (HD)",
                "800 px (Web)"
            ],
            state="readonly",
            font=("Segoe UI", 9)
        )
        self.resize_combo.pack(fill="x", pady=(4, 16))

        ttk.Label(sidebar, text="DIRECTORIO DE SALIDA", style="Section.TLabel").pack(anchor="w", pady=(4, 8))
        dir_entry = tk.Entry(
            sidebar,
            textvariable=self.output_dir_var,
            bg=self.bg_surface,
            fg=self.text_primary,
            insertbackground=self.text_primary,
            relief="flat",
            font=("Segoe UI", 9)
        )
        dir_entry.pack(fill="x", ipady=6, pady=(0, 8))

        dir_btn_frame = ttk.Frame(sidebar, style="Sidebar.TFrame")
        dir_btn_frame.pack(fill="x", pady=(0, 16))
        ttk.Button(
            dir_btn_frame,
            text="Cambiar Carpeta",
            style="Action.TButton",
            command=self._select_output_dir
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(
            dir_btn_frame,
            text="Abrir Carpeta",
            style="Action.TButton",
            command=self._open_output_dir
        ).pack(side="right", fill="x", expand=True, padx=(4, 0))

        self.process_btn = ttk.Button(
            sidebar,
            text="PROCESAR IMAGENES",
            style="Success.TButton",
            command=self._start_processing
        )
        self.process_btn.pack(side="bottom", fill="x")

        right_panel = ttk.Frame(main_container)
        right_panel.grid(row=1, column=1, sticky="nsew")
        right_panel.rowconfigure(1, weight=1)
        right_panel.columnconfigure(0, weight=1)

        toolbar = ttk.Frame(right_panel)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        ttk.Button(
            toolbar,
            text="Agregar Imagenes",
            style="Primary.TButton",
            command=self._add_files
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            toolbar,
            text="Agregar Carpeta",
            style="Action.TButton",
            command=self._add_folder
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            toolbar,
            text="Quitar Seleccion",
            style="Action.TButton",
            command=self._remove_selected
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            toolbar,
            text="Limpiar Lista",
            style="Action.TButton",
            command=self._clear_all
        ).pack(side="right")

        table_container = ttk.Frame(right_panel, style="Sidebar.TFrame")
        table_container.grid(row=1, column=0, sticky="nsew")
        table_container.rowconfigure(0, weight=1)
        table_container.columnconfigure(0, weight=1)

        columns = ("name", "orig_fmt", "orig_size", "new_fmt", "new_size", "saved", "status")
        self.tree = ttk.Treeview(table_container, columns=columns, show="headings", selectmode="extended")

        self.tree.heading("name", text="Archivo")
        self.tree.heading("orig_fmt", text="Origen")
        self.tree.heading("orig_size", text="Peso Inicial")
        self.tree.heading("new_fmt", text="Salida")
        self.tree.heading("new_size", text="Peso Final")
        self.tree.heading("saved", text="Reduccion")
        self.tree.heading("status", text="Estado")

        self.tree.column("name", width=250, anchor="w")
        self.tree.column("orig_fmt", width=70, anchor="center")
        self.tree.column("orig_size", width=95, anchor="e")
        self.tree.column("new_fmt", width=70, anchor="center")
        self.tree.column("new_size", width=95, anchor="e")
        self.tree.column("saved", width=90, anchor="center")
        self.tree.column("status", width=130, anchor="center")

        scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        footer = ttk.Frame(right_panel)
        footer.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)

        ttk.Label(footer, textvariable=self.status_var, font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.progress = ttk.Progressbar(footer, orient="horizontal", mode="determinate")
        self.progress.grid(row=1, column=0, sticky="ew")

    def _on_quality_slide(self, val):
        q = int(float(val))
        self.quality_var.set(q)
        self.quality_label_var.set(f"{q}%")

    def _on_format_change(self, event=None):
        fmt = self.format_var.get().upper()
        if fmt == "ICO":
            self.ico_combo.configure(state="readonly")
            self.resize_combo.configure(state="disabled")
        else:
            self.ico_combo.configure(state="disabled")
            self.resize_combo.configure(state="readonly")

        if fmt == "PNG":
            self.smart_png_check.configure(state="normal")
        else:
            self.smart_png_check.configure(state="disabled")

    @staticmethod
    def _format_bytes(size):
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024.0:.2f} KB"
        return f"{size / (1024.0 * 1024.0):.2f} MB"

    def _parse_max_dimension(self):
        val = self.resize_var.get()
        if val.startswith("Original"):
            return 0
        parts = val.split()
        try:
            return int(parts[0])
        except ValueError:
            return 0

    def _add_files(self):
        if self.is_processing:
            return
        filetypes = [
            ("Imagenes Soportadas", "*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif *.ico *.gif *.ppm"),
            ("Todos los archivos", "*.*")
        ]
        paths = filedialog.askopenfilenames(title="Seleccionar Imagenes", filetypes=filetypes)
        self._register_paths(paths)

    def _add_folder(self):
        if self.is_processing:
            return
        folder = filedialog.askdirectory(title="Seleccionar Carpeta con Imagenes")
        if not folder:
            return
        collected = []
        for entry in Path(folder).rglob("*"):
            if entry.is_file() and entry.suffix.lower() in ImageOptimizationEngine.SUPPORTED_INPUTS:
                collected.append(str(entry))
        self._register_paths(collected)

    def _register_paths(self, paths):
        added = 0
        for p in paths:
            path_obj = Path(p)
            norm_path = str(path_obj.resolve())
            if norm_path in self.files_map or not path_obj.exists():
                continue
            if path_obj.suffix.lower() not in ImageOptimizationEngine.SUPPORTED_INPUTS:
                continue
            size = path_obj.stat().st_size
            item_id = self.tree.insert(
                "",
                "end",
                values=(
                    path_obj.name,
                    path_obj.suffix.replace(".", "").upper(),
                    self._format_bytes(size),
                    "-",
                    "-",
                    "-",
                    "En espera"
                )
            )
            self.files_map[norm_path] = {
                "id": item_id,
                "path": norm_path,
                "orig_size": size,
                "new_size": None
            }
            added += 1

        self._update_summary_stats()
        if added > 0:
            self.status_var.set(f"Se agregaron {added} imagenes a la cola de trabajo.")

    def _remove_selected(self):
        if self.is_processing:
            return
        selected = self.tree.selection()
        if not selected:
            return
        to_delete = []
        for norm_path, info in self.files_map.items():
            if info["id"] in selected:
                to_delete.append(norm_path)
        for norm_path in to_delete:
            self.tree.delete(self.files_map[norm_path]["id"])
            del self.files_map[norm_path]
        self._update_summary_stats()

    def _clear_all(self):
        if self.is_processing:
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.files_map.clear()
        self.progress["value"] = 0
        self._update_summary_stats()
        self.status_var.set("Lista vaciada.")

    def _select_output_dir(self):
        folder = filedialog.askdirectory(title="Seleccionar Carpeta de Destino")
        if folder:
            self.output_dir_var.set(folder)

    def _open_output_dir(self):
        out_dir = Path(self.output_dir_var.get())
        out_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(str(out_dir))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(out_dir)])
        else:
            subprocess.Popen(["xdg-open", str(out_dir)])

    def _update_summary_stats(self):
        total_files = len(self.files_map)
        total_orig = 0
        total_new = 0
        for info in self.files_map.values():
            if info["new_size"] is not None:
                total_orig += info["orig_size"]
                total_new += info["new_size"]

        if total_orig > 0:
            saved_bytes = max(0, total_orig - total_new)
            pct = ((total_orig - total_new) / float(total_orig)) * 100.0
            self.stats_var.set(
                f"Archivos: {total_files} | Ahorro Total: {self._format_bytes(saved_bytes)} ({pct:.1f}%)"
            )
        else:
            self.stats_var.set(f"Archivos: {total_files} | Ahorro Total: 0.00 KB (0.0%)")

    def _start_processing(self):
        if self.is_processing:
            return
        if not self.files_map:
            messagebox.showwarning("Cola Vacia", "Agregue al menos una imagen antes de iniciar el procesamiento.")
            return

        out_dir = Path(self.output_dir_var.get().strip())
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("Error de Directorio", f"No se pudo crear la carpeta de salida:\n{exc}")
            return

        options = {
            "format": self.format_var.get(),
            "quality": self.quality_var.get(),
            "strip_metadata": self.strip_meta_var.get(),
            "smart_png": self.smart_png_var.get(),
            "max_dimension": self._parse_max_dimension(),
            "ico_preset": self.ico_preset_var.get()
        }

        self.is_processing = True
        self.process_btn.configure(state="disabled")
        self.progress["maximum"] = len(self.files_map)
        self.progress["value"] = 0

        items = list(self.files_map.values())
        worker = threading.Thread(
            target=self._batch_worker,
            args=(items, str(out_dir), options),
            daemon=True
        )
        worker.start()
        self.after(50, self._poll_queue)

    def _batch_worker(self, items, out_dir, options):
        total = len(items)
        for index, item in enumerate(items, start=1):
            path = item["path"]
            item_id = item["id"]
            self.task_queue.put(("status", item_id, "Procesando...", index, total))
            try:
                out_path, orig_size, new_size = ImageOptimizationEngine.process_image(path, out_dir, options)
                self.task_queue.put((
                    "done",
                    path,
                    item_id,
                    options["format"],
                    orig_size,
                    new_size,
                    index,
                    total
                ))
            except Exception as exc:
                self.task_queue.put(("error", item_id, str(exc), index, total))
        self.task_queue.put(("finished", total))

    def _poll_queue(self):
        try:
            while True:
                msg = self.task_queue.get_nowait()
                kind = msg[0]

                if kind == "status":
                    _, item_id, status_txt, idx, total = msg
                    if self.tree.exists(item_id):
                        vals = list(self.tree.item(item_id, "values"))
                        vals[6] = status_txt
                        self.tree.item(item_id, values=vals)
                    self.status_var.set(f"Procesando imagen {idx} de {total}...")

                elif kind == "done":
                    _, path, item_id, fmt, orig_size, new_size, idx, total = msg
                    if path in self.files_map:
                        self.files_map[path]["new_size"] = new_size
                    diff_pct = ((orig_size - new_size) / float(orig_size)) * 100.0 if orig_size > 0 else 0.0
                    sign = f"-{diff_pct:.1f}%" if diff_pct >= 0 else f"+{abs(diff_pct):.1f}%"
                    if self.tree.exists(item_id):
                        vals = list(self.tree.item(item_id, "values"))
                        vals[3] = fmt
                        vals[4] = self._format_bytes(new_size)
                        vals[5] = sign
                        vals[6] = "Completado"
                        self.tree.item(item_id, values=vals)
                    self.progress["value"] = idx
                    self._update_summary_stats()

                elif kind == "error":
                    _, item_id, err_msg, idx, total = msg
                    if self.tree.exists(item_id):
                        vals = list(self.tree.item(item_id, "values"))
                        vals[6] = "Error"
                        self.tree.item(item_id, values=vals)
                    self.progress["value"] = idx
                    self.status_var.set(f"Error en archivo ({idx}/{total}): {err_msg}")

                elif kind == "finished":
                    _, total = msg
                    self.is_processing = False
                    self.process_btn.configure(state="normal")
                    self.status_var.set(f"Proceso finalizado correctamente. {total} archivos procesados.")
                    self._update_summary_stats()
                    return

        except queue.Empty:
            pass

        if self.is_processing:
            self.after(50, self._poll_queue)


if __name__ == "__main__":
    app = ProfessionalImageSuite()
    app.mainloop()
