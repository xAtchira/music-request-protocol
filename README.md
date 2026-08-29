# Music Request Server

A Client–Server application demonstrating **TCP Socket Programming** and a
custom **Application-Layer Protocol**: **MRP — Music Request Protocol**.

Built for a Computer Networks / Socket Programming course project. No
Flask, no FastAPI, no WebSocket, no database server, no third-party
packages — just Python's standard `socket`, `threading`, and `json`.

---

## 1. Protocol Name

**MRP — Music Request Protocol**

## 2. Purpose

MRP lets a client browse, search, inspect, and download songs from a music
server over a single persistent TCP connection. It is a small,
line-oriented, text-based request/response protocol (similar in spirit to
FTP's control channel), with a raw binary payload appended after the text
header for file downloads.

## 3. Transport Layer

**TCP** (`SOCK_STREAM`).

TCP was chosen over UDP because:

- **Reliability** — song metadata and, more importantly, binary music
  file bytes must arrive complete and uncorrupted. A single dropped or
  reordered UDP datagram could corrupt an `.mp3` file.
- **Connection-oriented** — the client holds one connection open across
  multiple commands (`LIST`, `SEARCH`, `INFO`, `DOWNLOAD`, ... `QUIT`),
  which maps naturally onto a TCP session.
- **Ordered byte stream** — MRP relies on reading the response in the
  exact order it was written (status line, then data lines, then binary
  payload), which TCP guarantees and UDP does not.

## 4. Message Format

All text lines are UTF-8 and terminated with `\r\n`.

```
REQUEST:
<COMMAND> [PARAMETER]\r\n

RESPONSE:
<STATUS_CODE> <STATUS_PHRASE>\r\n
<DATA LINE 1>\r\n
<DATA LINE 2>\r\n
...
```

- A request is always exactly one line.
- A response always starts with a status line.
- Data lines that follow are protocol-specific (see each command below).
- For `LIST` / `SEARCH`, the first data line is `COUNT n`, telling the
  client how many song lines to expect next — this lets the client know
  exactly when the response ends without needing an extra terminator.
- For `DOWNLOAD`, the data lines give `FILE_NAME` and `FILE_SIZE`, and are
  immediately followed by exactly `FILE_SIZE` raw bytes on the same TCP
  stream (no text encoding, no framing needed beyond the byte count).

## 5. Request Commands

| Command | Parameter | Description |
|---|---|---|
| `LIST` | — | Request the full song catalog |
| `SEARCH` | `<keyword>` | Search title / artist / album / genre (case-insensitive substring match) |
| `INFO` | `<song_id>` | Request full metadata for one song |
| `DOWNLOAD` | `<song_id>` | Request the binary music file for one song |
| `QUIT` | — | Gracefully close the connection |

## 6. Response Status Codes

| Code | Phrase | Meaning |
|---|---|---|
| 200 | OK | Request succeeded |
| 200 | BYE | Sent in response to `QUIT`, just before the server closes the socket |
| 201 | READY | Reserved — server is ready (not actively used, available for a future greeting banner) |
| 400 | BAD REQUEST | Malformed request: missing command, missing parameter, or wrong parameter type (e.g. non-numeric Song ID) |
| 404 | NOT FOUND | No matching songs (`SEARCH`) or Song ID does not exist (`INFO` / `DOWNLOAD`) |
| 404 | FILE NOT FOUND | Song metadata exists but the actual audio file is missing on the server (`DOWNLOAD` only) |
| 405 | METHOD NOT ALLOWED | Unrecognized command |
| 500 | SERVER ERROR | Unexpected internal server error |

## 7. Request / Response Examples

**LIST**
```
>> LIST
<< 200 OK
<< COUNT 8
<< 101|Believer|Imagine Dragons|Evolve|Rock|204
<< 102|Perfect|Ed Sheeran|Divide|Pop|263
<< ...
```

**SEARCH (found)**
```
>> SEARCH Ed Sheeran
<< 200 OK
<< COUNT 3
<< 102|Perfect|Ed Sheeran|Divide|Pop|263
<< 103|Shape of You|Ed Sheeran|Divide|Pop|234
<< 107|Photograph|Ed Sheeran|X|Pop|258
```

**SEARCH (not found)**
```
>> SEARCH xyz
<< 404 NOT FOUND
<< No matching songs
```

**INFO**
```
>> INFO 101
<< 200 OK
<< ID: 101
<< TITLE: Believer
<< ARTIST: Imagine Dragons
<< ALBUM: Evolve
<< GENRE: Rock
<< DURATION: 204
<< FILE: believer.mp3
```

**INFO (not found)**
```
>> INFO 999
<< 404 NOT FOUND
<< Song ID does not exist
```

**Invalid command**
```
>> HELLO
<< 405 METHOD NOT ALLOWED
```

**Invalid / missing parameter**
```
>> INFO
<< 400 BAD REQUEST
<< Missing Song ID

>> INFO ABC
<< 400 BAD REQUEST
<< Song ID must be an integer
```

**DOWNLOAD (success)**
```
>> DOWNLOAD 101
<< 200 OK
<< FILE_NAME believer.mp3
<< FILE_SIZE 500000
<< [500000 bytes of raw binary data follow immediately]
```

**DOWNLOAD (metadata exists, file missing on disk)**
```
>> DOWNLOAD 104
<< 404 FILE NOT FOUND
<< Music file does not exist on server
```

**QUIT**
```
>> QUIT
<< 200 BYE
```
(server then closes the TCP connection)

## 8. Error Handling

The protocol and both endpoints are designed to never crash on bad input:

| Scenario | Handling |
|---|---|
| Server not running | Client catches `ConnectionRefusedError` / `OSError`, prints a clear message, exits cleanly |
| Client fails to connect | Same as above |
| Unknown command | Server replies `405 METHOD NOT ALLOWED` |
| Missing parameter | Server replies `400 BAD REQUEST` |
| Song ID not numeric | Server replies `400 BAD REQUEST` |
| Song ID does not exist | Server replies `404 NOT FOUND` |
| Music file missing on disk | Server replies `404 FILE NOT FOUND` |
| Client disconnects abruptly | Server's `recv()` returns empty bytes / raises `ConnectionResetError`; server logs it, closes that client's thread, and keeps serving other clients |
| Connection dropped mid-download | Client's `recv_exact()` raises a `ServerDisconnected` exception with a partial-byte-count message instead of silently producing a corrupt file |
| Invalid / unparsable request line | Server replies `400 BAD REQUEST` |
| Unexpected server-side exception | Caught per-request, logged, and reported to the client as `500 SERVER ERROR` instead of killing the thread |

## 9. File Download Procedure

1. Client sends `DOWNLOAD <song_id>`.
2. Server validates the parameter and looks up the song.
3. If valid and the file exists, server sends the text header
   (`200 OK`, `FILE_NAME`, `FILE_SIZE`) first.
4. Server then reads the file in `8192`-byte chunks and calls
   `sendall()` for each chunk over the **same** TCP connection.
5. Client reads exactly `FILE_SIZE` bytes total (draining any bytes
   already buffered from the line-based reads first), reporting progress
   every time it crosses a new 10% boundary.
6. Client writes the collected bytes to `downloads/<file_name>` using
   `open(path, "wb")`.
7. Client compares the number of bytes received against the expected
   `FILE_SIZE` and prints `Download completed successfully.` or a
   mismatch warning.

---

## Project Files

```
music-request-server/
├── server.py          TCP server: socket/bind/listen/accept, threading,
│                       request routing, file streaming, logging
├── client.py           TCP client: menu, request building, response
│                       parsing/display, file receiving, logging
├── protocol.py          MRP logic only: constants, request parser,
│                        response builder — no socket code at all
├── music_data.json     Song catalog (8 sample songs)
├── music/                Sample audio files (some intentionally present,
│                        some intentionally absent to demo 404 FILE NOT FOUND)
├── downloads/           Destination folder for client-side downloads
└── README.md            This file
```

## How to Run

**Requires:** Python 3.x (standard library only, works on Windows 10/11,
macOS, Linux).

**Terminal 1 — start the server:**
```
python server.py
```

**Terminal 2 — start the client:**
```
python client.py
```

Follow the on-screen menu (1–5). Every request and response is printed
in both terminals so you can watch the protocol exchange live — useful
for demo recording.

To stop the server, press `Ctrl+C` in its terminal.
