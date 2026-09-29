# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

"""Recycle the Router's MCU connection while OpenOCD holds the MCU halted."""

import os
from pathlib import Path
import socket
import sys
import time


RPC_TIMEOUT = 5.0
OPEN_SETTLE_SECONDS = 1.0
MAX_RESPONSE_BYTES = 4096


class RouterError(Exception):
    pass


def openocd_arguments(python):
    """Load reset coordination before init, also in the unfiltered GDB server.

    Hex-encoded Tcl words preserve paths without embedded quotes, which Core
    can otherwise break when flattening debugger arguments into a shell string.
    """
    script = Path(__file__).resolve()
    words = ["[binary format H* %s]" % str(p).encode().hex() for p in (python, script)]
    return [
        "-c", "set arduinoq_router_command [list %s]" % " ".join(words),
        "-f", str(script.with_name("openocd_router.tcl")),
    ]


def _string(value):
    data = value.encode("utf-8")
    if len(data) > 65535:
        raise RouterError("Router serial port name is too long")
    return b"\xda" + len(data).to_bytes(2, "big") + data


class _Response:
    """Bounded MessagePack reader for control replies, using only the stdlib.

    PlatformIO does not depend on msgpack. Only the scalar/array types used by
    Router control results and errors are accepted; this is not an RPC router.
    A single deadline and byte budget also bound fragmented or malformed replies.
    """

    def __init__(self, connection, deadline):
        self.connection = connection
        self.deadline = deadline
        self.remaining = MAX_RESPONSE_BYTES

    def read(self, size):
        if size > self.remaining:
            raise RouterError("Router response exceeds size limit")
        self.remaining -= size
        result = bytearray()
        while len(result) < size:
            timeout = self.deadline - time.monotonic()
            if timeout <= 0:
                raise RouterError("Router RPC timed out")
            self.connection.settimeout(timeout)
            data = self.connection.recv(size - len(result))
            if not data:
                raise RouterError("Router closed the control connection")
            result.extend(data)
        return bytes(result)

    def value(self, depth=0):
        if depth > 8:
            raise RouterError("Router response exceeds nesting limit")
        code = self.read(1)[0]
        if code < 128:
            return code
        if code >= 224:
            return code - 256
        if code == 192:
            return None
        if code in (194, 195):
            return code == 195
        if 204 <= code <= 211:
            size = 1 << ((code - 204) % 4)
            return int.from_bytes(self.read(size), "big", signed=code >= 208)
        if 160 <= code <= 191:
            return self.read(code - 160).decode("utf-8")
        if code in (217, 218, 219):
            size = int.from_bytes(self.read(1 << (code - 217)), "big")
            return self.read(size).decode("utf-8")
        if 144 <= code <= 159 or code in (220, 221):
            size = code - 144 if code < 160 else int.from_bytes(self.read(2 if code == 220 else 4), "big")
            if size > self.remaining:
                raise RouterError("Router response array exceeds size limit")
            return [self.value(depth + 1) for _ in range(size)]
        raise RouterError("Unsupported Router response type: 0x%02x" % code)


def _call(connection, request_id, method, port):
    deadline = time.monotonic() + RPC_TIMEOUT
    connection.settimeout(RPC_TIMEOUT)
    # [REQUEST, id, method, [port]]; IDs are private to this short-lived client.
    connection.sendall(b"\x94\x00" + bytes([request_id]) + _string(method) + b"\x91" + _string(port))
    response = _Response(connection, deadline).value()
    if not isinstance(response, list) or len(response) != 4 or response[:2] != [1, request_id]:
        raise RouterError("Unexpected Router response to %s: %r" % (method, response))
    if response[2] is not None or response[3] is not True:
        raise RouterError("Router rejected %s: %r" % (method, response[2:]))


def wait_until_ready():
    """Reserved readiness barrier; currently only an unverified fixed delay.

    Router 0.10.0 acknowledges open before opening the UART. Replace this
    delay when an actual readiness acknowledgement is available. It must stay
    after open and before OpenOCD resumes the MCU, regardless of boot mode.
    """
    time.sleep(OPEN_SETTLE_SECONDS)


def reconnect():
    """Close, reopen, then wait while the caller keeps the MCU halted.

    Failure propagates so the reset coordinator does not resume the target.
    No Router restart, GPIO readiness change, or monitor disconnection is made.
    """
    path = os.environ.get("ARDUINO_ROUTER_SOCKET", "/var/run/arduino-router.sock")
    port = os.environ.get("ARDUINOQ_ROUTER_SERIAL_PORT", "/dev/ttyHS1")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(RPC_TIMEOUT)
            connection.connect(path)
            _call(connection, 1, "$/serial/close", port)
            _call(connection, 2, "$/serial/open", port)
        wait_until_ready()
    except (OSError, UnicodeError) as exc:
        raise RouterError("Router reconnect via %s (%s) failed: %s" % (path, port, exc)) from exc


if __name__ == "__main__":
    try:
        reconnect()
    except RouterError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        sys.exit(1)
