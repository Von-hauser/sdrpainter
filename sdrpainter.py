
# linear FM chirp painter HR Approved 2025-11-1
# bladeRF or hackrf 
# grab a pic converts it then Creates a bin file and plays it.

import os, time, threading, subprocess, shutil, queue, multiprocessing as mp
import numpy as np
from PIL import Image, ImageOps, ImageDraw, ImageFont
import tkinter as tk
from tkinter import filedialog, messagebox, END, NORMAL, DISABLED

# ---------- Defaults ----------
DEFAULT_TEXT = "HELLO"
DEFAULT_FREQ_MHZ = 435.0
DEFAULT_SR_MHZ   = 2.0          # Works for both radios (HackRF >= 2 Msps)
DEFAULT_SPEED    = 30.0         # rows/s
DEFAULT_BW_KHZ   = 100.0
DEFAULT_GAIN_DB  = 30           # bladeRF: overall; HackRF: VGA (0..47)
DEFAULT_W, DEFAULT_H = 1024, 512
DEFAULT_USB_MODE = True

# ---------- Dark theme ----------
CLR_BG    = "#0f1115"
CLR_PANEL = "#141821"
CLR_TEXT  = "#e6e6e6"
CLR_MUTED = "#a6a6a6"
CLR_BTN   = "#1f2430"
CLR_BTN_H = "#2a3142"
CLR_EDIT  = "#1a1f2b"
CLR_EDIT_TXT = "#ffffff"
CLR_ACCENT= "#2ea043"

FONT_CANDIDATES = [
    "DejaVuSansMono-Bold.ttf", "Consolas.ttf", "Courier New.ttf",
    r"C:\Windows\Fonts\consolab.ttf", r"C:\Windows\Fonts\consola.ttf",
]

# ---------- bladeRF-cli discovery ----------
def find_bladerf_cli():
    for p in [r"C:\bladeRF\bladeRF-cli.exe",
              r"C:\Program Files\Nuand\bladeRF\bladeRF-cli.exe",
              r"C:\Program Files (x86)\Nuand\bladeRF\bladeRF-cli.exe"]:
        if os.path.isfile(p): return p
    for name in ("bladeRF-cli.exe","bladerf-cli.exe","bladeRF-cli","bladerf-cli"):
        p = shutil.which(name)
        if p: return p
    return None

# ---------- hackrf_transfer discovery ----------
def find_hackrf_transfer():
    for p in [r"C:\Program Files\HackRF\hackrf_transfer.exe",
              r"C:\Program Files (x86)\HackRF\hackrf_transfer.exe",
              r"C:\hackrf\hackrf_transfer.exe"]:
        if os.path.isfile(p): return p
    p = shutil.which("hackrf_transfer.exe") or shutil.which("hackrf_transfer")
    return p

