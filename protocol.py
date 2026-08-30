# ---------------------------------------------------------------------------
# Line terminator used by MRP for every request line and response line
# ---------------------------------------------------------------------------
TERMINATOR = "\r\n"

# ---------------------------------------------------------------------------
# MRP Commands
# ---------------------------------------------------------------------------
CMD_LIST = "LIST"
CMD_SEARCH = "SEARCH"
CMD_INFO = "INFO"
CMD_DOWNLOAD = "DOWNLOAD"
CMD_QUIT = "QUIT"

VALID_COMMANDS = {CMD_LIST, CMD_SEARCH, CMD_INFO, CMD_DOWNLOAD, CMD_QUIT}

# Commands that require a parameter after them
COMMANDS_REQUIRING_PARAM = {CMD_SEARCH, CMD_INFO, CMD_DOWNLOAD}

# ---------------------------------------------------------------------------
# MRP Status Codes / Phrases
# ---------------------------------------------------------------------------
STATUS_OK = "200 OK"
STATUS_READY = "201 READY"
STATUS_BAD_REQUEST = "400 BAD REQUEST"
STATUS_NOT_FOUND = "404 NOT FOUND"
STATUS_FILE_NOT_FOUND = "404 FILE NOT FOUND"
STATUS_METHOD_NOT_ALLOWED = "405 METHOD NOT ALLOWED"
STATUS_SERVER_ERROR = "500 SERVER ERROR"
STATUS_BYE = "200 BYE"


class ParsedRequest:
    """Simple container for a parsed MRP request."""

    def __init__(self, command, parameter, raw_text, is_valid=True, error_message=""):
        self.command = command
        self.parameter = parameter
        self.raw_text = raw_text
        self.is_valid = is_valid
        self.error_message = error_message

    def __repr__(self):
        return f"ParsedRequest(command={self.command!r}, parameter={self.parameter!r})"


def parse_request(raw_line):

    if raw_line is None:
        return ParsedRequest(None, "", "", is_valid=False, error_message="Empty request")

    text = raw_line.strip()

    if text == "":
        return ParsedRequest(None, "", raw_line, is_valid=False, error_message="Empty request")

    parts = text.split(" ", 1)
    command = parts[0].strip().upper()
    parameter = parts[1].strip() if len(parts) > 1 else ""

    return ParsedRequest(command, parameter, text, is_valid=True)


def build_status_line(status):
    """Return the status line with terminator, e.g. '200 OK\\r\\n'."""
    return f"{status}{TERMINATOR}"


def build_response(status, data_lines=None):

    response = build_status_line(status)
    if data_lines:
        for line in data_lines:
            response += f"{line}{TERMINATOR}"
    return response


def format_song_line(song):
    """Format one song dict as a pipe-delimited data line used by LIST/SEARCH."""
    return (
        f"{song['id']}|{song['title']}|{song['artist']}|"
        f"{song['album']}|{song['genre']}|{song['duration']}"
    )


def format_song_info(song):
    """Format one song dict as multi-line INFO response data."""
    return [
        f"ID: {song['id']}",
        f"TITLE: {song['title']}",
        f"ARTIST: {song['artist']}",
        f"ALBUM: {song['album']}",
        f"GENRE: {song['genre']}",
        f"DURATION: {song['duration']}",
        f"FILE: {song['file']}",
    ]
