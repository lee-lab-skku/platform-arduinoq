# SPDX-FileCopyrightText: 2026 Advanced Additive Manufacturing Systems Laboratory, Sungkyunkwan University
# SPDX-License-Identifier: Apache-2.0


import importlib.util
import os
import re

from platformio.exception import UserSideException
from platformio.public import PlatformBase, get_systype

# Helper modules are loaded by path rather than by import. Adding the platform
# directory to sys.path would publish this file as the module "platform" and
# shadow the standard library module of the same name.
HOST_MODULE_DIR = "host"
LAYOUT_MODULE = ("builder", "arduinoq_common", "arduino_zephyr_layout.py")
LLEXT_GDB_SCRIPT = ("host", "gdb", "llext.gdb")

# Helper modules already loaded, keyed by absolute path. Module level rather
# than per instance: the modules hold no state, loading one twice is pure
# waste, and PlatformBase offers no __init__ hook to hang a cache on.
_LOADED_MODULES = {}

# PlatformIO's stock GDB start-up script, less two lines.
#
# "monitor init" is gone. The server this platform starts has already run
# init, and running it again halts the target a second time -- which is where
# the two consecutive "halted due to debug-request" came from.
#
# "$INIT_BREAK" is gone because it is evaluated here, while only the resident
# firmware's symbols are loaded -- so its default of "tbreak main" resolves
# against the resident firmware and stops the run to llext_bootstrap short.
# Dropping it also means a project no longer has to blank debug_init_break; a
# session stops in a defined place regardless, and another initial breakpoint
# belongs in debug_extra_cmds, which is evaluated once the sketch's symbols
# are in place.
DEBUG_INIT_CMDS = (
    "define pio_reset_halt_target",
    "monitor reset halt",
    "end",
    "define pio_reset_run_target",
    "monitor reset",
    "end",
    "target extended-remote $DEBUG_PORT",
    "$LOAD_CMDS",
    "pio_reset_halt_target",
)

