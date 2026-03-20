import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import csv
import os
import json
import struct
import re
import math
import ctypes
import time

# --- EXTERNAL LIBRARIES FOR CAMERA ---
try:
    import pymem
    import pymem.process
    import keyboard
    import mouse
except ImportError:
    messagebox.showerror("Missing Libraries", "Please install required libraries:\npip install pymem keyboard mouse")
    exit()

from Worker_Data import ebp_patcher

# ==========================================
#               CONSTANTS
# ==========================================

# --- GUI CONSTANTS ---
WINDOW_WIDTH = 1450  
WINDOW_HEIGHT = 950
NUM_ROWS = 24
CSV_FILENAME = r"Worker_Data\ebpcommands.csv"

# --- OBJECT GENERATION SETTINGS ---
OBJECT_TOTAL_SIZE = 500  

# Folder Paths
BASE_DIR = "Worker_Data"
WORKER_DIR = os.path.join(BASE_DIR, "Worker")
ENTRY_DIR = os.path.join(BASE_DIR, "Entry")

# Layout Controls
OUTER_MARGIN = 45
ROW_SPACING = 0
ROW_INTERNAL_PADY = 0
ENTRY_HEIGHT_PAD = 0

# --- CAMERA / MEMORY CONSTANTS ---
PROCESS_NAME = "FFX.exe"
CAMERA_POS_OFFSET = 0xD37B7C
CAMERA_TARGET_OFFSET = 0xD37560
MOVEMENT_SPEED = 0.7  
MOUSE_SENSITIVITY = 0.0005
TICK_RATE_MS = 10 

# Smoothing
MOVEMENT_DAMPING = 0.5
AIM_SMOOTHING = 0.6

# Screen Depth
SCREEN_DEPTH_OFFSET = 0xD36FFC
SCREEN_DEPTH_SCROLL_SPEED = 50 

# Patch Configuration
PATCH_LOCATIONS = [
    {"offset": 0x3C14A5, "original": b"\x89\x02", "patch": b"\x90\x90"},
    {"offset": 0x3C14AC, "original": b"\x89\x42\x04", "patch": b"\x90\x90\x90"},
    {"offset": 0x3C14B4, "original": b"\x89\x42\x08", "patch": b"\x90\x90\x90"},
    {"offset": 0x3BE9E8, "original": b"\xD9\x98\x5B\xFF\xFF\xFF", "patch": b"\x90\x90\x90\x90\x90\x90"},
]

# ==========================================
#               HELPER CLASSES
# ==========================================

