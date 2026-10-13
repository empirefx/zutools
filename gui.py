"""Tkinter front-end for the zutools extractor.

Pick the Zu client folder -> it lists the `.zu` packs it found -> choose an
output folder -> extract all of them, or only the ones you select. Packs are
extracted straight into the chosen output folder (paths merged across packs).
Optionally decode the extracted `.ZU1` tables and `WORLDS/*.DAT` files
afterwards (each independently, both on by default); decoded output is written
next to its sources inside the DATA / WORLDS folders.

Usage:
    python gui.py
    python gui.py --selftest
"""
import os
import re
import sys
import threading
import traceback
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import zurez
import zudata
import zuworld


def _natural_key(path):
    """Sort key so zu_pack2 comes before zu_pack10."""
    name = os.path.basename(path).lower()
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def find_packs(folder):
    """Return .zu archive paths directly inside `folder`, in natural order."""
    if not folder or not os.path.isdir(folder):
        return []
    out = [os.path.join(folder, f) for f in os.listdir(folder)
           if f.lower().endswith(".zu") and os.path.isfile(os.path.join(folder, f))]
    return sorted(out, key=_natural_key)


def find_special_dirs(root):
    """Walk `root` for DATA dirs (with .ZU1) and WORLDS dirs (with .DAT)."""
    data_dirs, world_dirs = [], []
    for cur, _dirs, files in os.walk(root):
        base = os.path.basename(cur).upper()
        if base == "DATA" and any(f.upper().endswith(".ZU1") for f in files):
            data_dirs.append(cur)
        if base == "WORLDS" and any(f.upper().endswith(".DAT") for f in files):
            world_dirs.append(cur)
    return data_dirs, world_dirs


