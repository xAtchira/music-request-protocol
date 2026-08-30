import socket
import threading
import json
import os

import protocol

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 5000

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MUSIC_DATA_FILE = os.path.join(BASE_DIR, "music_data.json")
MUSIC_DIR = os.path.join(BASE_DIR, "music")

RECV_BUFFER = 4096          # bytes read at a time while parsing request lines
FILE_SEND_CHUNK = 8192      # bytes per chunk while streaming a file


print_lock = threading.Lock()


def log(message):
    """Thread-safe print for server-side logging."""
    with print_lock:
        print(message)


# ---------------------------------------------------------------------------
# Music metadata handling
# ---------------------------------------------------------------------------
def load_music_data():
    """
    Load the song catalog from music_data.json.
    """
    try:
        with open(MUSIC_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        log(f"[SERVER] ERROR: {MUSIC_DATA_FILE} not found.")
        return []
    except json.JSONDecodeError as e:
        log(f"[SERVER] ERROR: Invalid JSON in music_data.json: {e}")
        return []


def find_song_by_id(songs, song_id):
    for song in songs:
        if song["id"] == song_id:
            return song
    return None


def search_songs(songs, keyword):
    """Case-insensitive search across title, artist, album, genre."""
    keyword_lower = keyword.lower()
    results = []
    for song in songs:
        haystack = " ".join(
            [song["title"], song["artist"], song["album"], song["genre"]]
        ).lower()
        if keyword_lower in haystack:
            results.append(song)
    return results


# ---------------------------------------------------------------------------
# Socket-level helpers
# ---------------------------------------------------------------------------
def recv_line(conn, buffer):

    while b"\r\n" not in buffer:
        chunk = conn.recv(RECV_BUFFER)
        if not chunk:
            # client closed the connection
            return None, buffer
        buffer += chunk

    line_bytes, _, buffer = buffer.partition(b"\r\n")
    try:
        line = line_bytes.decode("utf-8")
    except UnicodeDecodeError:
        line = ""  # will be treated as an invalid/empty request
    return line, buffer


def send_response(conn, response_text):
    conn.sendall(response_text.encode("utf-8"))


# ---------------------------------------------------------------------------
# Request handlers - one function per MRP command
# ---------------------------------------------------------------------------
def handle_list(songs):
    data_lines = [f"COUNT {len(songs)}"]
    for song in songs:
        data_lines.append(protocol.format_song_line(song))
    return protocol.build_response(protocol.STATUS_OK, data_lines)


def handle_search(songs, keyword):
    if keyword == "":
        return protocol.build_response(
            protocol.STATUS_BAD_REQUEST, ["Missing search keyword"]
        )

    results = search_songs(songs, keyword)
    if not results:
        return protocol.build_response(
            protocol.STATUS_NOT_FOUND, ["No matching songs"]
        )

    data_lines = [f"COUNT {len(results)}"]
    for song in results:
        data_lines.append(protocol.format_song_line(song))
    return protocol.build_response(protocol.STATUS_OK, data_lines)


def handle_info(songs, param):
    if param == "":
        return protocol.build_response(
            protocol.STATUS_BAD_REQUEST, ["Missing Song ID"]
        )
    if not param.isdigit():
        return protocol.build_response(
            protocol.STATUS_BAD_REQUEST, ["Song ID must be an integer"]
        )

    song = find_song_by_id(songs, int(param))
    if song is None:
        return protocol.build_response(
            protocol.STATUS_NOT_FOUND, ["Song ID does not exist"]
        )

    return protocol.build_response(protocol.STATUS_OK, protocol.format_song_info(song))


def handle_download(conn, songs, param):

    if param == "":
        response = protocol.build_response(
            protocol.STATUS_BAD_REQUEST, ["Missing Song ID"]
        )
        send_response(conn, response)
        return response

    if not param.isdigit():
        response = protocol.build_response(
            protocol.STATUS_BAD_REQUEST, ["Song ID must be an integer"]
        )
        send_response(conn, response)
        return response

    song = find_song_by_id(songs, int(param))
    if song is None:
        response = protocol.build_response(
            protocol.STATUS_NOT_FOUND, ["Song ID does not exist"]
        )
        send_response(conn, response)
        return response

    file_path = os.path.join(MUSIC_DIR, song["file"])
    if not os.path.isfile(file_path):
        response = protocol.build_response(
            protocol.STATUS_FILE_NOT_FOUND, ["Music file does not exist on server"]
        )
        send_response(conn, response)
        return response

    file_size = os.path.getsize(file_path)
    response = protocol.build_response(
        protocol.STATUS_OK,
        [f"FILE_NAME {song['file']}", f"FILE_SIZE {file_size}"],
    )
    send_response(conn, response)

    # Stream the binary file data right after the text header.
    bytes_sent = 0
    try:
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(FILE_SEND_CHUNK)
                if not chunk:
                    break
                conn.sendall(chunk)
                bytes_sent += len(chunk)
    except (BrokenPipeError, ConnectionResetError, OSError) as e:
        log(f"[SERVER] Connection lost while sending file: {e}")

    log(f"[SERVER] Sent {bytes_sent}/{file_size} bytes for '{song['file']}'.")
    return response


# ---------------------------------------------------------------------------
# Per-client thread
# ---------------------------------------------------------------------------
def handle_client(conn, addr):
    log(f"\n[SERVER] Client connected: {addr[0]}:{addr[1]}")

    songs = load_music_data()  # reload catalog per-connection so edits are picked up
    buffer = b""

    try:
        while True:
            try:
                line, buffer = recv_line(conn, buffer)
            except ConnectionResetError:
                log(f"[SERVER] Client {addr[0]}:{addr[1]} reset the connection.")
                break

            if line is None:
                log(f"[SERVER] Client {addr[0]}:{addr[1]} disconnected.")
                break

            log(f"\n[REQUEST]\n{line}")

            parsed = protocol.parse_request(line)

            # --- Invalid / unparsable request line -------------------------------
            if not parsed.is_valid:
                response = protocol.build_response(
                    protocol.STATUS_BAD_REQUEST, ["Empty or malformed request"]
                )
                send_response(conn, response)
                log(f"[RESPONSE]\n{response.strip()}")
                continue

            command = parsed.command
            param = parsed.parameter

            # --- Unknown command ---------------------------------------------------
            if command not in protocol.VALID_COMMANDS:
                response = protocol.build_response(protocol.STATUS_METHOD_NOT_ALLOWED)
                send_response(conn, response)
                log(f"[RESPONSE]\n{response.strip()}")
                log(f"[SERVER] Unsupported command: {command}")
                continue

            # --- QUIT ----------------------------------------------------------------
            if command == protocol.CMD_QUIT:
                response = protocol.build_response(protocol.STATUS_BYE)
                send_response(conn, response)
                log(f"[RESPONSE]\n{response.strip()}")
                log(f"[SERVER] Client {addr[0]}:{addr[1]} requested QUIT. Closing connection.")
                break

            # --- LIST ------------------------------------------------------------------
            try:
                if command == protocol.CMD_LIST:
                    response = handle_list(songs)
                    send_response(conn, response)

                elif command == protocol.CMD_SEARCH:
                    response = handle_search(songs, param)
                    send_response(conn, response)

                elif command == protocol.CMD_INFO:
                    response = handle_info(songs, param)
                    send_response(conn, response)

                elif command == protocol.CMD_DOWNLOAD:
                    # handle_download sends its own response (and binary data)
                    response = handle_download(conn, songs, param)

                log(f"[RESPONSE]\n{response.strip()}")
                log("[SERVER] Response sent successfully.")

            except Exception as e:
                # Catch-all so a single bad request never crashes the server/thread
                log(f"[SERVER] Internal error while handling '{command}': {e}")
                try:
                    error_response = protocol.build_response(
                        protocol.STATUS_SERVER_ERROR, ["Internal server error"]
                    )
                    send_response(conn, error_response)
                except OSError:
                    pass  # connection already broken; nothing more we can do

    finally:
        conn.close()
        log(f"[SERVER] Connection closed: {addr[0]}:{addr[1]}")


# ---------------------------------------------------------------------------
# Main server loop
# ---------------------------------------------------------------------------
def main():
    print("=" * 40)
    print("       MUSIC REQUEST SERVER")
    print("       Protocol: MRP")
    print("=" * 40)

    os.makedirs(MUSIC_DIR, exist_ok=True)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((HOST, PORT))
    except OSError as e:
        print(f"[SERVER] ERROR: Could not bind to {HOST}:{PORT} -> {e}")
        return

    server_socket.listen(5)
    print(f"\n[SERVER] Listening on {HOST}:{PORT}")
    print("[SERVER] Press Ctrl+C to stop.\n")

    try:
        while True:
            conn, addr = server_socket.accept()
            client_thread = threading.Thread(
                target=handle_client, args=(conn, addr), daemon=True
            )
            client_thread.start()
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down (KeyboardInterrupt).")
    finally:
        server_socket.close()


if __name__ == "__main__":
    main()
