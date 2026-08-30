import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import protocol
from client import MRPConnection, ServerDisconnected, HOST as DEFAULT_HOST, PORT as DEFAULT_PORT

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")

FONT_MONO = ("Consolas", 10)
FONT_UI = ("Segoe UI", 10)


# ---------------------------------------------------------------------------
# Background network worker
# ---------------------------------------------------------------------------
class NetworkWorker:

    def __init__(self, out_queue):
        self.out_queue = out_queue
        self.conn = None
        self.lock = threading.Lock()

    def is_connected(self):
        return self.conn is not None

    def _emit(self, msg_type, payload=None):
        self.out_queue.put((msg_type, payload))

    def _log(self, direction, text):
        # direction: ">>" for sent, "<<" for received
        self._emit("log", f"{direction} {text}")

    # ---- Connection lifecycle -------------------------------------------------
    def connect(self, host, port):
        def run():
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            try:
                sock.connect((host, port))
                sock.settimeout(None)
            except (ConnectionRefusedError, TimeoutError, OSError) as e:
                self._emit("connect_failed", str(e))
                return
            self.conn = MRPConnection(sock)
            self._emit("connected", f"{host}:{port}")

        threading.Thread(target=run, daemon=True).start()

    def disconnect_silently(self):
        """Close the socket without sending QUIT (used on force-close)."""
        if self.conn:
            self.conn.close()
            self.conn = None

    # ---- Commands ---------------------------------------------------------------
    def list_songs(self):
        def run():
            try:
                self._log(">>", protocol.CMD_LIST)
                self.conn.send_line(protocol.CMD_LIST)

                status_line = self.conn.recv_line()
                first_line = self.conn.recv_line()
                data_lines = [first_line]
                n = self._extract_count(first_line)
                for _ in range(n):
                    data_lines.append(self.conn.recv_line())

                self._log("<<", status_line)
                for line in data_lines:
                    self._log("<<", line)

                self._emit("list_result", (status_line, data_lines))
            except (ServerDisconnected, OSError) as e:
                self._emit("error", str(e))

        threading.Thread(target=run, daemon=True).start()

    def search_songs(self, keyword):
        def run():
            try:
                raw = f"{protocol.CMD_SEARCH} {keyword}"
                self._log(">>", raw)
                self.conn.send_line(raw)

                status_line = self.conn.recv_line()
                self._log("<<", status_line)

                data_lines = []
                if status_line.startswith("200"):
                    first_line = self.conn.recv_line()
                    data_lines.append(first_line)
                    self._log("<<", first_line)
                    n = self._extract_count(first_line)
                    for _ in range(n):
                        line = self.conn.recv_line()
                        data_lines.append(line)
                        self._log("<<", line)
                else:
                    message = self.conn.recv_line()
                    data_lines.append(message)
                    self._log("<<", message)

                self._emit("search_result", (status_line, data_lines))
            except (ServerDisconnected, OSError) as e:
                self._emit("error", str(e))

        threading.Thread(target=run, daemon=True).start()

    def get_info(self, song_id):
        def run():
            try:
                raw = f"{protocol.CMD_INFO} {song_id}"
                self._log(">>", raw)
                self.conn.send_line(raw)

                status_line = self.conn.recv_line()
                self._log("<<", status_line)

                if status_line.startswith("200"):
                    data_lines = [self.conn.recv_line() for _ in range(7)]
                else:
                    data_lines = [self.conn.recv_line()]
                for line in data_lines:
                    self._log("<<", line)

                self._emit("info_result", (status_line, data_lines))
            except (ServerDisconnected, OSError) as e:
                self._emit("error", str(e))

        threading.Thread(target=run, daemon=True).start()

    def download(self, song_id, save_path):
        def run():
            try:
                raw = f"{protocol.CMD_DOWNLOAD} {song_id}"
                self._log(">>", raw)
                self.conn.send_line(raw)

                status_line = self.conn.recv_line()
                self._log("<<", status_line)

                if not status_line.startswith("200"):
                    message = self.conn.recv_line()
                    self._log("<<", message)
                    self._emit("download_failed", f"{status_line}: {message}")
                    return

                file_name_line = self.conn.recv_line()
                file_size_line = self.conn.recv_line()
                self._log("<<", file_name_line)
                self._log("<<", file_size_line)

                file_size = int(file_size_line.split(" ", 1)[1].strip())
                self._emit("download_header", (song_id, save_path, file_size))

                def on_progress(received, total):
                    self._emit("download_progress", (received, total))

                file_data = self.conn.recv_exact(file_size, on_progress=on_progress)

                with open(save_path, "wb") as f:
                    f.write(file_data)

                ok = len(file_data) == file_size
                self._emit("download_done", (save_path, len(file_data), file_size, ok))

            except (ServerDisconnected, OSError, ValueError, IndexError) as e:
                self._emit("download_failed", str(e))

        threading.Thread(target=run, daemon=True).start()

    def quit(self):
        def run():
            try:
                self._log(">>", protocol.CMD_QUIT)
                self.conn.send_line(protocol.CMD_QUIT)
                status_line = self.conn.recv_line()
                self._log("<<", status_line)
                self.conn.close()
                self.conn = None
                self._emit("quit_done", status_line)
            except (ServerDisconnected, OSError) as e:
                self.conn = None
                self._emit("quit_done", f"(connection already closed: {e})")

        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def _extract_count(count_line):
        try:
            return int(count_line.split(" ", 1)[1])
        except (IndexError, ValueError):
            return 0


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------
class MusicClientApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Music Request Client — MRP Protocol")
        self.geometry("980x640")
        self.minsize(860, 560)

        self.out_queue = queue.Queue()
        self.worker = NetworkWorker(self.out_queue)
        self.connected = False
        self.busy = False  # True while a request is in flight

        self._build_widgets()
        self._set_connected_state(False)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.after(50, self._poll_queue)

    # ---- UI construction ----------------------------------------------------------
    def _build_widgets(self):
        # ---- Top: connection bar --------------------------------------------------
        top = ttk.Frame(self, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Host:", font=FONT_UI).pack(side=tk.LEFT)
        self.host_var = tk.StringVar(value=DEFAULT_HOST)
        ttk.Entry(top, textvariable=self.host_var, width=14).pack(side=tk.LEFT, padx=(4, 12))

        ttk.Label(top, text="Port:", font=FONT_UI).pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        ttk.Entry(top, textvariable=self.port_var, width=8).pack(side=tk.LEFT, padx=(4, 12))

        self.connect_btn = ttk.Button(top, text="Connect", command=self.on_connect_clicked)
        self.connect_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.status_var = tk.StringVar(value="● Not connected")
        self.status_label = ttk.Label(top, textvariable=self.status_var, font=FONT_UI, foreground="#b00020")
        self.status_label.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(top, text="Protocol: MRP (TCP)", font=FONT_UI).pack(side=tk.RIGHT)

        # ---- Action bar --------------------------------------------------------------
        actions = ttk.Frame(self, padding=(8, 0, 8, 8))
        actions.pack(side=tk.TOP, fill=tk.X)

        self.list_btn = ttk.Button(actions, text="List All Songs", command=self.on_list_clicked)
        self.list_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(actions, text="Search:", font=FONT_UI).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(actions, textvariable=self.search_var, width=24)
        search_entry.pack(side=tk.LEFT, padx=(4, 4))
        search_entry.bind("<Return>", lambda e: self.on_search_clicked())
        self.search_btn = ttk.Button(actions, text="Search", command=self.on_search_clicked)
        self.search_btn.pack(side=tk.LEFT, padx=(0, 12))

        self.info_btn = ttk.Button(actions, text="Song Info", command=self.on_info_clicked)
        self.info_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.download_btn = ttk.Button(actions, text="Download", command=self.on_download_clicked)
        self.download_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.quit_btn = ttk.Button(actions, text="Quit / Disconnect", command=self.on_quit_clicked)
        self.quit_btn.pack(side=tk.RIGHT)

        middle = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        middle.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        # Song table
        table_frame = ttk.Frame(middle)
        columns = ("id", "title", "artist", "album", "genre", "duration")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=14)
        headings = {
            "id": ("ID", 50), "title": ("Title", 160), "artist": ("Artist", 140),
            "album": ("Album", 130), "genre": ("Genre", 90), "duration": ("Sec", 50),
        }
        for col, (label, width) in headings.items():
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=tk.W)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_row_selected)

        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        middle.add(table_frame, weight=3)

        # Details panel
        details_frame = ttk.LabelFrame(middle, text="Song Details / Status", padding=10)
        self.details_var = tk.StringVar(value="Select a song, or run List / Search first.")
        ttk.Label(details_frame, textvariable=self.details_var, justify=tk.LEFT,
                  wraplength=260, font=FONT_UI).pack(anchor=tk.NW, fill=tk.X)

        ttk.Separator(details_frame).pack(fill=tk.X, pady=10)

        ttk.Label(details_frame, text="Download progress:", font=FONT_UI).pack(anchor=tk.W)
        self.progress = ttk.Progressbar(details_frame, orient=tk.HORIZONTAL, mode="determinate", length=240)
        self.progress.pack(anchor=tk.W, pady=(4, 4))
        self.progress_label_var = tk.StringVar(value="")
        ttk.Label(details_frame, textvariable=self.progress_label_var, font=FONT_UI).pack(anchor=tk.W)

        middle.add(details_frame, weight=2)

        # ---- Bottom: protocol log ------------------------------------------------------
        log_frame = ttk.LabelFrame(self, text="Protocol Log (raw MRP request/response)", padding=6)
        log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=False, padx=8, pady=(0, 8))
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, font=FONT_MONO, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ---- Helpers ---------------------------------------------------------------------
    def append_log(self, line):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _set_connected_state(self, connected):
        self.connected = connected
        if connected:
            self.status_var.set(f"● Connected to {self.host_var.get()}:{self.port_var.get()}")
            self.status_label.configure(foreground="#0a7d2c")
            self.connect_btn.configure(text="Connected", state=tk.DISABLED)
        else:
            self.status_var.set("● Not connected")
            self.status_label.configure(foreground="#b00020")
            self.connect_btn.configure(text="Connect", state=tk.NORMAL)
        self._set_action_buttons_enabled(connected and not self.busy)

    def _set_action_buttons_enabled(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        for btn in (self.list_btn, self.search_btn, self.info_btn, self.download_btn, self.quit_btn):
            btn.configure(state=state)

    def _set_busy(self, busy):
        self.busy = busy
        self._set_action_buttons_enabled(self.connected and not busy)

    def selected_song_id(self):
        selection = self.tree.selection()
        if not selection:
            return None
        values = self.tree.item(selection[0], "values")
        return values[0] if values else None

    def clear_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

    def populate_table(self, data_lines_after_count):
        self.clear_table()
        for line in data_lines_after_count:
            fields = line.split("|")
            if len(fields) == 6:
                self.tree.insert("", tk.END, values=fields)

    # ---- Button handlers ---------------------------------------------------------------
    def on_connect_clicked(self):
        host = self.host_var.get().strip()
        port_text = self.port_var.get().strip()
        if not host or not port_text.isdigit():
            messagebox.showerror("Invalid input", "Please enter a valid host and numeric port.")
            return
        self.append_log(f"[CLIENT] Connecting to {host}:{port_text} ...")
        self.connect_btn.configure(state=tk.DISABLED)
        self.worker.connect(host, int(port_text))

    def on_list_clicked(self):
        self._set_busy(True)
        self.details_var.set("Requesting song list...")
        self.worker.list_songs()

    def on_search_clicked(self):
        keyword = self.search_var.get().strip()
        if not keyword:
            messagebox.showinfo("Search", "Please type a keyword to search for.")
            return
        self._set_busy(True)
        self.details_var.set(f"Searching for '{keyword}'...")
        self.worker.search_songs(keyword)

    def on_info_clicked(self):
        song_id = self.selected_song_id()
        if song_id is None:
            messagebox.showinfo("Song Info", "Select a song from the table first "
                                              "(run List or Search to populate it).")
            return
        self._set_busy(True)
        self.worker.get_info(song_id)

    def on_download_clicked(self):
        song_id = self.selected_song_id()
        if song_id is None:
            messagebox.showinfo("Download", "Select a song from the table first "
                                             "(run List or Search to populate it).")
            return

        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        default_path = os.path.join(DOWNLOAD_DIR, f"song_{song_id}.mp3")
        save_path = filedialog.asksaveasfilename(
            title="Save downloaded song as...",
            initialdir=DOWNLOAD_DIR,
            initialfile=os.path.basename(default_path),
            defaultextension=".mp3",
        )
        if not save_path:
            return  # user cancelled

        self._set_busy(True)
        self.progress["value"] = 0
        self.progress_label_var.set("Starting download...")
        self.worker.download(song_id, save_path)

    def on_quit_clicked(self):
        if not self.connected:
            return
        self._set_busy(True)
        self.worker.quit()

    def on_row_selected(self, event):
        song_id = self.selected_song_id()
        if song_id:
            self.details_var.set(f"Selected Song ID {song_id}.\nClick 'Song Info' for full details, "
                                  f"or 'Download' to save the audio file.")

    def on_close(self):
        if self.connected and self.worker.is_connected():
            try:
                self.worker.disconnect_silently()
            except Exception:
                pass
        self.destroy()

    # ---- Queue polling / message dispatch -------------------------------------------------
    def _poll_queue(self):
        try:
            while True:
                msg_type, payload = self.out_queue.get_nowait()
                self._handle_message(msg_type, payload)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    def _handle_message(self, msg_type, payload):
        if msg_type == "log":
            self.append_log(payload)

        elif msg_type == "connected":
            self.append_log(f"[CLIENT] Connected to {payload}")
            self._set_connected_state(True)

        elif msg_type == "connect_failed":
            self.append_log(f"[CLIENT] ERROR: Could not connect -> {payload}")
            messagebox.showerror("Connection failed", f"Could not connect to server:\n{payload}")
            self.connect_btn.configure(state=tk.NORMAL)

        elif msg_type == "list_result":
            status_line, data_lines = payload
            self._set_busy(False)
            if status_line.startswith("200"):
                self.populate_table(data_lines[1:])
                self.details_var.set(f"Loaded {len(data_lines) - 1} song(s).")
            else:
                self.details_var.set(f"Error: {status_line}")

        elif msg_type == "search_result":
            status_line, data_lines = payload
            self._set_busy(False)
            if status_line.startswith("200"):
                self.populate_table(data_lines[1:])
                self.details_var.set(f"Search found {len(data_lines) - 1} song(s).")
            else:
                self.clear_table()
                self.details_var.set(f"{status_line}\n{data_lines[0] if data_lines else ''}")

        elif msg_type == "info_result":
            status_line, data_lines = payload
            self._set_busy(False)
            if status_line.startswith("200"):
                pretty = "\n".join(data_lines)
                self.details_var.set(pretty)
            else:
                self.details_var.set(f"{status_line}\n{data_lines[0] if data_lines else ''}")

        elif msg_type == "download_header":
            song_id, save_path, file_size = payload
            self.progress["maximum"] = file_size
            self.progress_label_var.set(f"0 / {file_size} bytes (0%)")

        elif msg_type == "download_progress":
            received, total = payload
            self.progress["value"] = received
            percent = int((received / total) * 100) if total else 100
            self.progress_label_var.set(f"{received} / {total} bytes ({percent}%)")

        elif msg_type == "download_done":
            save_path, received, total, ok = payload
            self._set_busy(False)
            if ok:
                self.progress_label_var.set(f"Done: {received} / {total} bytes (100%)")
                self.details_var.set(f"Download completed successfully.\nSaved to:\n{save_path}")
            else:
                self.progress_label_var.set(f"Incomplete: {received} / {total} bytes")
                self.details_var.set("Warning: downloaded size does not match expected size.")

        elif msg_type == "download_failed":
            self._set_busy(False)
            self.progress_label_var.set("Download failed.")
            self.details_var.set(f"Download error:\n{payload}")
            messagebox.showerror("Download failed", str(payload))

        elif msg_type == "quit_done":
            self.append_log(f"[CLIENT] {payload}")
            self._set_busy(False)
            self._set_connected_state(False)
            self.clear_table()
            self.details_var.set("Disconnected. Click Connect to start a new session.")

        elif msg_type == "error":
            self._set_busy(False)
            self._set_connected_state(False)
            self.append_log(f"[CLIENT] Connection error: {payload}")
            messagebox.showerror("Connection error", str(payload))


def main():
    app = MusicClientApp()
    app.mainloop()


if __name__ == "__main__":
    main()