def _humansize(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.packs = []
        root.title("Zu client extractor")
        root.minsize(720, 520)

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Zu client folder:").grid(row=0, column=0, sticky="w")
        self.client_var = tk.StringVar()
        centry = ttk.Entry(top, textvariable=self.client_var)
        centry.grid(row=0, column=1, sticky="ew")
        centry.bind("<Return>", lambda _e: self.scan(self.client_var.get()))
        centry.bind("<FocusOut>", lambda _e: self.scan(self.client_var.get()))
        ttk.Button(top, text="Browse...", command=self.browse_client).grid(row=0, column=2, padx=4)

        ttk.Label(top, text="Output folder:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.out_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.out_var).grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(top, text="Browse...", command=self.browse_out).grid(row=1, column=2, padx=4, pady=(6, 0))
        top.columnconfigure(1, weight=1)

        mid = ttk.Frame(root, padding=(8, 0))
        mid.pack(fill="both", expand=True)
        self.found_var = tk.StringVar(value="Detected packs: 0")
        ttk.Label(mid, textvariable=self.found_var).pack(anchor="w")
        box = ttk.Frame(mid)
        box.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(box, selectmode=tk.EXTENDED, height=8)
        sb = ttk.Scrollbar(box, command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        btns = ttk.Frame(mid)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Select all", command=lambda: self.listbox.selection_set(0, "end")).pack(side="left")
        ttk.Button(btns, text="Select none", command=lambda: self.listbox.selection_clear(0, "end")).pack(side="left", padx=4)

        self.decode_var = tk.BooleanVar(value=True)
        self.decode_world_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(mid, text="Decode .ZU1 tables (into the DATA folder)",
                        variable=self.decode_var).pack(anchor="w")
        ttk.Checkbutton(mid, text="Decode WORLDS/*.DAT (into the WORLDS folder)",
                        variable=self.decode_world_var).pack(anchor="w")

        bar = ttk.Frame(root, padding=8)
        bar.pack(fill="x")
        self.run_btn = ttk.Button(bar, text="Extract selected", command=self.start_extract)
        self.run_btn.pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True, padx=8)

        self.log = tk.Text(root, height=10, wrap="none", state="disabled")
        self.log.pack(fill="both", expand=True)
        self._poll()

    def browse_client(self):
        d = filedialog.askdirectory(title="Select the Zu client folder")
        if d:
            self.client_var.set(d)
            self.scan(d)

    def browse_out(self):
        d = filedialog.askdirectory(title="Select output folder")
        if d:
            self.out_var.set(d)

    def scan(self, folder):
        self.packs = find_packs(folder)
        self.listbox.delete(0, "end")
        for p in self.packs:
            try:
                sz = _humansize(os.path.getsize(p))
            except OSError:
                sz = "?"
            self.listbox.insert("end", "%s  (%s)" % (os.path.basename(p), sz))
        self.listbox.selection_set(0, "end")
        self.found_var.set("Detected packs: %d" % len(self.packs))
        self.logln("Found %d .zu pack(s) in %s" % (len(self.packs), folder))

    def logln(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def start_extract(self):
        if not self.packs:
            messagebox.showwarning("No packs", "Select a client folder with .zu packs first.")
            return
        idxs = self.listbox.curselection()
        if not idxs:
            messagebox.showwarning("No selection", "Select at least one pack to extract.")
            return
        out = self.out_var.get().strip()
        if not out:
            messagebox.showwarning("No output", "Choose an output folder.")
            return
        sel = [self.packs[i] for i in idxs]
        self.run_btn.config(state="disabled")
        self.progress.start(12)
        t = threading.Thread(target=self._worker,
                             args=(sel, out, self.decode_var.get(), self.decode_world_var.get()),
                             daemon=True)
        t.start()

    def _worker(self, packs, out, decode_tables, decode_worlds):
        try:
            for pack in packs:
                self.logln("Extracting %s -> %s" % (os.path.basename(pack), out))
                ar = zurez.Archive(pack)
                n = 0
                for rel, rsz, rpos in ar.entries():
                    dst = os.path.join(out, rel.lstrip("/").replace("/", os.sep))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, "wb") as o:
                        o.write(ar.read(rpos, rsz))
                    n += 1
                    if n % 200 == 0:
                        self.logln("  ... %d files" % n)
                ar.close()
                self.logln("  done: %d files" % n)
            data_dirs, world_dirs = find_special_dirs(out)
            if decode_tables:
                for d in data_dirs:
                    self.logln("Decode .ZU1 tables: %s" % d)
                    zudata.dumpall(d, d)
            if decode_worlds:
                for d in world_dirs:
                    self.logln("Decode worlds: %s" % d)
                    zuworld.dumpall(d, d)
            self.q.put(("done", None))
        except Exception as e:
            self.q.put(("error", "%s\n%s" % (e, traceback.format_exc())))

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.logln(payload)
                elif kind == "done":
                    self.progress.stop()
                    self.run_btn.config(state="normal")
                    self.logln("All done.")
                    messagebox.showinfo("Done", "Extraction finished.")
                elif kind == "error":
                    self.progress.stop()
                    self.run_btn.config(state="normal")
                    self.logln("ERROR: " + payload)
                    messagebox.showerror("Error", payload)
        except queue.Empty:
            pass
        self.root.after(120, self._poll)


def _selftest():
    import tempfile
    d = tempfile.mkdtemp()
    for name in ("zu_pack10.zu", "zu_pack2.zu", "zu_pack1.zu", "readme.txt"):
        open(os.path.join(d, name), "wb").close()
    packs = find_packs(d)
    names = [os.path.basename(p) for p in packs]
    assert names == ["zu_pack1.zu", "zu_pack2.zu", "zu_pack10.zu"], names
    data = os.path.join(d, "X", "DATA")
    worlds = os.path.join(d, "X", "WORLDS")
    os.makedirs(data)
    os.makedirs(worlds)
    open(os.path.join(data, "ITEMS.ZU1"), "wb").close()
    open(os.path.join(worlds, "XR.DAT"), "wb").close()
    dd, wd = find_special_dirs(os.path.join(d, "X"))
    assert dd == [data], dd
    assert wd == [worlds], wd
    print("gui selftest OK")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