# ---------- bladeRF interactive wrapper ----------
class BladeRFProc:
    def __init__(self, cli_path, log_cb):
        self.cli_path = cli_path
        self.log = log_cb
        self.proc = None
        self.q = queue.Queue()

    def start(self):
        path = self.cli_path or find_bladerf_cli()
        if not path or not os.path.isfile(path):
            self.log("ERROR: bladeRF-cli not found (C:\\bladeRF, Program Files, or PATH)."); return False
        flags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags = subprocess.CREATE_NO_WINDOW
        try:
            self.proc = subprocess.Popen(
                [path, "-i"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, bufsize=1, creationflags=flags
            )
        except Exception as e:
            self.log(f"ERROR launching bladeRF-cli: {e}"); return False
        threading.Thread(target=self._reader, daemon=True).start()
        return True

    def _reader(self):
        try:
            for line in self.proc.stdout:
                self.q.put(line.rstrip())
        except Exception:
            pass

    def drain(self):
        try:
            while True: self.log(self.q.get_nowait())
        except queue.Empty:
            pass

    def send(self, cmd, delay=0.02):
        if not self.proc or not self.proc.stdin: return
        self.proc.stdin.write(cmd.strip()+"\n"); self.proc.stdin.flush()
        if delay>0: time.sleep(delay)

    def stop(self):
        try: self.send("tx stop", 0.02)
        except: pass
        try:
            if self.proc and self.proc.stdin:
                self.proc.stdin.write("quit\n"); self.proc.stdin.flush()
        except: pass
        try:
            if self.proc: self.proc.wait(timeout=1.0)
        except Exception:
            pass

# ---------- HackRF one-shot runner ----------
class HackRFProc:
    """
    Thin wrapper around hackrf_transfer for TX from file.
    """
    def __init__(self, exe_path, log_cb):
        self.exe_path = exe_path
        self.log = log_cb
        self.proc = None
        self._reader_thread = None

    def start_tx(self, filepath, freq_hz, samp_rate_hz, bb_bw_hz, tx_gain_db, repeat=False, bias_on=False):
        path = self.exe_path or find_hackrf_transfer()
        if not path or not os.path.isfile(path):
            self.log("ERROR: hackrf_transfer not found (Program Files, C:\\hackrf, or PATH)."); return False

        # Clamp gain to HackRF's VGA 0..47 dB
        tx_gain_db = int(max(0, min(47, int(tx_gain_db))))

        cmd = [
            path,
            "-t", filepath,
            "-f", str(int(freq_hz)),
            "-s", str(int(samp_rate_hz)),
            "-x", str(tx_gain_db),
            "-b", str(int(bb_bw_hz))
        ]
        if repeat:
            cmd.append("-R")  # repeat indefinitely
        if bias_on:
            cmd.extend(["-a", "1"])  # antenna power ON

        flags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags = subprocess.CREATE_NO_WINDOW

        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, bufsize=1, creationflags=flags
            )
        except Exception as e:
            self.log(f"ERROR launching hackrf_transfer: {e}"); return False

        self._reader_thread = threading.Thread(target=self._reader, daemon=True)
        self._reader_thread.start()
        self.log("HackRF TX started.")
        return True

    def _reader(self):
        try:
            for line in self.proc.stdout:
                self.log(line.rstrip())
        except Exception:
            pass
        finally:
            self.log("HackRF process ended.")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            except Exception:
                pass
        self.proc = None

# ---- HackRF baseband filter quantizer ----
def hackrf_quantize_bb_bw(fs_hz: int, req_bw_hz: int) -> int:
    """
    Snap requested BW to HackRF's allowed baseband filters.
    Enforces minimum 1.75 MHz and caps by sample rate and ~device max (20 MHz typical).
    """
    allowed = [
        1_750_000, 2_500_000, 3_500_000, 5_000_000, 5_500_000, 6_000_000,
        7_000_000, 8_000_000, 9_000_000, 10_000_000, 12_000_000, 14_000_000,
        15_000_000, 20_000_000
    ]
    cap = max(1_750_000, min(int(fs_hz), 20_000_000))
    candidates = [v for v in allowed if v <= cap]
    if not candidates:
        return 1_750_000
    target = max(1_750_000, int(req_bw_hz))
    for v in candidates:
        if v >= target:
            return v
    return candidates[-1]

# ---------- Auto-scaled text rendering ----------
def _load_font(px):
    px = max(8, int(px))
    for f in FONT_CANDIDATES:
        try: return ImageFont.truetype(f, size=px)
        except Exception: pass
    return ImageFont.load_default()

def render_text_bitmap(text, w, h, pad=6):
    test = Image.new("L", (w, h), 0); d = ImageDraw.Draw(test)
    fs = int(h*2); font = _load_font(fs)
    bbox = d.textbbox((0,0), text, font=font); tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    while (tw+2*pad > w or th+2*pad > h) and fs > 8:
        fs = max(8, int(fs*0.9)); font = _load_font(fs)
        bbox = d.textbbox((0,0), text, font=font); tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    img = Image.new("L", (w, h), 0); d = ImageDraw.Draw(img)
    x = (w - tw)//2 - bbox[0]; y = (h - th)//2 - bbox[1]
    d.text((x, y), text, fill=255, font=font)
    return img

