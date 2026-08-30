import socket
import os

import protocol

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 5000

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")

RECV_BUFFER = 4096
FILE_RECV_CHUNK = 8192


class ServerDisconnected(Exception):
    """Raised internally when the server closes the connection unexpectedly."""
    pass


# ---------------------------------------------------------------------------
# Low-level socket helpers (mirror server.py's line-buffering logic)
# ---------------------------------------------------------------------------
class MRPConnection:

    def __init__(self, sock):
        self.sock = sock
        self.buffer = b""

    def recv_line(self):
        while b"\r\n" not in self.buffer:
            chunk = self.sock.recv(RECV_BUFFER)
            if not chunk:
                raise ServerDisconnected("Server closed the connection.")
            self.buffer += chunk
        line_bytes, _, self.buffer = self.buffer.partition(b"\r\n")
        return line_bytes.decode("utf-8", errors="replace")

    def recv_exact(self, num_bytes, on_progress=None):
        """
        Read exactly num_bytes of raw binary data (first draining any bytes
        already sitting in self.buffer from the line-based reads).
        """
        data = bytearray()

        # Use any leftover buffered bytes first
        if self.buffer:
            take = min(len(self.buffer), num_bytes)
            data += self.buffer[:take]
            self.buffer = self.buffer[take:]

        while len(data) < num_bytes:
            chunk = self.sock.recv(min(FILE_RECV_CHUNK, num_bytes - len(data)))
            if not chunk:
                raise ServerDisconnected(
                    f"Connection lost during transfer ({len(data)}/{num_bytes} bytes received)."
                )
            data += chunk
            if on_progress:
                on_progress(len(data), num_bytes)

        return bytes(data)

    def send_line(self, text):
        self.sock.sendall((text + protocol.TERMINATOR).encode("utf-8"))

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
def log_request(raw_request):
    print("\n[CLIENT] Sending Request")
    print(f">> {raw_request}")


def log_response(status_line, data_lines=None):
    print("\n[CLIENT] Received Response")
    print(f"<< {status_line}")
    if data_lines:
        for line in data_lines:
            print(f"<< {line}")


# ---------------------------------------------------------------------------
# Response reading helpers
# ---------------------------------------------------------------------------
def read_simple_response(conn, expected_data_lines=0, count_prefixed=False):

    status_line = conn.recv_line()
    data_lines = []

    if count_prefixed:
        first_line = conn.recv_line()
        data_lines.append(first_line)
        if first_line.upper().startswith("COUNT"):
            try:
                n = int(first_line.split(" ", 1)[1])
            except (IndexError, ValueError):
                n = 0
            for _ in range(n):
                data_lines.append(conn.recv_line())
    else:
        for _ in range(expected_data_lines):
            data_lines.append(conn.recv_line())

    return status_line, data_lines


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------
def do_list(conn):
    raw = protocol.CMD_LIST
    log_request(raw)
    conn.send_line(raw)

    status_line, data_lines = read_simple_response(conn, count_prefixed=True)
    log_response(status_line, data_lines)

    if status_line.startswith("200"):
        print("\nAvailable Songs:\n")
        for line in data_lines[1:]:  # skip the COUNT line
            fields = line.split("|")
            if len(fields) >= 3:
                print(f"{fields[0]} | {fields[1]} | {fields[2]}")
    else:
        print(f"\nError: {status_line}")


def do_search(conn):
    keyword = input("Enter search keyword: ").strip()
    raw = f"{protocol.CMD_SEARCH} {keyword}"
    log_request(raw)
    conn.send_line(raw)

    status_line = conn.recv_line()

    if status_line.startswith("200"):
        first_line = conn.recv_line()
        data_lines = [first_line]
        try:
            n = int(first_line.split(" ", 1)[1])
        except (IndexError, ValueError):
            n = 0
        for _ in range(n):
            data_lines.append(conn.recv_line())

        log_response(status_line, data_lines)
        print("\nSearch Results:\n")
        for line in data_lines[1:]:
            fields = line.split("|")
            if len(fields) >= 3:
                print(f"{fields[0]} | {fields[1]} | {fields[2]}")
    else:
        # 404 NOT FOUND or 400 BAD REQUEST -> single message line follows
        message = conn.recv_line()
        log_response(status_line, [message])
        print(f"\nError: {message}")