class ArduinoqPlatform(PlatformBase):
    def is_embedded(self):
        # PlatformBase derives this from the presence of a package declared
        # with type "uploader", which PlatformIO then force-installs for any
        # target whose name contains "upload" -- ignoring "optional".
        #
        # PlatformIO reads this for the linker "cyclic reference" workaround
        # (--start-group/--end-group), IDE target listing, and unit-test and
        # debug session behaviour.
        return True

    def configure_default_packages(self, variables, targets):
        """Host systype is used in every package asset name as a token.
        platform.json pins the default assets; every other supported host is the
        same URL with this token swapped, so package versions live in exactly one place.
        """
        DEFAULT_SYSTYPE = "linux_x86_64"
        SUPPORTED_SYSTYPES = ("linux_x86_64", "linux_aarch64")

        systype = get_systype()
        if systype not in SUPPORTED_SYSTYPES:
            raise UserSideException(
                "The '%s' platform does not support the '%s' host. Every "
                "package it installs is a Linux build; supported hosts are "
                "%s. Note that the board is flashed from the Linux MPU "
                "either way, so a non-Linux workstation can still drive this "
                "platform through remote command with '-r' option, which builds on MPU."
                % (
                    self.name,
                    systype,
                    ", ".join(sorted(SUPPORTED_SYSTYPES)),
                )
            )

        if systype != DEFAULT_SYSTYPE:
            for opts in self.packages.values():
                if DEFAULT_SYSTYPE in opts.get("version", ""):
                    opts["version"] = opts["version"].replace(DEFAULT_SYSTYPE, systype)

        return super().configure_default_packages(variables, targets)

    # -----------------------------------------------------------------------
    # Host-side services
    #
    # Anything a project may need to do to the board outside a build is
    # reached through these, so that the board's wiring stays described in
    # one place. Both are plain methods on the platform instance, which
    # PlatformIO hands to a custom test runner as ".platform".
    # -----------------------------------------------------------------------

    def _resolve_path(self, *relative_parts):
        return os.path.join(self.get_dir(), *relative_parts)

    def _load_module(self, *relative_parts):
        path = self._resolve_path(*relative_parts)
        if path not in _LOADED_MODULES:
            stem, _ = os.path.splitext("_".join(relative_parts))
            spec = importlib.util.spec_from_file_location(
                "%s_%s" % (self.name, stem), path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _LOADED_MODULES[path] = module
        return _LOADED_MODULES[path]

    def _load_host_module(self, name):
        return self._load_module(HOST_MODULE_DIR, "%s.py" % name)

    def get_board_control(self, board_id):
        """Board operations driven through OpenOCD (reset, halt, ...).

        Usable from a project as
        ``env.PioPlatform().get_board_control(board_id).reset()``, or from a
        custom test runner through ``self.platform``.
        """
        board_control = self._load_host_module("board_control")
        return board_control.BoardControl.from_board_config(
            self.board_config(board_id)
        )

    def configure_debug_session(self, debug_config):
        """Point PlatformIO's debug session at the board's own OpenOCD.

        PlatformBase raises NotImplementedError here, which DebugConfigBase
        swallows, so without this the session would start with no server at
        all. The server is described here rather than in the board manifest
        so that it resolves the OpenOCD installation exactly as uploads and
        resets do, instead of repeating the path a third time.
        """
        env_options = debug_config.env_options
        # The project supplied its own server, or turned it off entirely.
        if "debug_server" in env_options or debug_config.server is None:
            return

        control = self.get_board_control(debug_config.board_config.id)
        debug_config.server.update(
            cwd=control.openocd_dir,
            executable=control.openocd_binary,
            arguments=control.server_arguments(
                gdb_port=self._gdb_port(debug_config)
            ),
        )

        self._add_debug_commands(debug_config)

        if not env_options.get("debug_load_cmds"):
            # "preload" is PlatformIO's way of saying "the platform loads the
            # firmware, not GDB": it runs the "upload" target before the
            # session and then clears the load commands, so GDB never issues
            # one. That is the only workable arrangement here, because what
            # gets flashed is the packed image while the ELF GDB opens is a
            # relocatable object the LLEXT loader places at run time.
            debug_config.load_cmds = ["preload"]

    @staticmethod
    def _gdb_port(debug_config):
        """The TCP port to tell OpenOCD about, when there is one at all.

        With an OpenOCD server, a GDB client and no port configured,
        PlatformIO does not open a socket: it runs the server as a pipe
        command for GDB and passes "gdb_port pipe" itself. Naming a port in
        that case would override the pipe and break the connection outright.

        A configured debug_port is exactly what turns that off, so the port is
        only worth stating when the project asked for one. It is still checked
        for being a bare number, since it may instead address a server this
        platform does not start.
        """
        configured = debug_config.env_options.get(
            "debug_port"
        ) or debug_config.tool_settings.get("port")
        if not configured:
            return None
        match = re.match(r"^:?(\d+)$", str(configured))
        return int(match.group(1)) if match else None

    def _add_debug_commands(self, debug_config):
        """Prepare the session for placing the sketch's symbols.

        The ELF PlatformIO hands to GDB is a relocatable object, so nothing in
        it sits where it will actually run. What is needed to fix that lives
        in the resident firmware: the "struct llext" type and the llext_load
        call whose out-parameter names the regions the loader allocated. Both
        are loaded here, together with the helper that reads them.

        Appended to the tool's own extra commands rather than replacing them,
        and PlatformIO concatenates the project's debug_extra_cmds after these
        in any case.
        """
        layout = self._load_module(*LAYOUT_MODULE).resolve(
            self, debug_config.board_config
        )

        if not debug_config.tool_settings.get("init_cmds"):
            debug_config.tool_settings["init_cmds"] = list(DEBUG_INIT_CMDS)

        commands = [
            # A safety net only, now that the sketch's symbols stay loaded
            # throughout. It does not help an IDE: MI's -break-insert ignores
            # this setting and fails outright unless it is given -f.
            "set breakpoint pending on",
            # The resident firmware is built with its paths rewritten relative
            # to the tree it came from. Only the part of that tree the
            # framework package ships can be pointed at; Zephyr's own sources
            # are not on the board at all, so those frames stay source-less.
            "set substitute-path ./ArduinoCore-zephyr %s" % layout.framework_dir,
            "source %s" % self._resolve_path(*LLEXT_GDB_SCRIPT),
            # Only the resident firmware for now: it is what runs until the
            # extension is started, and the sketch's own symbols would be at
            # addresses nothing occupies yet.
            #
            # Absolute: this is fed to GDB verbatim, with no shell to expand
            # a "~" along the way.
            "symbol-file %s" % layout.resident_elf,
            # Run to the extension and place its symbols here, while the init
            # script still has control. Everything an IDE does happens after
            # this file finishes, so by then the sketch's symbols are already
            # where they will stay -- which is the only arrangement that works
            # for it. Resolving breakpoints later is not enough: GDB resolves
            # a location once and then tries to insert it at that address on
            # the next resume, and an address the loader has not chosen yet
            # cannot be written, which aborts the resume outright.
            #
            # llext_bootstrap rather than llext_load: the loader reaches it
            # with the extension already loaded and named by its first
            # argument, so nothing has to be finished to see the result.
            "break llext_bootstrap",
            # Remembered so the helper can drop it before discarding the
            # symbol table it belongs to.
            "set $_aq_llext_bp = $bpnum",
            "continue",
            # $PROG_PATH is substituted by PlatformIO before GDB sees it.
            "arduinoq_loaded_sketch_symbols $PROG_PATH",
            # Left defined so the placement can be repeated by hand from any
            # stop where the extension is in scope.
            "define arduinoq_sketch",
            "arduinoq_loaded_sketch_symbols $PROG_PATH",
            "end",
            "echo \\n[arduinoq] stopped in the loader, with the sketch's "
            "symbols in place.\\n",
        ]
        debug_config.tool_settings["extra_cmds"] = (
            list(debug_config.tool_settings.get("extra_cmds") or []) + commands
        )

    def get_test_output_reader(self, test_runner):
        """Reader that collects unit-test output from this board.

        A project's test_custom_runner.py is expected to ask the platform for
        this instead of instantiating a reader itself; platforms that do not
        provide the method fall back to PlatformIO's serial reader.
        """
        board_id = test_runner.project_config.get(
            "env:%s" % test_runner.test_suite.env_name, "board"
        )
        test_reader = self._load_host_module("test_reader")
        return test_reader.ArduinoqTestOutputReader(
            test_runner,
            board_control=self.get_board_control(board_id),
            board_config=self.board_config(board_id),
        )