# ---------- IQ builders ----------
def _row_worker(args):
    idx, row, x_dst, ejphi = args
    amp = np.interp(x_dst, np.arange(row.size, dtype=np.float32), row.astype(np.float32))
    return idx, (amp * ejphi).astype(np.complex64)

def build_iq_mp(gray_img, fs_hz, bw_hz, rows_per_s, usb=True, fmin_hz=0.0):
    if gray_img.mode != "L": gray_img = gray_img.convert("L")
    data = np.asarray(gray_img, dtype=np.float32) / 255.0
    H, W = data.shape
    row_t = 1.0 / max(1e-6, rows_per_s)
    Ns = int(round(fs_hz * row_t)); Ns = max(16, Ns)
    t = np.linspace(0.0, row_t, Ns, endpoint=False, dtype=np.float32)

    if usb:
        f0 = float(fmin_hz); k = float(bw_hz) / row_t
        phi = 2.0*np.pi*(f0*t + 0.5*k*t*t)
    else:
        f0 = -bw_hz/2.0; k = float(bw_hz) / row_t
        phi = 2.0*np.pi*(f0*t + 0.5*k*t*t)

    ejphi = np.exp(1j*phi).astype(np.complex64)
    x_dst = np.linspace(0, W-1, Ns, dtype=np.float32)
    tasks = [(r, data[r,:], x_dst, ejphi) for r in range(H)]
    with mp.Pool(max(1, mp.cpu_count()-1)) as pool:
        parts = pool.map(_row_worker, tasks)
    parts.sort(key=lambda x: x[0])
    iq = np.concatenate([p[1] for p in parts])

    # DC block + normalize
    iq -= np.mean(iq)
    peak = float(np.max(np.abs(iq)) + 1e-9)
    iq = (iq / peak * 0.95).astype(np.complex64)
    return iq, H / float(rows_per_s)

def save_sc16q11(path, iq):
    i = np.clip(np.real(iq)*2047, -2048, 2047).astype(np.int16)
    q = np.clip(np.imag(iq)*2047, -2048, 2047).astype(np.int16)
    inter = np.empty(i.size*2, dtype=np.int16)
    inter[0::2], inter[1::2] = i, q
    with open(path, "wb") as f: inter.tofile(f)

def save_sc8(path, iq):
    # HackRF expects signed 8-bit interleaved I/Q
    i = np.clip(np.real(iq)*127, -128, 127).astype(np.int8)
    q = np.clip(np.imag(iq)*127, -128, 127).astype(np.int8)
    inter = np.empty(i.size*2, dtype=np.int8)
    inter[0::2], inter[1::2] = i, q
    with open(path, "wb") as f: inter.tofile(f)

