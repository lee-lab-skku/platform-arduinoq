# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0

#
# Test output reader for this board.
#
# PlatformIO offers no way for a development platform to register a test
# runner: TestRunnerFactory only ever loads <test_dir>/test_custom_runner.py
# from the project. A project runner can still delegate here, because
# TestRunnerBase keeps the platform for its environment as .platform; README
# shows the delegating runner.
#
# What belongs on which side: how the board is reached and reset is platform
# knowledge and lives here; how a line of test output is parsed belongs to
# whatever produced it, and stays in the project's runner.

import click
import serial

from platformio.test.exception import UnitTestSuiteError
from platformio.test.runners.readers.serial import SerialTestOutputReader

# The sketch's Serial is provided by RouterBridge and surfaces on the MPU as
# a TCP socket rather than a UART, so there is no port for PlatformIO's
# SerialPortFinder to discover. This is the platform's default; a project can
# still override it with "test_port", and a board manifest with "test.port".
DEFAULT_TEST_PORT = "socket://localhost:7500"


class ArduinoqTestOutputReader(SerialTestOutputReader):
    # How long the board may stay silent before the run is called stalled.
    #
    # The inherited SERIAL_TIMEOUT is a read() timeout that nothing acts on:
    # when it expires read() returns b"", which the base loop hands to the
    # output handler and then blocks on again, forever. Over a real UART that
    # is rarely reached; over the bridge a board that stops sending mid-suite
    # is an ordinary failure mode, and has to end the run with something the
    # caller can read.
    #
    # Sized for the gap between lines of test output rather than for a whole
    # suite, so that a long-running test case does not trip it.
    IDLE_TIMEOUT = 120

    def __init__(self, test_runner, board_control=None, board_config=None):
        super().__init__(test_runner)
        self.board_control = board_control
        self.board_config = board_config

    def resolve_test_port(self):
        """Resolve the port without going through SerialPortFinder.

        The base implementation scans USB serial devices and matches them
        against the board's hwids, which cannot produce a socket URL. The
        precedence is otherwise the usual one: the --test-port option and
        "test_port" first, then this platform's default.
        """
        port = self.test_runner.get_test_port()
        if port:
            return port
        return DEFAULT_TEST_PORT

    def begin(self):
        port = self.resolve_test_port()

        # The board has no DTR/RTS line to toggle -- the base reader's reset
        # does nothing here, and would not work over a socket URL in any case.
        # OpenOCD drives it instead, and it has to go before the connection:
        # connecting first leaves this reset cutting a frame in half under an
        # attached reader (see CONTRIBUTING.md). Nothing races the first
        # line of output, because a test build is packed for "app" startup and
        # holds in the loader until release() below.
        reset = not self.test_runner.options.no_reset and self.board_control
        if reset:
            self.board_control.reset()

        try:
            connection = serial.serial_for_url(
                port,
                baudrate=self.test_runner.get_test_speed(),
                timeout=self.IDLE_TIMEOUT,
            )
        except serial.SerialException as exc:
            click.secho(str(exc), fg="red", err=True)
            return None

        received = False
        try:
            if reset:
                self.board_control.release()

            while not self.test_runner.test_suite.is_finished():
                # in_waiting is not a byte count for a socket URL: pyserial
                # reports the length of select()'s ready list, so it is only
                # ever 0 or 1 and this is read(1) either way. The "or 1" is
                # what makes it block, though -- read(0) returns immediately,
                # which is a spin rather than a wait. Kept in the base
                # reader's shape, which is correct for a real port.
                data = connection.read(connection.in_waiting or 1)
                if not data:
                    raise UnitTestSuiteError(
                        "No test output for %d s and the suite has not "
                        "finished%s. The board stopped sending: check that "
                        "arduino-router.service is running, and that the "
                        "sketch has not blocked or reset mid-run."
                        % (
                            self.IDLE_TIMEOUT,
                            ""
                            if received
                            else " -- nothing was received at all",
                        )
                    )
                received = True
                self.test_runner.on_testing_data_output(data)
        except serial.SerialException as exc:
            # The bridge closed the connection. Distinct from silence, and
            # worth saying so: it points at the router session rather than at
            # the sketch.
            raise UnitTestSuiteError(
                "Test connection to %s closed before the suite finished (%s)."
                % (port, exc)
            ) from exc
        finally:
            connection.close()

        return None
