# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

"""Run OpenOCD with upload-specific output handling; independent of SCons."""

import argparse
import re
import subprocess
import sys
import tempfile


MARKER = "__ARDUINOQ_UPLOAD__"
EVENT = re.compile(
    r"^" + MARKER + r" (verify-begin|verify-end|write) (resident|sketch)(?: (\d+))?$"
)
LOG_LINE = re.compile(
    r"^(Error|Warn|Info|Debug|User)\s*:\s*"
    r"(?:\d+\s+\d+\s+\S+:\d+\s+\S+:\s*)?(.*)$",
    re.IGNORECASE,
)
# This is also emitted after a real verification failure. Keep it when the
# same verification reports any other error; never filter it outside that call.
VERIFY_FAILURE = re.compile(
    r"^verify failed in bank at 0x[0-9a-f]+ starting at 0x[0-9a-f]+$",
    re.IGNORECASE,
)
ERROR_TEXT = re.compile(
    r"\b(error|failed|failure|invalid command|couldn't|can't|not found|no such)\b",
    re.IGNORECASE,
)


def classify(line):
    match = LOG_LINE.match(line.strip())
    if match:
        # command_print/echo can carry an Error: message inside a User log
        # record when OpenOCD's debug formatting is enabled.
        if match[1].lower() == "user" and LOG_LINE.match(match[2]):
            return classify(match[2])
        return match[1].lower(), match[2]
    return "", line.strip()


def is_error(line):
    level, message = classify(line)
    return level == "error" or (level in ("", "user") and bool(ERROR_TEXT.search(message)))


class UploadOutput:
    def __init__(self, verbose, output, transcript):
        self.verbose = verbose
        self.output = output
        self.transcript = transcript
        self.verifying = None
        self.verification = []
        self.error_context = False
        self.hidden = False

    def emit(self, line):
        self.output.write(line)
        self.output.flush()

    def diagnostic(self, line):
        self.transcript.write(line)
        level, _ = classify(line)
        error = is_error(line)
        if level not in ("", "user"):
            self.error_context = bool(error)
        elif error:
            self.error_context = True
        if self.verbose or error or (level in ("", "user") and self.error_context):
            self.emit(line)
        else:
            self.hidden = True

    def finish_verification(self, code=None):
        # Only a complete, failed verification with no other error is the
        # expected rewrite diagnostic. Incomplete/unknown sequences stay visible.
        other_error = any(
            not VERIFY_FAILURE.fullmatch(classify(line)[1])
            and is_error(line)
            for line in self.verification
        )
        for line in self.verification:
            if code == "1" and not other_error and VERIFY_FAILURE.fullmatch(classify(line)[1]):
                continue
            self.diagnostic(line)
        self.verifying = None
        self.verification = []

    def feed(self, line):
        level, message = classify(line)
        event = EVENT.fullmatch(message) if level in ("", "user") else None
        if event:
            action, part, code = event.groups()
            if action == "verify-end" and self.verifying == part:
                self.finish_verification(code)
            else:
                self.finish_verification()
                if action == "verify-begin":
                    self.verifying = part
                elif action == "write":
                    label = "resident firmware" if part == "resident" else "sketch"
                    self.emit("Writing %s...\n" % label)
            self.error_context = False
            return
        # At -d3 OpenOCD also traces the echo command. Those traces are not
        # events and must not leak the private protocol or duplicate notices.
        if MARKER in line:
            return
        if self.verifying:
            self.verification.append(line)
        else:
            self.diagnostic(line)

    def finish(self, returncode):
        self.finish_verification()
        if returncode:
            if self.hidden:
                self.emit("OpenOCD diagnostics before failure:\n")
                self.transcript.seek(0)
                for line in self.transcript:
                    self.emit(line)
            self.emit("Error: OpenOCD exited with code %s\n" % returncode)


def run(command, verbose=False, output=None):
    output = sys.stdout if output is None else output
    with tempfile.SpooledTemporaryFile(mode="w+t", max_size=1024 * 1024) as transcript:
        filtered = UploadOutput(verbose, output, transcript)
        try:
            with subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace", bufsize=1,
            ) as process:
                try:
                    for line in process.stdout:
                        filtered.feed(line)
                    returncode = process.wait()
                except KeyboardInterrupt:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    filtered.finish(130)
                    return 130
        except OSError as exc:
            filtered.emit("Error: could not run OpenOCD: %s\n" % exc)
            return 1
        filtered.finish(returncode)
        return returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("an OpenOCD command is required")
    return run(command, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
