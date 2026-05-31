"""Native NUT network protocol server for direct UPS client communication.

Implements the NUT (Network UPS Tools) text protocol, allowing NUT clients
(upsc, upsmon, etc.) to connect directly without requiring the dummy-ups driver.

Protocol: TCP, line-based text on port 3493 (default)
Reference: https://networkupstools.org/docs/developer-guide.chunked/ap01.html
"""

import logging
import os
import socketserver
import threading
from typing import Dict, Any

logger = logging.getLogger(__name__)


class NUTProtocolHandler(socketserver.StreamRequestHandler):
    """Handler for NUT protocol commands."""

    # Protocol constants
    PROTOCOL_VERSION = "1.2"
    SERVER_VERSION = "Tesla-UPS-Bridge 1.0"
    UPS_NAME = os.getenv("NUT_UPS_NAME", "ups")
    UPS_DESC = "Tesla Powerwall via Bridge"
    AUTH_USERNAME = os.getenv("NUT_USERNAME", "monuser")
    AUTH_PASSWORD = os.getenv("NUT_PASSWORD", "secret")

    def handle(self):
        """Handle client connection."""
        client = f"{self.client_address[0]}:{self.client_address[1]}"
        logger.info("NUT client connected: %s", client)

        try:
            while True:
                line = self.rfile.readline()
                if not line:
                    break  # Client disconnected

                # Handle both bytes (raw socket) and string (TextIOWrapper)
                if isinstance(line, bytes):
                    command = line.decode('utf-8').strip()
                else:
                    command = line.strip()
                if not command:
                    continue

                self._handle_command(command)

        except ConnectionError:
            pass
        finally:
            logger.info("NUT client disconnected: %s", client)

    def _handle_command(self, command: str):
        """Parse and execute NUT command."""
        parts = command.split()
        if not parts:
            return

        cmd = parts[0].upper()
        args = parts[1:]

        handlers = {
            'VER': self._cmd_ver,
            'NETVER': self._cmd_netver,
            'LIST': self._cmd_list,
            'GET': self._cmd_get,
            'UPS': self._cmd_ups,
            'LOGIN': self._cmd_login,
            'LOGOUT': self._cmd_logout,
            'START': self._cmd_start,
            'STOP': self._cmd_stop,
        }

        handler = handlers.get(cmd, self._cmd_unknown)
        try:
            handler(args)
        except ConnectionError:
            # Client logout - not an error
            pass
        except Exception as e:
            logger.error("Error handling command '%s': %s", cmd, e)
            self._send_response(f"ERR UNKNOWN\n")

    def _send_response(self, message: str):
        """Send response to client."""
        self.wfile.write(message.encode('utf-8'))
        self.wfile.flush()

    def _get_state(self) -> Dict[str, Any]:
        """Get current UPS state from bridge module."""
        # Import here to avoid circular dependency at module load
        # Python caches imports, so we'll get the same module reference
        import bridge

        status = bridge.state.get('status', 'OL')
        soe = bridge.state.get('soe', 100.0)
        soe_int = round(soe)

        # Calculate battery runtime (rough estimate: 5% = 1 hour for Powerwall)
        runtime_minutes = soe_int * 12 if soe_int > 0 else 0

        return {
            'ups.status': status,
            'battery.charge': str(soe_int),
            'battery.runtime': str(runtime_minutes),
            'battery.type': 'LiIon',
            'ups.model': 'Tesla Powerwall',
            'ups.mfr': 'Tesla',
            'device.model': 'Tesla Powerwall',
            'device.mfr': 'Tesla',
            'device.type': 'ups',
            'ups.load': '0',
            'input.voltage': '240',
            'output.voltage': '240',
            'ups.delay.shutdown': '120',
            'ups.delay.start': '60',
        }

    # Command handlers

    def _cmd_ver(self, args):
        """VER - Return server version."""
        self._send_response(f"UPS {self.SERVER_VERSION}\n")

    def _cmd_netver(self, args):
        """NETVER - Return network protocol version."""
        self._send_response(f"Network UPS Tools {self.PROTOCOL_VERSION}\n")

    def _cmd_list(self, args):
        """LIST [UPS|VAR] <upsname> - List UPS or variables."""
        if len(args) < 1:
            self._send_response("ERR UNKNOWN\n")
            return

        subcmd = args[0].upper()

        if subcmd == 'UPS':
            # LIST UPS - List all UPS devices
            self._send_response(f"UPS {self.UPS_NAME} \"{self.UPS_DESC}\"\n")
            self._send_response("END LIST UPS\n")

        elif subcmd == 'VAR' and len(args) >= 2:
            # LIST VAR <upsname> - List all variables for a UPS
            upsname = args[1]
            if upsname != self.UPS_NAME:
                self._send_response("ERR UNKNOWN-UPS\n")
                return

            state = self._get_state()
            self._send_response(f"BEGIN LIST VAR {upsname}\n")
            for var, value in state.items():
                self._send_response(f"VAR {upsname} {var} \"{value}\"\n")
            self._send_response(f"END LIST VAR {upsname}\n")

        elif subcmd == 'RW' and len(args) >= 2:
            # LIST RW <upsname> - List read-write variables (none for now)
            upsname = args[1]
            self._send_response(f"BEGIN LIST RW {upsname}\n")
            self._send_response(f"END LIST RW {upsname}\n")

        elif subcmd == 'CMD' and len(args) >= 2:
            # LIST CMD <upsname> - List supported instant commands
            upsname = args[1]
            self._send_response(f"BEGIN LIST CMD {upsname}\n")
            # No instant commands supported
            self._send_response(f"END LIST CMD {upsname}\n")

        else:
            self._send_response("ERR UNKNOWN\n")

    def _cmd_get(self, args):
        """GET [UPSDESC|VAR] <upsname> [varname] - Get UPS description or variable."""
        if len(args) < 2:
            self._send_response("ERR UNKNOWN\n")
            return

        subcmd = args[0].upper()
        upsname = args[1]

        if upsname != self.UPS_NAME:
            self._send_response("ERR UNKNOWN-UPS\n")
            return

        if subcmd == 'UPSDESC':
            # GET UPSDESC <upsname>
            self._send_response(f"UPSDESC {upsname} \"{self.UPS_DESC}\"\n")

        elif subcmd == 'VAR' and len(args) >= 3:
            # GET VAR <upsname> <varname>
            varname = args[2]
            state = self._get_state()
            if varname in state:
                self._send_response(f"VAR {upsname} {varname} \"{state[varname]}\"\n")
            else:
                self._send_response("ERR VAR-NOT-SUPPORTED\n")

        elif subcmd == 'TYPE' and len(args) >= 3:
            # GET TYPE <upsname> <varname>
            varname = args[2]
            # All our vars are strings except battery.charge which is numeric
            if varname == 'battery.charge':
                self._send_response(f"TYPE {upsname} {varname} NUMBER\n")
            else:
                self._send_response(f"TYPE {upsname} {varname} STRING\n")

        else:
            self._send_response("ERR UNKNOWN\n")

    def _cmd_ups(self, args):
        """UPS <upsname> - Select UPS (legacy, mostly a no-op for us)."""
        if len(args) < 1:
            self._send_response("ERR UNKNOWN\n")
            return

        upsname = args[0]
        if upsname == self.UPS_NAME:
            self._send_response(f"OK\n")
        else:
            self._send_response("ERR UNKNOWN-UPS\n")

    def _cmd_login(self, args):
        """LOGIN <upsname> [username] [password] - Authenticate with credentials."""
        if len(args) < 1:
            self._send_response("ERR UNKNOWN\n")
            return

        upsname = args[0]
        if upsname != self.UPS_NAME:
            self._send_response("ERR UNKNOWN-UPS\n")
            return

        # Check credentials if provided
        if len(args) >= 2:
            username = args[1]
            password = args[2] if len(args) >= 3 else ""
            if username != self.AUTH_USERNAME or password != self.AUTH_PASSWORD:
                self._send_response("ERR ACCESS-DENIED\n")
                logger.warning("Failed login attempt for user: %s", username)
                return

        self._send_response("OK\n")
        logger.info("Successful login for user: %s", args[1] if len(args) >= 2 else "anonymous")

    def _cmd_logout(self, args):
        """LOGOUT - End session."""
        self._send_response("OK Goodbye\n")
        raise ConnectionError("Client logout")

    def _cmd_start(self, args):
        """START [TLS|SHUTDOWN] <upsname> - Start TLS or shutdown (not supported)."""
        self._send_response("ERR NOT-SUPPORTED\n")

    def _cmd_stop(self, args):
        """STOP [TLS|SHUTDOWN] <upsname> - Stop TLS or shutdown (not supported)."""
        self._send_response("ERR NOT-SUPPORTED\n")

    def _cmd_unknown(self, args):
        """Handle unknown commands."""
        self._send_response("ERR UNKNOWN\n")


class NUTServer:
    """NUT network protocol server for direct client communication."""

    def __init__(self, host: str = '0.0.0.0', port: int = 3493):
        self.host = host
        self.port = port
        self._server = None
        self._thread = None

    def start(self):
        """Start TCP server in background thread."""
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self._server = socketserver.ThreadingTCPServer(
            (self.host, self.port),
            NUTProtocolHandler
        )
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("NUT server started on %s:%d", self.host, self.port)

    def stop(self):
        """Stop the server."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            logger.info("NUT server stopped")

    def is_running(self) -> bool:
        """Check if server is running."""
        return self._server is not None and self._thread is not None and self._thread.is_alive()