class RowWidget:
    """
    Row: [Dropdown] | [xOffset] | [Text Entry] | [Command Data] | [Arg1] | [Arg2] | [Arg3] | [Quick Input]
    """
    def __init__(self, parent, row_index, update_callback, focus_neighbor_callback, command_map, quick_input_data, consumption_rules):
        self.row_index = row_index
        self.update_callback = update_callback
        self.focus_neighbor = focus_neighbor_callback
        self.command_map = command_map
        self.quick_input_map = quick_input_data['map']
        self.consumption_rules = consumption_rules 
        
        self.frame = tk.Frame(parent, bg="#f0f0f0")
        self.frame.pack(fill="x", pady=ROW_SPACING)
        
        # 1. Dropdown (Left)
        vals = [""] + [f"j{i:02X}" for i in range(12)]
        self.combo1 = ttk.Combobox(self.frame, values=vals, width=5, state="readonly")
        self.combo1.pack(side="left", padx=(0, 5), pady=ROW_INTERNAL_PADY)
        self.combo1.current(0)
        self.combo1.bind("<<ComboboxSelected>>", self._on_combo_change)

        # 2. Offset Display (Left)
        self.count_label = tk.Label(
            self.frame,
            text="0000",
            width=6,
            anchor="e",
            bg="#f0f0f0",
            fg="#555",
            font=("Consolas", 9)
        )
        self.count_label.pack(side="left", fill="y", padx=(0, 10), pady=ROW_INTERNAL_PADY)

        # --- RIGHT SIDE (Pack Order: Right to Left) ---
        
        # 1. Quick Input (Far Right)
        self.quick_vals = [""] + quick_input_data['labels']
        self.quick_combo = ttk.Combobox(self.frame, values=self.quick_vals, width=18, state="readonly")
        self.quick_combo.pack(side="right", padx=(2, 0), pady=ROW_INTERNAL_PADY)
        self.quick_combo.bind("<<ComboboxSelected>>", self._on_quick_select)

        # 2. Arg Data 3
        self.arg_data_3_var = tk.StringVar()
        self.arg_label_3 = tk.Label(self.frame, textvariable=self.arg_data_3_var, width=14, anchor="w", bg="#f4f4f4", fg="#880000", font=("Arial", 8), relief="flat")
        self.arg_label_3.pack(side="right", fill="y", padx=(1, 1), pady=ROW_INTERNAL_PADY)

        # 3. Arg Data 2
        self.arg_data_2_var = tk.StringVar()
        self.arg_label_2 = tk.Label(self.frame, textvariable=self.arg_data_2_var, width=14, anchor="w", bg="#f4f4f4", fg="#880000", font=("Arial", 8), relief="flat")
        self.arg_label_2.pack(side="right", fill="y", padx=(1, 1), pady=ROW_INTERNAL_PADY)

        # 4. Arg Data 1
        self.arg_data_1_var = tk.StringVar()
        self.arg_label_1 = tk.Label(self.frame, textvariable=self.arg_data_1_var, width=14, anchor="w", bg="#f4f4f4", fg="#880000", font=("Arial", 8), relief="flat")
        self.arg_label_1.pack(side="right", fill="y", padx=(1, 1), pady=ROW_INTERNAL_PADY)

        # 5. Command Data (Left of Right Block)
        self.cmd_result_var = tk.StringVar()
        self.cmd_label = tk.Label(self.frame, textvariable=self.cmd_result_var, width=20, anchor="w", bg="#e8e8e8", fg="#000088", font=("Arial", 9, "italic"), relief="flat")
        self.cmd_label.pack(side="right", fill="y", padx=(5, 2), pady=ROW_INTERNAL_PADY)

        # --- CENTER ---
        self.text_container = tk.Frame(self.frame, bg="white", bd=0)
        self.text_container.pack(side="left", fill="x", expand=True, padx=(0, 0), pady=ROW_INTERNAL_PADY)

        self.text_var = tk.StringVar()
        self.text_var.trace_add("write", self._on_text_change)
        
        self.entry = tk.Entry(self.text_container, textvariable=self.text_var, relief="flat", bg="white", font=("Consolas", 11))
        self.entry.pack(side="left", fill="x", expand=True, ipady=ENTRY_HEIGHT_PAD, padx=5)
        
        self.entry.bind("<Up>", lambda e: self.focus_neighbor(self.row_index, -1))
        self.entry.bind("<Down>", lambda e: self.focus_neighbor(self.row_index, 1))
        self.entry.bind("<Return>", lambda e: self.focus_neighbor(self.row_index, 1))

    def _on_combo_change(self, event):
        self.update_callback()

    def _on_quick_select(self, event):
        label = self.quick_combo.get()
        if label in self.quick_input_map:
            code_to_insert = self.quick_input_map[label]
            self.text_var.set(code_to_insert)
            self.quick_combo.set("")
            self.entry.focus_set()

    def _on_text_change(self, *args):
        raw_text = self.text_var.get().upper()
        clean_text = raw_text.replace(" ", "")
        
        main_desc = ""
        arg_1_txt = ""
        arg_2_txt = ""
        arg_3_txt = ""
        
        if self.command_map and clean_text:
            found_items = []
            sorted_keys = sorted(self.command_map.keys(), key=len, reverse=True)
            text_len = len(clean_text)
            mask = [False] * text_len
            
            for key in sorted_keys:
                key_clean = key.replace(" ", "").upper()
                if not key_clean: continue
                search_start = 0
                while True:
                    idx = clean_text.find(key_clean, search_start)
                    if idx == -1: break
                    match_len = len(key_clean)
                    is_taken = False
                    for i in range(idx, idx + match_len):
                        if mask[i]:
                            is_taken = True
                            break
                    if not is_taken:
                        found_items.append((idx, key, self.command_map[key]))
                        for i in range(idx, idx + match_len):
                            mask[i] = True
                    search_start = idx + 1
            
            found_items.sort(key=lambda x: x[0])
            
            if found_items:
                main_idx = -1
                last_high_prio_idx = -1
                for i, (idx, code, desc) in enumerate(found_items):
                    code_clean = code.replace(" ", "").upper()
                    is_high = False
                    for prefix in self.consumption_rules:
                        if code_clean.startswith(prefix):
                            is_high = True
                            break
                    if is_high:
                        last_high_prio_idx = i
                
                if last_high_prio_idx != -1:
                    main_idx = last_high_prio_idx
                else:
                    main_idx = len(found_items) - 1
                
                main_desc = found_items[main_idx][2]
                left_args = []
                if main_idx > 0:
                    pre_items = found_items[:main_idx]
                    start_idx = max(0, len(pre_items) - 3)
                    left_args = pre_items[start_idx:]
                
                if len(left_args) > 0: arg_1_txt = left_args[0][2]
                if len(left_args) > 1: arg_2_txt = left_args[1][2]
                if len(left_args) > 2: arg_3_txt = left_args[2][2]

        self.cmd_result_var.set(main_desc)
        self.arg_data_1_var.set(arg_1_txt)
        self.arg_data_2_var.set(arg_2_txt)
        self.arg_data_3_var.set(arg_3_txt)
        self.update_callback()

    def refresh(self):
        self._on_text_change()

    def get_text_length(self):
        raw_text = self.text_var.get().replace(" ", "")
        length = len(raw_text)
        if length == 0: return 0
        return (length + 1) // 2

    def set_display_count(self, count):
        num_bytes = max(2, (count.bit_length() + 7) // 8)
        byte_data = count.to_bytes(num_bytes, byteorder='big')
        hex_str = byte_data.hex().upper()
        self.count_label.config(text=hex_str)

    def get_data(self):
        return {
            "c1": self.combo1.get(),
            "text": self.text_var.get(),
            "arg1": self.arg_data_1_var.get(),
            "arg2": self.arg_data_2_var.get(),
            "arg3": self.arg_data_3_var.get()
        }

    def set_data(self, data):
        self.combo1.set(data.get("c1", ""))
        self.text_var.set(data.get("text", ""))
        self.arg_data_1_var.set(data.get("arg1", ""))
        self.arg_data_2_var.set(data.get("arg2", ""))
        self.arg_data_3_var.set(data.get("arg3", ""))

    def focus(self):
        self.entry.focus_set()


# ==========================================
#               MAIN APPLICATION
# ==========================================

class DataEntryApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Unified Tool: Editor & Camera")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        
        # --- STORAGE INIT ---
        self._ensure_directories()
        self.command_map, self.quick_input_data = self.load_csv_data()
        self.hex_codes_for_parsing = []
        self.command_arg_counts = {} 
        self._load_parsing_data()
        self.consumption_rules = ["D8","14","15","16","17","59","5A","5B","5C","B5"] 
        self.fields = ["INIT", "MAIN", "TALK", "SCOUT", "CROSS", "TOUCH", "E06", "E07"]
        self.data_store = {}
        for field in self.fields:
            self.data_store[field] = [{"c1": "", "text": "", "arg1": "", "arg2": "", "arg3": ""} for _ in range(NUM_ROWS)]
        self.target_file_path = None 
        self.master_file_path = ""   
        self.current_field = "INIT"
        self.rows = []
        self.nav_buttons = {}

        # --- CAMERA STATE INIT ---
        self.pm = None
        self.game_module = None
        self.addresses = None
        self.freecam_enabled = False
        self.movement_mode = "standard"
        
        # Movement physics
        self.vel_x, self.vel_y, self.vel_z = 0.0, 0.0, 0.0
        self.current_yaw, self.current_pitch = 0.0, 0.0
        self.target_yaw, self.target_pitch = 0.0, 0.0
        
        # Input State Tracking
        self.left_click_last_state = False
        self.right_click_last_state = False  
        
        self._setup_screen_center()

        # --- TABS SETUP ---
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)

        # Thread-safe tab tracking for keyboard hooks
        self.current_tab_index = 0

        # Tab 1: Editor
        self.tab_editor = tk.Frame(self.notebook, bg="#d9d9d9")
        self.notebook.add(self.tab_editor, text="Worker Editor")

        # Tab 2: Camera
        self.tab_camera = tk.Frame(self.notebook, bg="#d9d9d9") # Matches Tab 1 bg
        self.notebook.add(self.tab_camera, text="Camera Operations")

        # Bind tab change event to update thread-safe tracker and auto-disable camera
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # --- KEYBOARD HOOKS FOR CAMERA ---
        # Hotkeys check self.current_tab_index to ensure they only run on Tab 1
        keyboard.add_hotkey('9', lambda: self.toggle_camera_mode('standard') if self.current_tab_index == 1 else None)
        keyboard.add_hotkey('0', lambda: self.toggle_camera_mode('directional') if self.current_tab_index == 1 else None)
        keyboard.add_hotkey('-', lambda: self.disable_camera() if self.current_tab_index == 1 else None)
        keyboard.add_hotkey('end', lambda: self.disable_camera() if self.current_tab_index == 1 else None)

        # --- BUILD INTERFACES ---
        self._build_editor_tab()
        self._build_camera_tab()

        # --- START BACKGROUND POLLING ---
        self._background_mouse_poll()

    def _on_tab_changed(self, event):
        """Updates tab index tracking and auto-disables camera when switching to Editor."""
        self.current_tab_index = self.notebook.index("current")
        # If user switches back to Editor while camera is active, disable it safely
        if self.current_tab_index == 0 and self.freecam_enabled:
            self.disable_camera()

    # ==========================================
    #           TAB 1: EDITOR BUILD
    # ==========================================
    def _build_editor_tab(self):
        self.main_container = tk.Frame(self.tab_editor, bg="#d9d9d9")
        self.main_container.pack(fill="both", expand=True, padx=OUTER_MARGIN, pady=OUTER_MARGIN)

        self._setup_top_nav()
        self._setup_editor_area()
        self._setup_footer()
        
        self._highlight_active_button()
        self.load_current_field_data()

    def _setup_top_nav(self):
        nav_frame = tk.Frame(self.main_container, bg="#333", pady=10, padx=10)
        nav_frame.pack(fill="x")
        tk.Label(nav_frame, text="CONTEXT:", bg="#333", fg="#aaa", font=("Arial", 10, "bold")).pack(side="left", padx=(0, 15))
        for field in self.fields:
            btn = tk.Button(nav_frame, text=field, command=lambda f=field: self.switch_context(f), font=("Arial", 10, "bold"), width=10, relief="flat", pady=5)
            btn.pack(side="left", padx=2)
            self.nav_buttons[field] = btn

    def _setup_editor_area(self):
        header_frame = tk.Frame(self.main_container, bg="#e0e0e0", pady=4)
        header_frame.pack(fill="x", padx=0, pady=(15, 0))
        
        tk.Label(header_frame, text="JUMP TAG", bg="#e0e0e0", width=10, anchor="w", font=("Arial", 8, "bold")).pack(side="left")
        tk.Label(header_frame, text="xOFFSET", bg="#e0e0e0", width=10, anchor="w", font=("Consolas", 9, "bold")).pack(side="left", padx=(0, 10))
        tk.Label(header_frame, text="CODE INPUT", bg="#e0e0e0", font=("Arial", 8, "bold")).pack(side="left")
        
        tk.Label(header_frame, text="QUICK INPUT", bg="#e0e0e0", width=18, anchor="w", font=("Arial", 8, "bold")).pack(side="right", padx=(5, 0))
        tk.Label(header_frame, text="ARG 3", bg="#e0e0e0", width=12, anchor="w", font=("Arial", 8, "bold")).pack(side="right", padx=(1, 0))
        tk.Label(header_frame, text="ARG 2", bg="#e0e0e0", width=12, anchor="w", font=("Arial", 8, "bold")).pack(side="right", padx=(1, 0))
        tk.Label(header_frame, text="ARG 1", bg="#e0e0e0", width=12, anchor="w", font=("Arial", 8, "bold")).pack(side="right", padx=(1, 0))
        tk.Label(header_frame, text="COMMAND DATA", bg="#e0e0e0", width=20, anchor="w", font=("Arial", 8, "bold")).pack(side="right", padx=(5, 5))

        container_border = tk.Frame(self.main_container, bg="#888", bd=1)
        container_border.pack(fill="both", expand=True)
        self.editor_frame = tk.Frame(container_border, bg="#f0f0f0")
        self.editor_frame.pack(fill="both", expand=True)

        for i in range(NUM_ROWS):
            row = RowWidget(self.editor_frame, i, self.recalculate_cumulative, self.move_focus, self.command_map, self.quick_input_data, self.consumption_rules)
            self.rows.append(row)

    def _setup_footer(self):
        footer = tk.Frame(self.main_container, pady=10, bg="#d9d9d9")
        footer.pack(fill="x")
        
        top_footer = tk.Frame(footer, bg="#d9d9d9")
        top_footer.pack(fill="x", expand=True)

        left_section = tk.Frame(top_footer, bg="#d9d9d9")
        left_section.pack(side="left", fill="both", expand=True)
        right_section = tk.Frame(top_footer, bg="#d9d9d9")
        right_section.pack(side="right", fill="y", padx=(10, 0))

        left_section.columnconfigure(1, weight=1)
        tk.Label(left_section, text="Entry Table:", bg="#d9d9d9", font=("Arial", 9)).grid(row=0, column=0, sticky="w", pady=4)
        self.entry_table_var = tk.StringVar()
        entry_lbl = tk.Label(left_section, textvariable=self.entry_table_var, bg="#eee", anchor="w", font=("Consolas", 10), relief="sunken", padx=5, pady=2)
        entry_lbl.grid(row=0, column=1, sticky="ew", padx=(10, 40), pady=4)

        tk.Label(left_section, text="Jump Table:", bg="#d9d9d9", font=("Arial", 9)).grid(row=1, column=0, sticky="w", pady=4)
        self.jump_table_var = tk.StringVar()
        jump_lbl = tk.Label(left_section, textvariable=self.jump_table_var, bg="#eee", anchor="w", font=("Consolas", 10), relief="sunken", padx=5, pady=2)
        jump_lbl.grid(row=1, column=1, sticky="ew", padx=(10, 40), pady=4)

        btn_width = 22
        tk.Button(right_section, text="Save Worker Profile", command=self.save_worker, bg="#cceeff", width=btn_width).pack(pady=2)
        tk.Button(right_section, text="Load Worker Profile", command=self.load_worker, bg="#cceeff", width=btn_width).pack(pady=2)
        tk.Frame(right_section, height=5, bg="#d9d9d9").pack()
        tk.Button(right_section, text="Save Function (Page)", command=self.save_function, bg="#ccffcc", width=btn_width).pack(pady=2)
        tk.Button(right_section, text="Load Function (Page)", command=self.load_function, bg="#ccffcc", width=btn_width).pack(pady=2)

        tk.Frame(footer, height=10, bg="#d9d9d9").pack(fill="x")
        bottom_row_frame = tk.Frame(footer, bg="#d9d9d9")
        bottom_row_frame.pack(side="bottom", pady=5)

        master_file_frame = tk.Frame(bottom_row_frame, bg="#d9d9d9", bd=1, relief="solid")
        master_file_frame.pack(side="left", padx=(0, 300), fill="y")
        tk.Button(master_file_frame, text="SELECT FILE", command=self.select_master_file, bg="#555", fg="white", font=("Arial", 9, "bold"), width=20).pack(pady=(5,2), padx=5)
        self.master_file_label = tk.Label(master_file_frame, text="No File Selected", bg="#d9d9d9", fg="#888", font=("Arial", 8, "italic"), width=25)
        self.master_file_label.pack(pady=(0, 5))

        left_btn_frame = tk.Frame(bottom_row_frame, bg="#d9d9d9")
        left_btn_frame.pack(side="left", padx=(0, 20))
        tk.Button(left_btn_frame, text="Scan for Custom Workers", command=self.scan_custom_workers, bg="#666", fg="white", font=("Arial", 9, "bold"), width=25).pack(pady=(0, 2))
        tk.Button(left_btn_frame, text="Update Custom Worker", command=self.update_custom_worker, bg="#666", fg="white", font=("Arial", 9, "bold"), width=25).pack(pady=(2, 0))

        btn = tk.Button(bottom_row_frame, text="ADD WORKER TO EBP", command=self.print_data, bg="#444", fg="white", font=("Arial", 10, "bold"), relief="flat", padx=20, pady=12)
        btn.pack(side="left")

    # ==========================================
    #           TAB 2: CAMERA BUILD
    # ==========================================
    def _build_camera_tab(self):
        # Use main container to match margins of Tab 1
        self.cam_main_container = tk.Frame(self.tab_camera, bg="#d9d9d9")
        self.cam_main_container.pack(fill="both", expand=True, padx=OUTER_MARGIN, pady=OUTER_MARGIN)

        # 1. TOP NAV (Style Match)
        nav_frame = tk.Frame(self.cam_main_container, bg="#333", pady=10, padx=10)
        nav_frame.pack(fill="x")
        
        tk.Label(nav_frame, text="CAMERA MODES:", bg="#333", fg="#aaa", font=("Arial", 10, "bold")).pack(side="left", padx=(0, 15))
        
        self.btn_cam_std = tk.Button(nav_frame, text="STANDARD (9)", command=lambda: self.toggle_camera_mode('standard'), font=("Arial", 10, "bold"), width=15, relief="flat", pady=5, bg="#e1e1e1")
        self.btn_cam_std.pack(side="left", padx=2)

        self.btn_cam_dir = tk.Button(nav_frame, text="DIRECTIONAL (0)", command=lambda: self.toggle_camera_mode('directional'), font=("Arial", 10, "bold"), width=15, relief="flat", pady=5, bg="#e1e1e1")
        self.btn_cam_dir.pack(side="left", padx=2)

        self.btn_cam_off = tk.Button(nav_frame, text="DISABLE (-)", command=self.disable_camera, font=("Arial", 10, "bold"), width=15, relief="flat", pady=5, bg="#ffcccc", fg="#880000")
        self.btn_cam_off.pack(side="right", padx=2)

        # 2. HEADER INFO
        header_frame = tk.Frame(self.cam_main_container, bg="#e0e0e0", pady=4)
        header_frame.pack(fill="x", padx=0, pady=(15, 0))
        
        tk.Label(header_frame, text="STATUS", bg="#e0e0e0", width=15, anchor="w", font=("Arial", 8, "bold")).pack(side="left", padx=(10,0))
        self.lbl_cam_status = tk.Label(header_frame, text="INACTIVE", bg="#e0e0e0", fg="#555", font=("Arial", 9, "bold"))
        self.lbl_cam_status.pack(side="left")
        
        tk.Label(header_frame, text="LOG OUTPUT (L-Click Cam, R-Click Char)", bg="#e0e0e0", font=("Arial", 8, "bold")).pack(side="right", padx=(0,10))

        # 3. CONTENT AREA (Text Box styled like Entry)
        container_border = tk.Frame(self.cam_main_container, bg="#888", bd=1)
        container_border.pack(fill="both", expand=True)
        
        content_frame = tk.Frame(container_border, bg="#f0f0f0")
        content_frame.pack(fill="both", expand=True)

        # Scrollable Text Box (White bg, Consolas font - matches Tab 1 entries)
        self.log_text = tk.Text(content_frame, bg="white", fg="black", font=("Consolas", 10), relief="flat", padx=10, pady=10)
        self.log_text.pack(side="left", fill="both", expand=True)
        
        scroll = tk.Scrollbar(content_frame, command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scroll.set)

        # 4. FOOTER (Instructions + Utility)
        footer = tk.Frame(self.cam_main_container, pady=10, bg="#d9d9d9")
        footer.pack(fill="x")
        
        instr_frame = tk.Frame(footer, bg="#d9d9d9")
        instr_frame.pack(side="left")
        
        info_txt = "Controls: WASD/Space/F (Move) | G/J/Y/H (Rotate/Pan) | Scroll (Depth)"
        tk.Label(instr_frame, text=info_txt, font=("Arial", 9), bg="#d9d9d9", fg="#555").pack(anchor="w")
        
        btn_clear = tk.Button(footer, text="CLEAR LOG", command=lambda: self.log_text.delete(1.0, tk.END), bg="#ccc", font=("Arial", 8, "bold"), relief="flat")
        btn_clear.pack(side="right")

    # ==========================================
    #           CAMERA LOGIC IMPLEMENTATION
    # ==========================================

    def _background_mouse_poll(self):
        """Runs continuously to check for right-clicks when on the camera tab, independent of freecam status."""
        if self.current_tab_index == 1:
            try:
                if mouse.is_pressed('right'):
                    if not self.right_click_last_state:
                        self._log_char_pos_standalone()
                    self.right_click_last_state = True
                else:
                    self.right_click_last_state = False
            except Exception:
                pass
        # Check again in 20ms
        self.root.after(20, self._background_mouse_poll)
    
    def _setup_screen_center(self):
        user32 = ctypes.windll.user32
        screen_width = user32.GetSystemMetrics(0)
        screen_height = user32.GetSystemMetrics(1)
        self.screen_center_x = screen_width // 2
        self.screen_center_y = screen_height // 2

    def calculate_addresses(self):
        try:
            self.pm = pymem.Pymem(PROCESS_NAME)
            self.game_module = pymem.process.module_from_name(self.pm.process_handle, PROCESS_NAME).lpBaseOfDll
            self.addresses = {
                "pos_x": self.game_module + CAMERA_POS_OFFSET,
                "pos_y": self.game_module + CAMERA_POS_OFFSET + 4,
                "pos_z": self.game_module + CAMERA_POS_OFFSET + 8,
                "target_x": self.game_module + CAMERA_TARGET_OFFSET,
                "target_y": self.game_module + CAMERA_TARGET_OFFSET + 4,
                "target_z": self.game_module + CAMERA_TARGET_OFFSET + 8,
                "screen_depth": self.game_module + SCREEN_DEPTH_OFFSET,
                "char_pos_x": self.game_module + 0xF25D78,
                "char_pos_y": self.game_module + 0xF25D7C,
                "char_pos_z": self.game_module + 0xF25D80,
                "char_rot_ptr": self.game_module + 0xEA2280,  # <-- ADDED FOR ROTATION
            }
            for i, patch_info in enumerate(PATCH_LOCATIONS):
                self.addresses[f"patch_{i+1}"] = self.game_module + patch_info["offset"]
            return True
        except Exception:
            return False

    def apply_memory_patch(self, patch_type):
        if not self.pm: return False
        try:
            for i, patch_info in enumerate(PATCH_LOCATIONS):
                addr_key = f"patch_{i+1}"
                address = self.addresses[addr_key]
                data = patch_info[patch_type]
                self.pm.write_bytes(address, data, len(data))
            return True
        except Exception as e:
            print(f"Patch Error ({patch_type}): {e}")
            return False

    def disable_camera(self):
        """Emergency exit / Unlock Cursor"""
        if self.freecam_enabled:
            self.freecam_enabled = False
            ctypes.windll.user32.ShowCursor(True)
            self.apply_memory_patch("original")
            mouse.unhook_all()
            self._update_cam_ui_state()

    def toggle_camera_mode(self, mode):
        """Logic for '9' and '0' keys"""
        # If we are already enabled and in the same mode, disable it (Toggle behavior)
        if self.freecam_enabled and self.movement_mode == mode:
            self.disable_camera()
            return

        # If we are enabled but switching modes, just switch mode
        if self.freecam_enabled and self.movement_mode != mode:
            self.movement_mode = mode
            self._update_cam_ui_state()
            return
        
        # If disabled, Enable it
        if not self.calculate_addresses():
            messagebox.showerror("Error", "Could not find FFX.exe")
            return

        if self.apply_memory_patch("patch"):
            self.freecam_enabled = True
            self.movement_mode = mode
            ctypes.windll.user32.ShowCursor(False)
            
            # Reset Target for stability
            try:
                px = self.pm.read_float(self.addresses['pos_x'])
                py = self.pm.read_float(self.addresses['pos_y'])
                pz = self.pm.read_float(self.addresses['pos_z'])
                self.pm.write_float(self.addresses['target_x'], px)
                self.pm.write_float(self.addresses['target_y'], py)
                self.pm.write_float(self.addresses['target_z'], pz + 10.0)
                
                # Init logic vars
                fx = self.pm.read_float(self.addresses['target_x']) - px
                fy = self.pm.read_float(self.addresses['target_y']) - py
                fz = self.pm.read_float(self.addresses['target_z']) - pz
                
                self.current_yaw = self.target_yaw = math.atan2(fz, fx)
                self.current_pitch = self.target_pitch = math.atan2(fy, math.sqrt(fx**2 + fz**2))
                self.vel_x = self.vel_y = self.vel_z = 0.0
                
                mouse.move(self.screen_center_x, self.screen_center_y)
                mouse.hook(self._mouse_hook_callback)
                
                self._update_cam_ui_state()
                self._camera_loop()
                
            except Exception as e:
                self.disable_camera()
                messagebox.showerror("Error", f"Failed to init camera: {e}")

    def _update_cam_ui_state(self):
        # Update UI Colors based on state
        if not self.freecam_enabled:
            self.btn_cam_std.config(bg="#e1e1e1", fg="black")
            self.btn_cam_dir.config(bg="#e1e1e1", fg="black")
            self.lbl_cam_status.config(text="INACTIVE", fg="#555")
        else:
            self.lbl_cam_status.config(text=f"ACTIVE ({self.movement_mode.upper()})", fg="#00aa00")
            if self.movement_mode == "standard":
                self.btn_cam_std.config(bg="#007acc", fg="white")
                self.btn_cam_dir.config(bg="#e1e1e1", fg="black")
            else:
                self.btn_cam_std.config(bg="#e1e1e1", fg="black")
                self.btn_cam_dir.config(bg="#007acc", fg="white")

    def _mouse_hook_callback(self, event):
        # Handle Scroll Wheel
        if isinstance(event, mouse.WheelEvent) and self.freecam_enabled:
            try:
                cur = self.pm.read_float(self.addresses['screen_depth'])
                new = cur + (SCREEN_DEPTH_SCROLL_SPEED if event.delta > 0 else -SCREEN_DEPTH_SCROLL_SPEED)
                if new != cur:
                    self.pm.write_float(self.addresses['screen_depth'], new)
            except: pass

    def _camera_loop(self):
        if not self.freecam_enabled: return
        
        # Pause camera tracking if user is not on the camera tab
        if self.current_tab_index != 1:
            self.root.after(TICK_RATE_MS, self._camera_loop)
            return

        try:
            # 1. Mouse Look
            cx, cy = mouse.get_position()
            dx = cx - self.screen_center_x
            dy = cy - self.screen_center_y
            
            if dx != 0 or dy != 0:
                mouse.move(self.screen_center_x, self.screen_center_y)
                self.target_yaw -= dx * MOUSE_SENSITIVITY
                self.target_pitch += dy * MOUSE_SENSITIVITY
                self.target_pitch = max(-math.pi/2 + 0.01, min(math.pi/2 - 0.01, self.target_pitch))

            # 2. Left Click Check (Camera Output)
            if mouse.is_pressed('left'):
                if not self.left_click_last_state:
                    self._log_camera_pos()
                self.left_click_last_state = True
            else:
                self.left_click_last_state = False

            # 3. Physics & Update
            self._update_physics()

            # Schedule Next Tick
            self.root.after(TICK_RATE_MS, self._camera_loop)

        except Exception as e:
            print(f"Loop Error: {e}")
            self.disable_camera()

    def _update_physics(self):
        # Smooth Look
        self.current_yaw += (self.target_yaw - self.current_yaw) * AIM_SMOOTHING
        self.current_pitch += (self.target_pitch - self.current_pitch) * AIM_SMOOTHING

        # Read Pos
        px = self.pm.read_float(self.addresses['pos_x'])
        py = self.pm.read_float(self.addresses['pos_y'])
        pz = self.pm.read_float(self.addresses['pos_z'])

        # Calculate Forward Vector
        fwd_x = math.cos(self.current_pitch) * math.cos(self.current_yaw)
        fwd_y = math.sin(self.current_pitch)
        fwd_z = math.cos(self.current_pitch) * math.sin(self.current_yaw)

        # Update Target in Memory (for rotation)
        self.pm.write_float(self.addresses['target_x'], px + fwd_x)
        self.pm.write_float(self.addresses['target_y'], py + fwd_y)
        self.pm.write_float(self.addresses['target_z'], pz + fwd_z)

        # Calculate Movement Forces
        force_x, force_y, force_z = 0.0, 0.0, 0.0
        
        # Standard Mode Logic (Plane) / Directional logic handled by rotation calcs
        if self.movement_mode == 'directional':
             # Directional: W moves towards where camera looks (3D)
             # Basic implementation: "Forward" is camera forward
             up_x, up_y, up_z = 0.0, 1.0, 0.0
             right_x = (fwd_y * up_z) - (fwd_z * up_y)
             right_z = (fwd_x * up_y) - (fwd_y * up_x)
             # Normalize right
             rmag = math.sqrt(right_x**2 + right_z**2)
             if rmag != 0: right_x/=rmag; right_z/=rmag
             
             if keyboard.is_pressed('y'): force_x += fwd_x; force_y += fwd_y; force_z += fwd_z
             if keyboard.is_pressed('h'): force_x -= fwd_x; force_y -= fwd_y; force_z -= fwd_z
             if keyboard.is_pressed('g'): force_x += right_x; force_z += right_z
             if keyboard.is_pressed('j'): force_x -= right_x; force_z -= right_z

        else:
            # Standard: W moves forward on horizontal plane only
            plane_fwd_x = fwd_x
            plane_fwd_z = fwd_z
            mag = math.sqrt(plane_fwd_x**2 + plane_fwd_z**2)
            if mag != 0: 
                plane_fwd_x /= mag
                plane_fwd_z /= mag
            
            right_x = -plane_fwd_z
            right_z = plane_fwd_x

            if keyboard.is_pressed('y'): force_x += plane_fwd_x; force_z += plane_fwd_z
            if keyboard.is_pressed('h'): force_x -= plane_fwd_x; force_z -= plane_fwd_z
            if keyboard.is_pressed('g'): force_x += right_x; force_z += right_z
            if keyboard.is_pressed('j'): force_x -= right_x; force_z -= right_z

        if keyboard.is_pressed('space'): force_y += 1.0
        if keyboard.is_pressed('f'): force_y -= 1.0

        # Apply Velocity
        self.vel_x += force_x * MOVEMENT_SPEED
        self.vel_y += force_y * MOVEMENT_SPEED
        self.vel_z += force_z * MOVEMENT_SPEED

        # Apply to Memory if moving
        if abs(self.vel_x) > 0.01 or abs(self.vel_y) > 0.01 or abs(self.vel_z) > 0.01:
            tx = self.pm.read_float(self.addresses['target_x'])
            ty = self.pm.read_float(self.addresses['target_y'])
            tz = self.pm.read_float(self.addresses['target_z'])
            
            self.pm.write_float(self.addresses['pos_x'], px + self.vel_x)
            self.pm.write_float(self.addresses['pos_y'], py + self.vel_y)
            self.pm.write_float(self.addresses['pos_z'], pz + self.vel_z)
            self.pm.write_float(self.addresses['target_x'], tx + self.vel_x)
            self.pm.write_float(self.addresses['target_y'], ty + self.vel_y)
            self.pm.write_float(self.addresses['target_z'], tz + self.vel_z)

        # Damping
        self.vel_x *= MOVEMENT_DAMPING
        self.vel_y *= MOVEMENT_DAMPING
        self.vel_z *= MOVEMENT_DAMPING

    def _float_to_game_hex(self, val):
        val_int = int(round(val))
        val_int = max(-32768, min(32767, val_int))
        return struct.pack('<h', val_int).hex().upper()

    def _log_camera_pos(self):
        try:
            px = self.pm.read_float(self.addresses['pos_x'])
            py = self.pm.read_float(self.addresses['pos_y'])
            pz = self.pm.read_float(self.addresses['pos_z'])
            
            tx = self.pm.read_float(self.addresses['target_x'])
            ty = self.pm.read_float(self.addresses['target_y'])
            tz = self.pm.read_float(self.addresses['target_z'])
            
            # Read Screen Depth
            depth_val = self.pm.read_float(self.addresses['screen_depth'])
            h_depth = self._float_to_game_hex(depth_val)

            # Calc Vector
            vx, vy, vz = tx - px, ty - py, tz - pz
            scale = 10.0
            etx, ety, etz = px + (vx*scale), py + (vy*scale), pz + (vz*scale)

            # Format
            h_px = self._float_to_game_hex(px)
            h_py = self._float_to_game_hex(py)
            h_pz = self._float_to_game_hex(pz)
            
            h_tx = self._float_to_game_hex(etx)
            h_ty = self._float_to_game_hex(ety)
            h_tz = self._float_to_game_hex(etz)

            line1 = f"AE{h_px} AE{h_py} AE{h_pz} D80260  (Cam Pos)\n"
            line2 = f"AE{h_tx} AE{h_ty} AE{h_tz} D82060  (Cam Target)\n"
            line3 = f"AE{h_depth} D83B60          (Screen Depth)\n"
            
            self.log_text.insert(tk.END, "-"*40 + "\n")
            self.log_text.insert(tk.END, line1)
            self.log_text.insert(tk.END, line2)
            self.log_text.insert(tk.END, line3)
            self.log_text.see(tk.END)
        except Exception as e:
            self.log_text.insert(tk.END, f"Error capturing: {e}\n")

    def _log_char_pos_standalone(self):
        # We need to make sure we are hooked into memory first, 
        # just in case the user hasn't turned the freecam on yet.
        if not self.pm or not self.addresses:
            if not self.calculate_addresses():
                self.log_text.insert(tk.END, "Error: Game not found. Please ensure FFX is running.\n")
                self.log_text.see(tk.END)
                return

        try:
            # Position Data
            cx = self.pm.read_float(self.addresses['char_pos_x'])
            cy = self.pm.read_float(self.addresses['char_pos_y'])
            cz = self.pm.read_float(self.addresses['char_pos_z'])

            h_cx = self._float_to_game_hex(cx)
            h_cy = self._float_to_game_hex(cy)
            h_cz = self._float_to_game_hex(cz)

            line1 = f"AE{h_cx} AE{h_cy} AE{h_cz} D81300  (Char Pos'n)\n"

            # --- NEW: Rotation Data ---
            rot_ptr = self.pm.read_int(self.addresses['char_rot_ptr'])
            rot = self.pm.read_float(rot_ptr + 0x168)
            h_rot = self._float_to_game_hex(rot * 100)
            
            line2 = f"AE{h_rot} AE6400 17 D89500  (Char Rot'n)\n"

            self.log_text.insert(tk.END, "-"*40 + "\n")
            self.log_text.insert(tk.END, line1)
            self.log_text.insert(tk.END, line2)
            self.log_text.see(tk.END)
        except Exception as e:
            self.log_text.insert(tk.END, f"Error capturing Char Pos/Rot: {e}\n")
            # If it fails, wipe PM so it can try to reattach next time
            self.pm = None 

    # ==========================================
    #           SHARED / EDITOR UTILS
    # ==========================================
    # (These methods remain largely unchanged from CODE 1 but are now part of the class)
    
    def _ensure_directories(self):
        os.makedirs(WORKER_DIR, exist_ok=True)
        os.makedirs(ENTRY_DIR, exist_ok=True)

    def _load_parsing_data(self):
        self.hex_codes_for_parsing = []
        self.command_arg_counts = {}
        if os.path.exists(CSV_FILENAME):
            try:
                with open(CSV_FILENAME, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if len(row) >= 1:
                            code = row[0].strip().replace(" ", "").lower()
                            if code:
                                self.hex_codes_for_parsing.append(code)
                                args_count = 0
                                if len(row) >= 3:
                                    example_str = row[2].strip()
                                    if example_str:
                                        parts = example_str.split()
                                        if len(parts) > 0: args_count = len(parts) - 1
                                self.command_arg_counts[code] = args_count
                self.hex_codes_for_parsing.sort(key=len, reverse=True)
            except Exception: pass

    def load_csv_data(self):
        cmd_map = {}
        quick_data = {'labels': [], 'map': {}}
        if os.path.exists(CSV_FILENAME):
            try:
                with open(CSV_FILENAME, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if len(row) >= 2:
                            key = row[0].strip()
                            val = row[1].strip()
                            if key: cmd_map[key] = val
                        if len(row) >= 4:
                            code = row[2].strip()
                            label = row[3].strip()
                            if label:
                                quick_data['labels'].append(label)
                                quick_data['map'][label] = code
            except Exception as e:
                messagebox.showerror("CSV Error", f"Failed to read {CSV_FILENAME}:\n{e}")
        return cmd_map, quick_data

    # --- Navigation ---
    def move_focus(self, current_index, direction):
        new_index = current_index + direction
        if 0 <= new_index < len(self.rows):
            self.rows[new_index].focus()

    def switch_context(self, new_field):
        if self.current_field == new_field: return
        self.save_current_field_data()
        self.current_field = new_field
        self._highlight_active_button()
        self.load_current_field_data()

    def _highlight_active_button(self):
        for field, btn in self.nav_buttons.items():
            if field == self.current_field:
                btn.config(bg="#007acc", fg="white")
            else:
                btn.config(bg="#e1e1e1", fg="black")

    def save_current_field_data(self):
        data_list = []
        for row in self.rows:
            data_list.append(row.get_data())
        self.data_store[self.current_field] = data_list

    def get_previous_pages_total(self):
        total = 0
        current_idx = self.fields.index(self.current_field)
        for i in range(current_idx):
            field_name = self.fields[i]
            rows = self.data_store[field_name]
            for r in rows:
                txt = r['text'].replace(" ", "")
                if txt: total += (len(txt) + 1) // 2
        return total

    def load_current_field_data(self):
        data_list = self.data_store[self.current_field]
        for i, row in enumerate(self.rows):
            if i < len(data_list):
                row.set_data(data_list[i])
            else:
                row.set_data({"c1": "", "text": "", "arg1": "", "arg2": "", "arg3": ""})
        self.recalculate_cumulative()
        self.refresh_all_rows()

    def recalculate_cumulative(self):
        running_total = self.get_previous_pages_total()
        for row in self.rows:
            row.set_display_count(running_total)
            running_total += row.get_text_length()
        self.update_footer_tables()
        
    def refresh_all_rows(self):
        for row in self.rows: row.refresh()

    def update_footer_tables(self):
        # Generate raw byte offsets for display in footer
        temp_store = self.data_store.copy()
        current_rows_data = []
        for row in self.rows: current_rows_data.append(row.get_data())
        temp_store[self.current_field] = current_rows_data

        entry_offsets = []
        jump_offsets = {f"j{i:02X}": None for i in range(12)}
        global_offset = 0
        
        for field in self.fields:
            entry_offsets.append(global_offset)
            rows = temp_store[field]
            for r in rows:
                tag = r['c1']
                if tag in jump_offsets and jump_offsets[tag] is None:
                    jump_offsets[tag] = global_offset
                txt = r['text'].replace(" ", "")
                length = 0
                if txt: length = (len(txt) + 1) // 2
                global_offset += length

        entry_str_parts = []
        for off in entry_offsets:
            b = off.to_bytes(4, byteorder='little')
            entry_str_parts.append(b.hex().upper())
        self.entry_table_var.set("  ".join(entry_str_parts))

        jump_str_parts = []
        for i in range(12):
            tag = f"j{i:02X}"
            off = jump_offsets[tag]
            if off is None: off = 0
            b = off.to_bytes(4, byteorder='little')
            jump_str_parts.append(b.hex().upper())
        self.jump_table_var.set("  ".join(jump_str_parts))

    # --- FILE IO ---
    def select_master_file(self):
        filename = filedialog.askopenfilename(title="Select Target Master File", filetypes=(("EBP Files", "*.ebp"), ("All Files", "*.*")))
        if filename:
            self.master_file_path = filename
            global k
            k = filename 
            display_name = os.path.basename(filename)
            if len(display_name) > 25: display_name = display_name[:22] + "..."
            self.master_file_label.config(text=display_name, fg="#000")

    def save_worker(self):
        self.save_current_field_data()
        filename = filedialog.asksaveasfilename(initialdir=WORKER_DIR, title="Save Worker Profile", filetypes=(("JSON Files", "*.json"), ("All Files", "*.*")), defaultextension=".json")
        if filename:
            try:
                with open(filename, 'w') as f: json.dump(self.data_store, f, indent=4)
                messagebox.showinfo("Success", "Worker Profile Saved Successfully.")
            except Exception as e: messagebox.showerror("Error", f"Failed to save worker:\n{e}")

    def load_worker(self):
        filename = filedialog.askopenfilename(initialdir=WORKER_DIR, title="Load Worker Profile", filetypes=(("JSON Files", "*.json"), ("All Files", "*.*")))
        if filename:
            try:
                with open(filename, 'r') as f: loaded_data = json.load(f)
                if not isinstance(loaded_data, dict): raise ValueError("Invalid file format")
                self.data_store = loaded_data
                for field in self.fields:
                    if field not in self.data_store:
                        self.data_store[field] = [{"c1": "", "text": "", "arg1": "", "arg2": "", "arg3": ""} for _ in range(NUM_ROWS)]
                self.load_current_field_data()
                messagebox.showinfo("Success", "Worker Profile Loaded.")
            except Exception as e: messagebox.showerror("Error", f"Failed to load worker:\n{e}")

    def save_function(self):
        self.save_current_field_data()
        default_name = f"{self.current_field}_data.json"
        filename = filedialog.asksaveasfilename(initialdir=ENTRY_DIR, initialfile=default_name, title=f"Save {self.current_field} Function", filetypes=(("JSON Files", "*.json"), ("All Files", "*.*")), defaultextension=".json")
        if filename:
            try:
                with open(filename, 'w') as f: json.dump(self.data_store[self.current_field], f, indent=4)
                messagebox.showinfo("Success", f"Function '{self.current_field}' Saved.")
            except Exception as e: messagebox.showerror("Error", f"Failed to save function:\n{e}")

    def load_function(self):
        filename = filedialog.askopenfilename(initialdir=ENTRY_DIR, title=f"Load Data into {self.current_field}", filetypes=(("JSON Files", "*.json"), ("All Files", "*.*")))
        if filename:
            try:
                with open(filename, 'r') as f: loaded_rows = json.load(f)
                if not isinstance(loaded_rows, list): raise ValueError("Invalid file format")
                self.data_store[self.current_field] = loaded_rows
                self.load_current_field_data()
                messagebox.showinfo("Success", f"Data loaded into '{self.current_field}'.")
            except Exception as e: messagebox.showerror("Error", f"Failed to load function:\n{e}")

    # --- Scanning & Updating Custom Workers ---
    def _scan_file_logic(self, filename):
        SIGNATURE = bytes.fromhex("81 82 83 80 71 72 73 70 61 62 63 60")
        SIG_OFFSET_FROM_START = OBJECT_TOTAL_SIZE - 12
        found_objects = []
        try:
            with open(filename, "rb") as f: file_data = f.read()
            search_index = 0
            while True:
                sig_index = file_data.find(SIGNATURE, search_index)
                if sig_index == -1: break 
                obj_start_index = sig_index - SIG_OFFSET_FROM_START
                if obj_start_index < 0:
                    search_index = sig_index + 1
                    continue
                obj_end_index = obj_start_index + OBJECT_TOTAL_SIZE
                found_object = file_data[obj_start_index : obj_end_index]
                found_objects.append((found_object, obj_start_index))
                search_index = sig_index + 1
            return found_objects
        except Exception as e:
            messagebox.showerror("Scan Error", f"An error occurred:\n{e}")
            return None

    def scan_custom_workers(self):
        if self.master_file_path and os.path.exists(self.master_file_path): filename = self.master_file_path
        else: filename = filedialog.askopenfilename(title="Scan File for Custom Workers", filetypes=(("All Files", "*.*"), ("EBP Files", "*.ebp")))
        if not filename: return
        found_objects = self._scan_file_logic(filename)
        if not found_objects:
            messagebox.showinfo("Scan Result", "No Custom Workers found.")
            return
        if len(found_objects) == 1:
            ans = messagebox.askyesno("Load Data", f"Found 1 object at 0x{found_objects[0][1]:X}.\nLoad into UI?")
            if ans: self.load_from_object(found_objects[0][0])
        else:
            self._show_worker_selection_dialog(found_objects, mode="load")

    def update_custom_worker(self):
        if self.master_file_path and os.path.exists(self.master_file_path): filename = self.master_file_path
        else: filename = filedialog.askopenfilename(title="Select File to Update", filetypes=(("All Files", "*.*"), ("EBP Files", "*.ebp")))
        if not filename: return
        found_objects = self._scan_file_logic(filename)
        if not found_objects:
            messagebox.showerror("Error", "No custom workers found in this file to update.")
            return
        self.target_file_path = filename
        if len(found_objects) == 1:
            ans = messagebox.askyesno("Update Worker", f"Found 1 worker at 0x{found_objects[0][1]:X}.\nOverwrite this worker with current UI data?")
            if ans: self._perform_update_write(filename, found_objects[0][1])
        else:
            self._show_worker_selection_dialog(found_objects, mode="update")

    def _show_worker_selection_dialog(self, found_objects, mode="load"):
        selection_win = tk.Toplevel(self.root)
        selection_win.title(f"Select Worker to {mode.title()}")
        selection_win.geometry("400x300")
        tk.Label(selection_win, text=f"Found {len(found_objects)} workers.", font=("Arial", 10)).pack(pady=10)
        list_frame = tk.Frame(selection_win)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        lb = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=("Consolas", 10))
        lb.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=lb.yview)
        for i, (data, offset) in enumerate(found_objects):
            lb.insert(tk.END, f"Worker #{i+1} - Offset: 0x{offset:08X}")
        
        def on_confirm():
            selection = lb.curselection()
            if selection:
                index = selection[0]
                data_bytes, offset = found_objects[index]
                if mode == "load": self.load_from_object(data_bytes)
                elif mode == "update":
                    if self.target_file_path and os.path.exists(self.target_file_path):
                        self._perform_update_write(self.target_file_path, offset)
                    else: messagebox.showerror("Error", "Target file path lost.")
                selection_win.destroy()
            else: messagebox.showwarning("Selection", "Please select a worker first.")
        tk.Button(selection_win, text=f"{mode.title()} Selected", command=on_confirm, bg="#007acc", fg="white").pack(pady=10)

    def _perform_update_write(self, filename, offset):
        try:
            with open(filename, "rb") as f:
                f.seek(offset)
                x_bytes = f.read(4)
                if len(x_bytes) < 4: raise ValueError("Unexpected EOF reading anchor X.")
                x_val = struct.unpack('<I', x_bytes)[0]
            new_object = self._generate_relative_update_object(x_val)
            if not new_object: return
            with open(filename, "r+b") as f:
                f.seek(offset)
                f.write(new_object)
            messagebox.showinfo("Success", "Worker updated successfully.")
        except Exception as e:
            messagebox.showerror("Update Error", f"Failed to update worker:\n{e}")

    def _generate_relative_update_object(self, anchor_x):
        self.save_current_field_data()
        temp_store = self.data_store
        entry_final_values = []
        jump_final_values = {f"j{i:02X}": None for i in range(12)}
        all_code_bytes = bytearray()
        current_relative_ptr = 0

        for field in self.fields:
            val = (anchor_x + current_relative_ptr) & 0xFFFFFFFF
            entry_final_values.append(val)
            rows = temp_store[field]
            for row in rows:
                tag = row['c1']
                if tag in jump_final_values and jump_final_values[tag] is None:
                    val = (anchor_x + current_relative_ptr) & 0xFFFFFFFF
                    jump_final_values[tag] = val
                txt = row['text'].replace(" ", "").strip()
                if txt:
                    try:
                        b_data = bytes.fromhex(txt)
                        all_code_bytes.extend(b_data)
                        current_relative_ptr += len(b_data)
                    except ValueError:
                        messagebox.showerror("Hex Error", f"Invalid Hex in {field}: {txt}")
                        return None
        
        for k, v in jump_final_values.items():
            if v is None: jump_final_values[k] = 0

        buffer = bytearray(b'\x3C' * OBJECT_TOTAL_SIZE)
        ENTRIES_START = 0
        JUMPS_START = 32
        CODE_START = 80
        FOOTER_START = OBJECT_TOTAL_SIZE - 16

        for i, val in enumerate(entry_final_values):
            start_idx = ENTRIES_START + (i * 4)
            buffer[start_idx : start_idx+4] = struct.pack('<I', val)
        
        sorted_jumps = [jump_final_values[f"j{i:02X}"] for i in range(12)]
        for i, val in enumerate(sorted_jumps):
            start_idx = JUMPS_START + (i * 4)
            buffer[start_idx : start_idx+4] = struct.pack('<I', val)

        code_len = len(all_code_bytes)
        max_code_space = FOOTER_START - CODE_START 
        if code_len > max_code_space:
            messagebox.showerror("Overflow", f"Code is too long! ({code_len} bytes). Max is {max_code_space}.")
            return None
        buffer[CODE_START : CODE_START + code_len] = all_code_bytes

        buffer[FOOTER_START : FOOTER_START+4] = struct.pack('<I', anchor_x)
        rest_hex = "81 82 83 80 71 72 73 70 61 62 63 60"
        buffer[FOOTER_START+4 : FOOTER_START+16] = bytes.fromhex(rest_hex)
        return buffer

    # --- Loading from Object (Parsing) ---
    def load_from_object(self, data_bytes):
        try:
            FOOTER_START = OBJECT_TOTAL_SIZE - 16
            footer = data_bytes[FOOTER_START:]
            ref_ptr = struct.unpack('<I', footer[0:4])[0]
            ENTRIES_START = 0
            JUMPS_START = 32
            CODE_START = 80
            
            entry_ptrs = []
            for i in range(8):
                offset = ENTRIES_START + (i*4)
                val = struct.unpack('<I', data_bytes[offset:offset+4])[0]
                entry_ptrs.append(val)
            
            jump_ptrs = []
            for i in range(12):
                offset = JUMPS_START + (i*4)
                val = struct.unpack('<I', data_bytes[offset:offset+4])[0]
                jump_ptrs.append(val)

            rel_entries = []
            for val in entry_ptrs:
                rel = val - ref_ptr
                rel_entries.append(rel)
            
            rel_jumps = {}
            for i, val in enumerate(jump_ptrs):
                if val != 0:
                    diff = val - ref_ptr
                    rel_jumps[diff] = f"j{i:02X}"

            full_code_block = data_bytes[CODE_START : FOOTER_START]
            new_data_store = {}

            for i, field in enumerate(self.fields):
                start_offset = rel_entries[i]
                if i < len(self.fields) - 1: end_offset = rel_entries[i+1]
                else: end_offset = len(full_code_block)

                if start_offset < 0 or start_offset >= len(full_code_block): chunk = b""
                else:
                    if end_offset > len(full_code_block): end_offset = len(full_code_block)
                    if end_offset < start_offset: end_offset = start_offset
                    chunk = full_code_block[start_offset : end_offset]

                page_rows = self._parse_chunk_to_rows(chunk, start_offset, rel_jumps)
                new_data_store[field] = page_rows

            self.data_store = new_data_store
            self.load_current_field_data()
            messagebox.showinfo("Success", "Data loaded into UI from Object.")
        except Exception as e:
            messagebox.showerror("Parsing Error", f"Failed to parse object:\n{e}")

    def _parse_chunk_to_rows(self, chunk, chunk_start_rel_offset, jump_map):
            raw_rows = []
            cursor = 0
            length = len(chunk)
            current_row_bytes = bytearray()
            current_row_tag = ""
            
            def format_raw_left_aligned(byte_data):
                hex_raw = byte_data.hex().upper()
                hex_raw = re.sub(r'(3C){11,}', '3C', hex_raw)
                chunks = [hex_raw[i:i+6] for i in range(0, len(hex_raw), 6)]
                return " ".join(chunks)

            def format_command_line(byte_data, cmd_code):
                cmd_len = len(cmd_code) // 2
                if len(byte_data) < cmd_len: return format_raw_left_aligned(byte_data)
                cmd_bytes = byte_data[-cmd_len:]
                remaining = byte_data[:-cmd_len]
                parts = [cmd_bytes.hex().upper()]
                arg_count = self.command_arg_counts.get(cmd_code, 0)
                for _ in range(arg_count):
                    if len(remaining) == 0: break
                    last_byte = remaining[-1]
                    if 0x67 <= last_byte <= 0x6A:
                        arg_chunk = remaining[-1:]
                        remaining = remaining[:-1]
                    else:
                        take = 3
                        if len(remaining) < 3: take = len(remaining)
                        arg_chunk = remaining[-take:]
                        remaining = remaining[:-take]
                    parts.insert(0, arg_chunk.hex().upper())
                if len(remaining) > 0:
                    prefix_hex = remaining.hex().upper()
                    prefix_chunks = [prefix_hex[i:i+6] for i in range(0, len(prefix_hex), 6)]
                    parts = prefix_chunks + parts
                return " ".join(parts)

            def flush_row(found_command_code=None):
                nonlocal current_row_bytes, current_row_tag
                if len(current_row_bytes) > 0 or current_row_tag:
                    txt = ""
                    cmd_meta = None
                    if len(current_row_bytes) > 0:
                        if found_command_code:
                            txt = format_command_line(current_row_bytes, found_command_code)
                            needed = self.command_arg_counts.get(found_command_code, 0)
                            args_fulfilled = 0
                            temp_rem = current_row_bytes[:- (len(found_command_code)//2)]
                            for _ in range(needed):
                                if len(temp_rem) == 0: break
                                lb = temp_rem[-1]
                                if 0x67 <= lb <= 0x6A:
                                    temp_rem = temp_rem[:-1]
                                    args_fulfilled += 1
                                elif len(temp_rem) >= 3:
                                    temp_rem = temp_rem[:-3]
                                    args_fulfilled += 1
                                else: break
                            cmd_meta = {'code': found_command_code, 'needed': needed, 'found': args_fulfilled}
                        else:
                            txt = format_raw_left_aligned(current_row_bytes)
                    
                    raw_rows.append({"c1": current_row_tag, "text": txt, "meta": cmd_meta, "arg1": "", "arg2": "", "arg3": ""})
                current_row_bytes = bytearray()
                current_row_tag = ""

            def get_args_split_index(byte_buffer, num_args_needed):
                if num_args_needed == 0: return len(byte_buffer) 
                current_idx = len(byte_buffer)
                for _ in range(num_args_needed):
                    if current_idx <= 0: return 0
                    val = byte_buffer[current_idx - 1]
                    if 0x67 <= val <= 0x6A: current_idx -= 1
                    else:
                        if current_idx < 3: return 0
                        current_idx -= 3
                return current_idx

            while cursor < length:
                abs_offset_in_code = chunk_start_rel_offset + cursor
                if abs_offset_in_code in jump_map:
                    flush_row()
                    current_row_tag = jump_map[abs_offset_in_code]

                match_found = False
                remaining_bytes = chunk[cursor:]
                remaining_hex = remaining_bytes.hex().lower()
                
                for code in self.hex_codes_for_parsing:
                    if remaining_hex.startswith(code):
                        match_len_bytes = len(code) // 2
                        cmd_bytes = remaining_bytes[:match_len_bytes]
                        args_needed = self.command_arg_counts.get(code, 0)
                        split_idx = get_args_split_index(current_row_bytes, args_needed)
                        
                        if split_idx > 0:
                            prefix_bytes = current_row_bytes[:split_idx]
                            current_row_bytes = current_row_bytes[split_idx:]
                            actual_args = current_row_bytes
                            current_row_bytes = prefix_bytes
                            flush_row() 
                            current_row_bytes = actual_args 
                        
                        current_row_bytes.extend(cmd_bytes)
                        cursor += match_len_bytes
                        flush_row(found_command_code=code)
                        match_found = True
                        break
                if match_found: continue
                current_row_bytes.append(chunk[cursor])
                cursor += 1
            
            flush_row()
            final_rows = self._post_process_merge_consumption(raw_rows)
            while len(final_rows) < NUM_ROWS:
                final_rows.append({"c1": "", "text": "", "arg1": "", "arg2": "", "arg3": ""})
            return final_rows[:NUM_ROWS]

    def _post_process_merge_consumption(self, raw_rows):
        if not raw_rows: return []
        processed_rows = []
        for r in raw_rows:
            is_consumer = False
            meta = r.get('meta')
            missing_count = 0
            if meta:
                code = meta['code'].upper()
                needed = meta['needed']
                found = meta['found']
                for prefix in self.consumption_rules:
                    if code.startswith(prefix):
                        if found < needed:
                            is_consumer = True
                            missing_count = needed - found
                        break
            
            if is_consumer:
                to_consume = []
                temp_idx = len(processed_rows) - 1
                while missing_count > 0 and temp_idx >= 0:
                    candidate = processed_rows[temp_idx]
                    if not candidate['c1'] and candidate['text'].strip():
                        to_consume.append(candidate)
                        missing_count -= 1
                        temp_idx -= 1
                    else: break
                
                if to_consume:
                    to_consume.reverse()
                    merged_text = ""
                    arg_slots = ["arg1", "arg2", "arg3"]
                    for i, victim in enumerate(to_consume):
                        merged_text = f"{merged_text}{victim['text']} "
                        victim_meta = victim.get('meta')
                        victim_code = victim_meta.get('code') if victim_meta else None
                        victim_desc = ""
                        if victim_code:
                             for k, v in self.command_map.items():
                                if k.replace(" ", "").lower() == victim_code.replace(" ", "").lower():
                                    victim_desc = v
                                    break
                        if i < 3: r[arg_slots[i]] = victim_desc
                    r['text'] = f"{merged_text}{r['text']}"
                    drop_count = len(to_consume)
                    processed_rows = processed_rows[:-drop_count]
            processed_rows.append(r)
        return processed_rows

    def print_data(self):
        self.save_current_field_data()
        if self.master_file_path and os.path.exists(self.master_file_path): filename = self.master_file_path
        else: filename = filedialog.askopenfilename(title="Select EBP File", filetypes=(("EBP Files", "*.ebp"), ("All Files", "*.*")))
        if not filename: return
        global k
        k = filename
        ebp_patcher.patch_ebp(k, n_clones=1, q_source_id=1)
        self.root.clipboard_clear()
        self.root.clipboard_append(k)
        self.root.update()
        try:
            file_size = os.path.getsize(filename)
            entry_val = file_size - 64
            jump_val = entry_val + 0x20
            code_start_val = 0
            with open(filename, "rb") as f:
                f.seek(0x70)
                data = f.read(4)
                if len(data) < 4: return 
                else:
                    val_at_70 = int.from_bytes(data, 'little')
                    code_start_val = val_at_70 + 0x40
            try:
                with open(filename, "r+b") as f:
                    f.seek(-20, 2) 
                    f.write(entry_val.to_bytes(4, 'little'))
                    f.write(jump_val.to_bytes(4, 'little'))
            except Exception as e:
                messagebox.showerror("File Error", f"Could not update file pointers:\n{e}")
                return 

            final_object = self._generate_byte_object(code_start_val, entry_val)
            if final_object:
                try:
                    with open(filename, "ab") as f: f.write(final_object)
                    messagebox.showinfo("Success", f"File Pointers updated and new Worker Object appended.")
                except Exception as e: messagebox.showerror("File Error", f"Could not append to file:\n{e}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to analyze EBP file:\n{e}")

    def _generate_byte_object(self, base_offset, custom_entry_ptr):
        def calculate_complex_pointer(relative_pos):
            pos_in_obj = relative_pos + 0x50
            step_2 = pos_in_obj + custom_entry_ptr
            step_3 = step_2 + 0x40
            final_val = step_3 - base_offset
            return final_val & 0xFFFFFFFF

        self.save_current_field_data()
        temp_store = self.data_store
        entry_final_values = [] 
        jump_final_values = {f"j{i:02X}": None for i in range(12)}
        all_code_bytes = bytearray()
        current_relative_ptr = 0

        for field in self.fields:
            val = calculate_complex_pointer(current_relative_ptr)
            entry_final_values.append(val)
            rows = temp_store[field]
            for row in rows:
                tag = row['c1']
                if tag in jump_final_values and jump_final_values[tag] is None:
                    val = calculate_complex_pointer(current_relative_ptr)
                    jump_final_values[tag] = val
                txt = row['text'].replace(" ", "").strip()
                if txt:
                    try:
                        b_data = bytes.fromhex(txt)
                        all_code_bytes.extend(b_data)
                        current_relative_ptr += len(b_data)
                    except ValueError: return None
        for k, v in jump_final_values.items():
            if v is None: jump_final_values[k] = 0 
        buffer = bytearray(b'\x3C' * OBJECT_TOTAL_SIZE)
        ENTRIES_START = 0
        JUMPS_START = 32
        CODE_START  = 80
        FOOTER_START = OBJECT_TOTAL_SIZE - 16
        for i, val in enumerate(entry_final_values):
            start_idx = ENTRIES_START + (i * 4)
            buffer[start_idx : start_idx+4] = struct.pack('<I', val)
        sorted_jumps = [jump_final_values[f"j{i:02X}"] for i in range(12)]
        for i, val in enumerate(sorted_jumps):
            start_idx = JUMPS_START + (i * 4)
            buffer[start_idx : start_idx+4] = struct.pack('<I', val)
        code_len = len(all_code_bytes)
        max_code_space = FOOTER_START - CODE_START 
        if code_len > max_code_space: return None
        buffer[CODE_START : CODE_START + code_len] = all_code_bytes
        init_ptr_bytes = buffer[0:4]
        buffer[FOOTER_START : FOOTER_START+4] = init_ptr_bytes
        rest_hex = "81 82 83 80 71 72 73 70 61 62 63 60"
        buffer[FOOTER_START+4 : FOOTER_START+16] = bytes.fromhex(rest_hex)
        return buffer

def create_dummy_csv():
    if not os.path.exists(CSV_FILENAME):
        try:
            with open(CSV_FILENAME, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows([["move", "Action: MOVE UNIT", "A0 01", "Move Normal"], ["hello", "sys: Greeting", "H1 00", "Greet"]])
        except: pass

if __name__ == "__main__":
    create_dummy_csv()
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except: pass
    app = DataEntryApp(root)
    root.mainloop()