def do_info(conn):
    song_id = input("Enter Song ID: ").strip()
    raw = f"{protocol.CMD_INFO} {song_id}"
    log_request(raw)
    conn.send_line(raw)

    status_line = conn.recv_line()

    if status_line.startswith("200"):
        data_lines = [conn.recv_line() for _ in range(7)]  # ID/TITLE/ARTIST/ALBUM/GENRE/DURATION/FILE
        log_response(status_line, data_lines)

        fields = {}
        for line in data_lines:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()

        print()
        print(f"ID       : {fields.get('ID', '')}")
        print(f"Title    : {fields.get('TITLE', '')}")
        print(f"Artist   : {fields.get('ARTIST', '')}")
        print(f"Album    : {fields.get('ALBUM', '')}")
        print(f"Genre    : {fields.get('GENRE', '')}")

        duration_raw = fields.get("DURATION", "0")
        try:
            seconds = int(duration_raw)
            print(f"Duration : {seconds // 60}:{seconds % 60:02d}")
        except ValueError:
            print(f"Duration : {duration_raw}")

        print(f"File     : {fields.get('FILE', '')}")
    else:
        message = conn.recv_line()
        log_response(status_line, [message])
        print(f"\nError: {message}")


def do_download(conn):
    song_id = input("Enter Song ID: ").strip()
    raw = f"{protocol.CMD_DOWNLOAD} {song_id}"
    log_request(raw)
    conn.send_line(raw)

    status_line = conn.recv_line()

    if not status_line.startswith("200"):
        message = conn.recv_line()
        log_response(status_line, [message])
        print(f"\nError: {message}")
        return

    file_name_line = conn.recv_line()   # "FILE_NAME believer.mp3"
    file_size_line = conn.recv_line()   # "FILE_SIZE 5242880"
    log_response(status_line, [file_name_line, file_size_line])

    try:
        file_name = file_name_line.split(" ", 1)[1].strip()
        file_size = int(file_size_line.split(" ", 1)[1].strip())
    except (IndexError, ValueError):
        print("\nError: Malformed DOWNLOAD response header from server.")
        return

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    dest_path = os.path.join(DOWNLOAD_DIR, file_name)

    print(f"\nDownloading {file_name}...\n")

    last_reported = [-1]  # mutable holder so the closure below can update it

    def report_progress(received, total):
        percent = int((received / total) * 100) if total else 100
        # only print every time the percentage crosses a new 10% boundary
        bucket = percent // 10
        if bucket != last_reported[0]:
            last_reported[0] = bucket
            print(f"Progress: {percent}%")

    try:
        file_data = conn.recv_exact(file_size, on_progress=report_progress)
    except ServerDisconnected as e:
        print(f"\nError: {e}")
        return

    with open(dest_path, "wb") as f:
        f.write(file_data)

    if len(file_data) == file_size:
        print("\nDownload completed successfully.")
        print(f"Saved to: {dest_path}")
    else:
        print("\nWarning: Downloaded file size does not match expected size.")


def do_quit(conn):
    raw = protocol.CMD_QUIT
    log_request(raw)
    conn.send_line(raw)

    status_line = conn.recv_line()
    log_response(status_line)
    print("\nConnection closed. Goodbye!")


# ---------------------------------------------------------------------------
# Menu / main loop
# ---------------------------------------------------------------------------
def print_menu():
    print("\n" + "=" * 40)
    print("       MUSIC REQUEST CLIENT")
    print("       Protocol: MRP")
    print("=" * 40)
    print("\n1. List Songs")
    print("2. Search Song")
    print("3. Song Information")
    print("4. Download Song")
    print("5. Quit")


def connect_to_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((HOST, PORT))
    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        print(f"[CLIENT] ERROR: Could not connect to {HOST}:{PORT} -> {e}")
        print("[CLIENT] Is the server running?")
        return None
    print(f"[CLIENT] Connected to server {HOST}:{PORT}")
    return MRPConnection(sock)


def main():
    conn = connect_to_server()
    if conn is None:
        return

    try:
        while True:
            print_menu()
            choice = input("\nSelect option: ").strip()

            try:
                if choice == "1":
                    do_list(conn)
                elif choice == "2":
                    do_search(conn)
                elif choice == "3":
                    do_info(conn)
                elif choice == "4":
                    do_download(conn)
                elif choice == "5":
                    do_quit(conn)
                    break
                else:
                    print("\nInvalid option. Please choose 1-5.")

            except ServerDisconnected as e:
                print(f"\n[CLIENT] {e}")
                print("[CLIENT] Connection lost. Exiting.")
                break
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                print(f"\n[CLIENT] Connection error: {e}")
                break

    except KeyboardInterrupt:
        print("\n[CLIENT] Interrupted by user. Closing connection.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
