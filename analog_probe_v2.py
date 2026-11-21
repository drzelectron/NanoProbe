import csv
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import numpy as np
import serial
import serial.tools.list_ports
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

BAUD_RATE = 9600


class WaveformControllerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Arduino Nano Waveform Generator & Plotter")
        self.root.geometry("1120x820")

        self.ser = None
        self.is_running = False
        self.stop_event = threading.Event()
        self.data_lock = threading.Lock()

        self.cycle_array = np.array([], dtype=int)
        self.time_history = []
        self.control_history = []
        self.response_history = []

        self._build_ui()
        self._on_waveform_changed(None)
        self._on_mode_changed(None)
        self._on_duty_changed(self.duty_var.get())
        self._on_interval_changed(self.interval_var.get())

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        top_frame = ttk.LabelFrame(self.root, text="Waveform & Acquisition Settings", padding=10)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=8)

        # Row 0: USB Port & Waveform Type
        ttk.Label(top_frame, text="USB Port:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top_frame, textvariable=self.port_var, values=ports, width=16)
        selected_idx = 0
        for idx, p in enumerate(ports):
            desc = serial.tools.list_ports.comports()[idx].description.upper()
            if "USB" in p.upper() or "USB" in desc:
                selected_idx = idx
                break
        if ports:
            self.port_combo.current(selected_idx)
        self.port_combo.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Label(top_frame, text="Waveform:").grid(row=0, column=2, sticky=tk.W, padx=5, pady=5)
        self.wave_var = tk.StringVar(value="Sine")
        self.wave_combo = ttk.Combobox(
            top_frame,
            textvariable=self.wave_var,
            values=["Sine", "Rectangular", "Triangular", "Sawtooth"],
            state="readonly",
            width=16,
        )
        self.wave_combo.grid(row=0, column=3, sticky=tk.W, padx=5, pady=5)
        self.wave_combo.bind("<<ComboboxSelected>>", self._on_waveform_changed)

        # Row 1: Frequency (int) & Quantization (int, 10..1000)
        ttk.Label(top_frame, text="Frequency (Hz):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.freq_var = tk.StringVar(value="10")
        self.freq_entry = ttk.Entry(top_frame, textvariable=self.freq_var, width=18)
        self.freq_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Label(top_frame, text="Quantization (10-1000):").grid(row=1, column=2, sticky=tk.W, padx=5, pady=5)
        self.quant_var = tk.StringVar(value="100")
        self.quant_entry = ttk.Entry(top_frame, textvariable=self.quant_var, width=18)
        self.quant_entry.grid(row=1, column=3, sticky=tk.W, padx=5, pady=5)

        # Row 2: Rectangular On/Off Ratio Slider + % & Cycle Mode
        ttk.Label(top_frame, text="On/Off Ratio:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        duty_box = ttk.Frame(top_frame)
        duty_box.grid(row=2, column=1, sticky=tk.EW, padx=5, pady=5)

        self.duty_var = tk.DoubleVar(value=50.0)
        self.duty_slider = ttk.Scale(
            duty_box,
            from_=1.0,
            to=99.0,
            variable=self.duty_var,
            orient=tk.HORIZONTAL,
            command=self._on_duty_changed,
        )
        self.duty_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.duty_pct_label = ttk.Label(duty_box, text="50%", width=6)
        self.duty_pct_label.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(top_frame, text="Cycle Mode:").grid(row=2, column=2, sticky=tk.W, padx=5, pady=5)
        self.mode_var = tk.StringVar(value="Single Cycle")
        self.mode_combo = ttk.Combobox(
            top_frame,
            textvariable=self.mode_var,
            values=["Single Cycle", "Double Cycle", "Continuous"],
            state="readonly",
            width=16,
        )
        self.mode_combo.grid(row=2, column=3, sticky=tk.W, padx=5, pady=5)
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_changed)

        # Row 3: Plot Time Interval Slider (1 ms to 10 s for Continuous mode)
        ttk.Label(top_frame, text="Plot Interval (Continuous):").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        interval_box = ttk.Frame(top_frame)
        interval_box.grid(row=3, column=1, columnspan=2, sticky=tk.EW, padx=5, pady=5)

        self.interval_var = tk.DoubleVar(value=1.0)
        self.interval_slider = ttk.Scale(
            interval_box,
            from_=0.001,
            to=10.0,
            variable=self.interval_var,
            orient=tk.HORIZONTAL,
            command=self._on_interval_changed,
        )
        self.interval_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.interval_label = ttk.Label(interval_box, text="1.000 s", width=10)
        self.interval_label.pack(side=tk.LEFT, padx=(6, 0))


        # Action Buttons: Start / Stop & Save Data
        action_box = ttk.Frame(top_frame)
        action_box.grid(row=0, column=4, rowspan=4, padx=16, pady=5)

        self.start_btn = tk.Button(
            action_box,
            text="START",
            bg="#1e8e3e",
            fg="white",
            activebackground="#137333",
            activeforeground="white",
            font=("Arial", 11, "bold"),
            width=12,
            height=2,
            command=self._on_start_stop,
        )
        self.start_btn.pack(side=tk.TOP, pady=(0, 8))

        self.save_btn = tk.Button(
            action_box,
            text="Save data",
            bg="#1a73e8",
            fg="white",
            activebackground="#1557b0",
            activeforeground="white",
            font=("Arial", 10, "bold"),
            width=12,
            height=1,
            command=self._on_save_data,
        )
        self.save_btn.pack(side=tk.TOP)

        # Plot Area
        plot_frame = ttk.LabelFrame(self.root, text="Real-Time Waveform Plot", padding=8)
        plot_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.fig, self.ax = plt.subplots(figsize=(10, 4.5))
        self.ax.set_facecolor("#181818")
        self.ax.grid(True, color="#3a3a3a", linestyle="--", linewidth=0.6)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Amplitude (V)")

        self.line_control, = self.ax.plot([], [], color="green", linewidth=1.6, label="DAC Output")
        self.line_response, = self.ax.plot([], [], color="yellow", linewidth=1.6, label="Device Response")
        self.ax.legend(loc="upper right")

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    def _on_waveform_changed(self, _event):
        if self.wave_var.get() == "Rectangular":
            self.duty_slider.state(["!disabled"])
        else:
            self.duty_slider.state(["disabled"])

    def _on_mode_changed(self, _event):
        if self.mode_var.get() == "Continuous":
            self.interval_slider.state(["!disabled"])
        else:
            self.interval_slider.state(["disabled"])

    def _on_duty_changed(self, val):
        pct = int(round(float(val)))
        self.duty_pct_label.config(text=f"{pct}%")

    def _on_interval_changed(self, val):
        secs = float(val)
        if secs < 1.0:
            self.interval_label.config(text=f"{secs * 1000:.0f} ms")
        else:
            self.interval_label.config(text=f"{secs:.3f} s")

    def _refresh_save_button_state(self):
        with self.data_lock:
            has_data = len(self.time_history) > 0
        if not self.is_running and has_data:
            self.save_btn.config(state=tk.NORMAL)
        else:
            self.save_btn.config(state=tk.DISABLED)

    def _validate_inputs(self):
        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror("Invalid Port", "Please select a USB port.")
            return None

        try:
            freq = int(self.freq_var.get().strip())
            if freq <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Frequency", "Frequency must be a positive integer.")
            return None

        try:
            quant = int(self.quant_var.get().strip())
            if not (10 <= quant <= 1000):
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Quantization", "Quantization must be an integer between 10 and 1000.")
            return None

        duty_pct = int(round(float(self.duty_var.get())))
        return port, freq, quant, duty_pct

    def _generate_one_cycle(self, wave_type, quant, duty_pct):
        phase = np.linspace(0.0, 1.0, quant, endpoint=False)

        if wave_type == "Sine":
            norm = 0.5 * (1.0 + np.sin(2.0 * np.pi * phase))
        elif wave_type == "Rectangular":
            norm = np.where(phase < (duty_pct / 100.0), 1.0, 0.0)
        elif wave_type == "Triangular":
            norm = np.where(phase < 0.5, 2.0 * phase, 2.0 * (1.0 - phase))
        elif wave_type == "Sawtooth":
            norm = phase
        else:
            norm = 0.5 * (1.0 + np.sin(2.0 * np.pi * phase))

        # 5-bit output range (0..31) scaled cleanly to 0..255
        levels = np.round(norm * 31.0).astype(int)
        return np.round((levels / 31.0) * 255.0).astype(int)

    def _on_start_stop(self):
        if self.is_running:
            self.stop_event.set()
            return

        validated = self._validate_inputs()
        if validated is None:
            return

        port, freq, quant, duty_pct = validated
        wave_type = self.wave_var.get()
        mode = self.mode_var.get()

        try:
            self.ser = serial.Serial(
                port=port,
                baudrate=BAUD_RATE,
                timeout=2.0,
                dsrdtr=False,
                rtscts=False,
            )
            self.ser.dtr = False
            self.ser.rts = False
            time.sleep(2.0)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception as exc:
            messagebox.showerror("Serial Connection Error", str(exc))
            return

        self.cycle_array = self._generate_one_cycle(wave_type, quant, duty_pct)

        with self.data_lock:
            self.time_history.clear()
            self.control_history.clear()
            self.response_history.clear()

        self.is_running = True
        self.stop_event.clear()
        self.start_btn.config(text="STOP", bg="#c5221f", activebackground="#a50e0e")
        self._set_controls_enabled(False)

        threading.Thread(
            target=self._run_acquisition,
            args=(freq, mode),
            daemon=True,
        ).start()
        self._schedule_plot_refresh()

    def _set_controls_enabled(self, enabled):
        state = "!disabled" if enabled else "disabled"
        self.port_combo.state([state])
        self.wave_combo.state([state])
        self.freq_entry.state([state])
        self.quant_entry.state([state])
        self.mode_combo.state([state])

        if enabled:
            self._on_waveform_changed(None)
            self._on_mode_changed(None)
        else:
            self.duty_slider.state(["disabled"])
            self.interval_slider.state(["disabled"])

    def _run_acquisition(self, freq, mode):
        quant = len(self.cycle_array)
        sample_period = 1.0 / (freq * quant)

        if mode == "Single Cycle":
            total_cycles = 1
        elif mode == "Double Cycle":
            total_cycles = 2
        else:
            total_cycles = None

        t0 = time.perf_counter()
        cycle_idx = 0

        try:
            while not self.stop_event.is_set():
                if total_cycles is not None and cycle_idx >= total_cycles:
                    break

                for sample in self.cycle_array:
                    if self.stop_event.is_set():
                        break

                    step_start = time.perf_counter()
                    self.ser.write(f"{int(sample)}\n".encode("ascii"))
                    self.ser.flush()

                    line = self.ser.readline()
                    if not line:
                        continue

                    parts = line.decode("ascii", errors="ignore").strip().split(",")
                    if len(parts) == 2:
                        ctrl_val = float(parts[0])*5/1024
                        resp_val = float(parts[1])*5/1024
                        elapsed = time.perf_counter() - t0

                        with self.data_lock:
                            self.time_history.append(elapsed)
                            self.control_history.append(ctrl_val)
                            self.response_history.append(resp_val)

                    remaining = sample_period - (time.perf_counter() - step_start)
                    if remaining > 0:
                        time.sleep(remaining)

                cycle_idx += 1
        except Exception:
            pass
        finally:
            self.root.after(0, self._finish_run)

    def _finish_run(self):
        self._update_plot()
        if self.ser is not None:
            try:
                if self.ser.is_open:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None

        self.is_running = False
        self.start_btn.config(text="START", bg="#1e8e3e", activebackground="#137333")
        self._set_controls_enabled(True)
        self._refresh_save_button_state()

    def _schedule_plot_refresh(self):
        self._update_plot()
        if self.is_running:
            self.root.after(30, self._schedule_plot_refresh)

    def _update_plot(self):
        with self.data_lock:
            if not self.time_history:
                return
            t = np.asarray(self.time_history, dtype=float)
            ctrl = np.asarray(self.control_history, dtype=float)
            resp = np.asarray(self.response_history, dtype=float)

        if self.mode_var.get() == "Continuous":
            n_sec = max(0.001, float(self.interval_var.get()))
            t_max = t[-1]
            t_min = max(0.0, t_max - n_sec)
            mask = t >= t_min
            t_plot = t[mask]
            ctrl_plot = ctrl[mask]
            resp_plot = resp[mask]
            x_left = t_max - n_sec if t_max > n_sec else 0.0
            x_right = max(n_sec, t_max)
        else:
            t_plot = t
            ctrl_plot = ctrl
            resp_plot = resp
            x_left = float(t[0])
            x_right = float(t[-1]) if len(t) > 1 else x_left + 0.01

        self.line_control.set_data(t_plot, ctrl_plot)
        self.line_response.set_data(t_plot, resp_plot)

        if x_right > x_left:
            self.ax.set_xlim(x_left, x_right)

        combined = np.concatenate([ctrl_plot, resp_plot])
        if combined.size > 0:
            y_min = float(np.min(combined))
            y_max = float(np.max(combined))
            if y_min == y_max:
                y_min -= 1.0
                y_max += 1.0
            pad = 0.05 * (y_max - y_min)
            self.ax.set_ylim(y_min - pad, y_max + pad)

        self.canvas.draw_idle()

    def _on_save_data(self):
        with self.data_lock:
            has_data = len(self.time_history) > 0
            t_copy = list(self.time_history)
            ctrl_copy = list(self.control_history)
            resp_copy = list(self.response_history)

        if self.is_running or not has_data:
            messagebox.showwarning("Nothing to Save", "Run a measurement first before saving data.")
            return

        choice_win = tk.Toplevel(self.root)
        choice_win.title("Save Data")
        choice_win.geometry("400x130")
        choice_win.resizable(False, False)
        choice_win.transient(self.root)
        choice_win.grab_set()

        ttk.Label(choice_win, text="Select export format:", font=("Arial", 10, "bold")).pack(pady=(16, 12))

        btn_row = ttk.Frame(choice_win)
        btn_row.pack(pady=4)

        def save_excel():
            choice_win.destroy()
            if not OPENPYXL_AVAILABLE:
                messagebox.showerror("Missing Dependency", "Please install 'openpyxl' to save Excel (.xlsx) files.")
                return

            file_path = filedialog.asksaveasfilename(
                parent=self.root,
                title="Save Data as Excel",
                defaultextension=".xlsx",
                filetypes=[("Excel workbook", "*.xlsx"), ("All files", "*.*")],
            )
            if not file_path:
                return
            try:
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Waveform Data"
                ws.append(["time (s)", "control (V)", "response (V)"])
                for t_val, c_val, r_val in zip(t_copy, ctrl_copy, resp_copy):
                    ws.append([round(float(t_val), 6), float(c_val), float(r_val)])
                wb.save(file_path)
                #messagebox.showinfo("Saved", f"Excel data saved to:\n{file_path}")
            except Exception as exc:
                messagebox.showerror("Save Error", str(exc))

        def save_csv():
            choice_win.destroy()
            file_path = filedialog.asksaveasfilename(
                parent=self.root,
                title="Save Data as CSV",
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            )
            if not file_path:
                return
            try:
                with open(file_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["time (s)", "control (V)", "response (V)"])
                    for t_val, c_val, r_val in zip(t_copy, ctrl_copy, resp_copy):
                        writer.writerow([str(f"{t_val:.6f}"), str(c_val), str(r_val)])
                #messagebox.showinfo("Saved", f"CSV data saved to:\n{file_path}")
            except Exception as exc:
                messagebox.showerror("Save Error", str(exc))

        def save_picture():
            choice_win.destroy()
            file_path = filedialog.asksaveasfilename(
                parent=self.root,
                title="Save Plot Picture",
                defaultextension=".png",
                filetypes=[
                    ("PNG image", "*.png"),
                    ("JPEG image", "*.jpg"),
                    ("SVG image", "*.svg"),
                    ("All files", "*.*"),
                ],
            )
            if not file_path:
                return
            try:
                self._update_plot()
                self.canvas.draw()
                self.fig.savefig(file_path, dpi=200, bbox_inches="tight")
                #messagebox.showinfo("Saved", f"Plot picture saved to:\n{file_path}")
            except Exception as exc:
                messagebox.showerror("Save Error", str(exc))

        ttk.Button(btn_row, text="Save as CSV", width=14, command=save_csv).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_row, text="Save as XLS", width=14, command=save_excel).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_row, text="Save as Picture", width=14, command=save_picture).pack(side=tk.LEFT, padx=8)

    def _on_close(self):
        self.stop_event.set()
        if self.ser is not None:
            try:
                if self.ser.is_open:
                    self.ser.close()
            except Exception:
                pass
        try:
            plt.close(self.fig)
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = WaveformControllerGUI(root)
    root.mainloop()