# ---------- GUI ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Spectrum Painter — bladeRF / HackRF — USB / Invert / Auto-scale / Dark")
        self.configure(bg=CLR_BG)
        self.geometry("1040x800")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Backends
        self.cli = BladeRFProc(find_bladerf_cli(), self._log)
        self.cli.start()
        self.hackrf = HackRFProc(find_hackrf_transfer(), self._log)
        self.after(150, self._poll_cli)

        self.image_path = None
        self.output_bin_sc16 = os.path.abspath("paint.bin")
        self.output_bin_sc8  = os.path.abspath("paint_sc8.bin")

        # Vars
        self.mode     = tk.StringVar(value="text")
        self.text_in  = tk.StringVar(value=DEFAULT_TEXT)
        self.freq_mhz = tk.StringVar(value=str(DEFAULT_FREQ_MHZ))
        self.sr_mhz   = tk.StringVar(value=str(DEFAULT_SR_MHZ))
        self.bw_khz   = tk.StringVar(value=str(DEFAULT_BW_KHZ))
        self.gain_db  = tk.StringVar(value=str(DEFAULT_GAIN_DB))
        self.speed_rps= tk.StringVar(value=str(DEFAULT_SPEED))
        self.r_w      = tk.StringVar(value=str(DEFAULT_W))
        self.r_h      = tk.StringVar(value=str(DEFAULT_H))
        self.repeat   = tk.BooleanVar(value=False)
        self.usb_mode = tk.BooleanVar(value=DEFAULT_USB_MODE)
        self.usb_fmin_khz = tk.StringVar(value="0")
        self.invert   = tk.BooleanVar(value=False)
        self.use_hackrf = tk.BooleanVar(value=False)  # backend selector

        # Bias-T controls
        self.bias_hackrf = tk.BooleanVar(value=False)
        self.bias_bladerf_rx = tk.BooleanVar(value=False)
        self.bias_bladerf_tx = tk.BooleanVar(value=False)

        self._build_ui()

    # ---- UI helpers ----
    def _panel(self, parent):
        return tk.Frame(parent, bg=CLR_PANEL, bd=1, highlightthickness=1, highlightbackground="#222833")
    def _label(self, parent, txt):
        return tk.Label(parent, text=txt, bg=CLR_PANEL, fg=CLR_MUTED)
    def _entry(self, parent, var, w=10):
        return tk.Entry(parent, textvariable=var, width=w, bg=CLR_EDIT, fg=CLR_EDIT_TXT,
                        insertbackground=CLR_EDIT_TXT, relief="flat")
    def _button(self, parent, txt, cmd, accent=False):
        c = CLR_ACCENT if accent else CLR_BTN; fg = "#ffffff" if accent else CLR_TEXT
        return tk.Button(parent, text=txt, command=cmd, bg=c, fg=fg,
                         activebackground=CLR_BTN_H, activeforeground=fg, relief="flat", padx=10, pady=4)
    def _check(self, parent, txt, var):
        return tk.Checkbutton(parent, text=txt, variable=var, bg=CLR_PANEL, fg=CLR_TEXT,
                              activebackground=CLR_PANEL, activeforeground=CLR_TEXT,
                              selectcolor=CLR_BG, relief="flat")

    # ---- Layout ----
    def _build_ui(self):
        bar = self._panel(self); bar.pack(fill="x", padx=10, pady=(10,6))
        tk.Label(bar, text="Mode:", bg=CLR_PANEL, fg=CLR_TEXT).pack(side="left", padx=8, pady=8)
        for val in ("image","text"):
            tk.Radiobutton(bar, text=val.capitalize(), variable=self.mode, value=val,
                           bg=CLR_PANEL, fg=CLR_TEXT, activebackground=CLR_PANEL,
                           selectcolor=CLR_BG, command=self._toggle_mode).pack(side="left", padx=6)
        self._check(bar, "Invert colors", self.invert).pack(side="left", padx=16)
        self._check(bar, "Use HackRF (instead of bladeRF)", self.use_hackrf).pack(side="right", padx=10)

        self.img_row = self._panel(self)
        tk.Label(self.img_row, text="Image:", bg=CLR_PANEL, fg=CLR_MUTED).pack(side="left", padx=8, pady=8)
        self.img_label = tk.Label(self.img_row, text="(none)", bg=CLR_PANEL, fg=CLR_MUTED)
        self.img_label.pack(side="left", padx=6)
        self._button(self.img_row, "Open…", self.pick_image).pack(side="left", padx=6)

        self.txt_row = self._panel(self)
        tk.Label(self.txt_row, text="Text:", bg=CLR_PANEL, fg=CLR_MUTED).pack(side="left", padx=8, pady=8)
        tk.Entry(self.txt_row, textvariable=self.text_in, width=28,
                 bg=CLR_EDIT, fg=CLR_EDIT_TXT, insertbackground=CLR_EDIT_TXT,
                 relief="flat").pack(side="left", padx=6)
        self.txt_row.pack(fill="x", padx=10, pady=6)

        g1 = self._panel(self); g1.pack(fill="x", padx=10, pady=6)
        for lbl, var in [("Freq (MHz)", self.freq_mhz),
                         ("BW (kHz)", self.bw_khz),
                         ("Power (dB)", self.gain_db),
                         ("Sample-rate (MHz)", self.sr_mhz)]:
            cell = tk.Frame(g1, bg=CLR_PANEL); cell.pack(side="left", padx=10, pady=8)
            self._label(cell, lbl).pack(anchor="w")
            self._entry(cell, var, 10).pack()

        g2 = self._panel(self); g2.pack(fill="x", padx=10, pady=6)
        for lbl, var in [("Speed (rows/s)", self.speed_rps),
                         ("Raster W", self.r_w),
                         ("Raster H", self.r_h)]:
            cell = tk.Frame(g2, bg=CLR_PANEL); cell.pack(side="left", padx=10, pady=8)
            self._label(cell, lbl).pack(anchor="w")
            self._entry(cell, var, 10).pack()

        g3 = self._panel(self); g3.pack(fill="x", padx=10, pady=6)
        self._check(g3, "USB (single-sideband)", self.usb_mode).pack(side="left", padx=10, pady=10)
        cell_usb = tk.Frame(g3, bg=CLR_PANEL); cell_usb.pack(side="left", padx=10, pady=8)
        self._label(cell_usb, "USB fmin (kHz)").pack(anchor="w")
        self._entry(cell_usb, self.usb_fmin_khz, 10).pack()
        self._check(g3, "Repeat (loop)", self.repeat).pack(side="left", padx=20)

        # Bias-T group
        bias = self._panel(self); bias.pack(fill="x", padx=10, pady=6)
        tk.Label(bias, text="Bias-T:", bg=CLR_PANEL, fg=CLR_TEXT).pack(side="left", padx=8, pady=8)
        self._check(bias, "HackRF antenna power", self.bias_hackrf).pack(side="left", padx=10)
        self._check(bias, "bladeRF RX bias-tee", self.bias_bladerf_rx).pack(side="left", padx=10)
        self._check(bias, "bladeRF TX bias-tee", self.bias_bladerf_tx).pack(side="left", padx=10)

        ctl = self._panel(self); ctl.pack(fill="x", padx=10, pady=6)
        self._button(ctl, "Play", self.play, accent=True).pack(side="left", padx=8, pady=8)
        self._button(ctl, "Stop", self.stop).pack(side="left", padx=8, pady=8)

        lf = self._panel(self); lf.pack(fill="both", expand=True, padx=10, pady=(6,10))
        self.log = tk.Text(lf, height=16, bg=CLR_EDIT, fg=CLR_TEXT,
                           insertbackground=CLR_TEXT, relief="flat", wrap="word")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)
        self.log.config(state=DISABLED)

    def _toggle_mode(self):
        if self.mode.get() == "image":
            self.txt_row.forget(); self.img_row.pack(fill="x", padx=10, pady=6)
        else:
            self.img_row.forget(); self.txt_row.pack(fill="x", padx=10, pady=6)

    # ---- Actions ----
    def pick_image(self):
        p = filedialog.askopenfilename(title="Select image",
                                       filetypes=[("Images","*.png;*.jpg;*.jpeg;*.bmp")])
        if not p: return
        self.image_path = p
        self.img_label.config(text=os.path.basename(p))
        self._log(f"Image loaded: {p}")

    def _poll_cli(self):
        # Drain bladeRF interactive logs; HackRF logs stream directly in its own thread
        self.cli.drain()
        self.after(150, self._poll_cli)

    def _log(self, msg):
        self.log.config(state=NORMAL); self.log.insert(END, msg.rstrip()+"\n")
        self.log.see(END); self.log.config(state=DISABLED)

    def play(self): threading.Thread(target=self._worker, daemon=True).start()

    def stop(self):
        if self.use_hackrf.get():
            self.hackrf.stop()
            self._log("HackRF TX stopped.")
        else:
            self.cli.send("tx stop", 0.02)
            self._log("bladeRF TX stopped.")

    def on_close(self):
        try:
            self.hackrf.stop()
        except: pass
        try:
            self.cli.stop()
        except: pass
        self.destroy()

    # ---- TX worker ----
    def _worker(self):
        try:
            fc   = int(float(self.freq_mhz.get()) * 1e6)
            fs   = int(float(self.sr_mhz.get())   * 1e6)
            bw   = int(float(self.bw_khz.get())   * 1e3)
            g    = int(float(self.gain_db.get()))
            sp   = float(self.speed_rps.get())
            W    = int(self.r_w.get()); H = int(self.r_h.get())
            usb  = bool(self.usb_mode.get())
            fmin = float(self.usb_fmin_khz.get()) * 1e3
        except Exception as e:
            self._log(f"Bad parameter: {e}"); return

        # Nyquist safety for painter synthesis
        if bw > int(0.9 * fs):
            bw = int(0.9 * fs); self._log(f"Note: BW clamped to {bw/1e3:.1f} kHz for Nyquist.")

        # Build raster
        if self.mode.get() == "image":
            if not self.image_path:
                messagebox.showerror("Error", "Select an image first."); return
            img = Image.open(self.image_path).convert("L").resize((W, H), Image.LANCZOS)
        else:
            txt = self.text_in.get().strip() or DEFAULT_TEXT
            img = render_text_bitmap(txt, W, H)

        if self.invert.get():  # invert colors (not orientation)
            img = ImageOps.invert(img)

        img = ImageOps.flip(img)  # top row first in time

        self._log("Generating IQ (multiprocessing)…")
        iq, dur = build_iq_mp(img, fs, bw, sp, usb=usb, fmin_hz=fmin if usb else 0.0)

        if self.use_hackrf.get():
            # HackRF path: write sc8, launch hackrf_transfer with quantized BB filter
            out8 = self.output_bin_sc8
            try:
                save_sc8(out8, iq)
            except Exception as e:
                self._log(f"ERROR writing BIN (sc8): {e}"); return
            self._log(f"Wrote {out8}  (≈{dur:.2f} s)")

            bb_bw = hackrf_quantize_bb_bw(fs, bw)
            self._log(f"HackRF BB filter set to {bb_bw/1e6:.2f} MHz (requested {bw/1e3:.1f} kHz)")

            started = self.hackrf.start_tx(
                filepath=out8,
                freq_hz=fc,
                samp_rate_hz=fs,
                bb_bw_hz=bb_bw,
                tx_gain_db=g,
                repeat=self.repeat.get(),
                bias_on=self.bias_hackrf.get()
            )
            if not started:
                self._log("Failed to start HackRF TX.")
                return

            if not self.repeat.get():
                # Wait for the process to end (file streamed once)
                while self.hackrf.proc and self.hackrf.proc.poll() is None:
                    time.sleep(0.1)
                self._log("TX complete (file finished).")

        else:
            # bladeRF path: write sc16q11 and drive CLI session
            out = self.output_bin_sc16
            try:
                save_sc16q11(out, iq)
            except Exception as e:
                self._log(f"ERROR writing BIN (sc16q11): {e}"); return
            self._log(f"Wrote {out}  (≈{dur:.2f} s)")

            # Bias-T controls for bladeRF (errors will log if unsupported)
            if self.bias_bladerf_rx.get():
                self.cli.send("set biastee rx on", 0.02)
            else:
                self.cli.send("set biastee rx off", 0.02)
            if self.bias_bladerf_tx.get():
                self.cli.send("set biastee tx on", 0.02)
            else:
                self.cli.send("set biastee tx off", 0.02)

            cmds = [
                f"set samplerate tx {fs}",
                f"set frequency tx {fc}",
                f"set bandwidth tx {bw}",
                f"set gain tx {g}",
                f"tx config file=\"{out}\" format=bin repeat={'0' if self.repeat.get() else '1'}",
                "tx start"
            ]
            for c in cmds: self.cli.send(c, 0.02)
            self._log("TX started.")

            if not self.repeat.get():
                self.cli.send("tx wait", 0.05)
                self.cli.send("tx stop", 0.02)
                self._log("TX complete (file finished).")

# ---------- Main ----------
if __name__ == "__main__":
    mp.freeze_support()
    app = App()
    app.mainloop()
