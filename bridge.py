"""UPS bridge service: polls a battery provider and writes NUT status files.

This service loads a BatteryProvider from providers.yaml, polls it on a
background thread, writes a NUT-compatible UPS status file, and optionally
sends an email alert on grid outages.
"""

import asyncio
import logging
import os
import smtplib
import threading
import time
from contextlib import asynccontextmanager
from email.mime.text import MIMEText
from typing import Any, Dict

import requests

from fastapi import FastAPI

import api
from i18n import _
from providers import BatteryProvider, BatteryStatus, load_providers
from providers import ConfigError
from nut_server import NUTServer

__version__ = "1.2.9"

# Mutable app-level state (avoids module-level global reassignment)
_app_state: Dict[str, Any] = {
    "providers": [],
    "nut_server": None,
}


def print_startup_banner():
    """Print startup banner with configuration information."""
    reporting_mode = os.getenv("REPORTING_MODE", "nut").upper()
    nut_port = os.getenv("NUT_SERVER_PORT", "3493")
    snmp_port = os.getenv("SNMP_PORT", "161")
    bridge_port = os.getenv("BRIDGE_PORT", "8100")
    status_file = os.getenv("STATUS_FILE", "/var/lib/nut/ups/powerwall.dev")
    poll_interval = os.getenv("POLL_INTERVAL", "15")

    logging.info("=" * 60)
    logging.info("Tesla Powerwall UPS Bridge v%s", __version__)
    logging.info("=" * 60)
    logging.info("Configuration:")
    logging.info("  Reporting Mode: %s", reporting_mode)
    logging.info("  Bridge Port: %s", bridge_port)
    logging.info("  NUT Server Port: %s (native mode only)", nut_port)
    logging.info("  SNMP Port: %s (SNMP mode only)", snmp_port)
    logging.info("  Status File: %s", status_file)
    logging.info("  Poll Interval: %s seconds", poll_interval)
    logging.info("  Battery Warning Level: %s%%", BATTERY_WARNING)
    logging.info("  Battery Critical Level: %s%%", BATTERY_THRESHOLD)
    logging.info("=" * 60)


@asynccontextmanager
async def lifespan(_fastapi_app: FastAPI):
    """Initialize battery providers and start the background polling thread."""
    # Print startup banner
    print_startup_banner()

    _app_state["providers"] = load_providers()

    # Start reporting services based on REPORTING_MODE
    _app_state["nut_server"] = start_reporting_services()

    threading.Thread(target=background_poller, daemon=True).start()
    yield

    # Cleanup
    if _app_state["nut_server"]:
        _app_state["nut_server"].stop()


app = FastAPI(lifespan=lifespan)

STATUS_FILE = os.getenv("STATUS_FILE", "/var/lib/nut/ups/ups.dev")
BATTERY_WARNING = float(os.getenv("BATTERY_WARNING", "30.0"))  # Warning level (%)
BATTERY_THRESHOLD = float(
    os.getenv("BATTERY_THRESHOLD", "15.0")
)  # Critical/shutdown level (%)

state: Dict[str, Any] = {
    "status": "OL",
    "soe": 0.0,
    "last_notified": "Never",
    "grid": "Unknown",
    "provider": "unknown",
    "notification_sent": False,
    "grid_offline_notified": False,  # Track if we've notified about grid going offline
    "grid_online_notified": False,  # Track if we've notified about grid coming back online
    "warning_notified": False,  # Track if we've notified about battery warning level
    "shutdown_notified": False,  # Track if we've notified about battery critical level
    "shutdown_signal_sent": False,  # Track if we've sent shutdown signal to clients
    "providers": [],  # List of individual provider statuses
}

# SSE event queue for broadcasting state updates to connected clients
sse_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

api.register(state, sse_queue)
app.include_router(api.router)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def get_env(key: str, default: str = "") -> str:
    """Read a string environment variable with an optional default."""
    return os.getenv(key, default)


def get_env_int(key: str, default: int) -> int:
    """Read an integer environment variable with a default fallback."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"Invalid integer for {key}: {value}") from exc


def load_config() -> Dict[str, Any]:
    """Load runtime configuration from environment variables."""
    return {
        "smtp_server": get_env("SMTP_SERVER", ""),
        "smtp_port": get_env_int("SMTP_PORT", 587),
        "email_user": get_env("EMAIL_USER", ""),
        "email_pass": get_env("EMAIL_PASS", ""),
        "notify_to": get_env("NOTIFY_TO", ""),
        "poll_interval": get_env_int("POLL_INTERVAL", 15),
    }


def start_reporting_services() -> NUTServer | None:
    """Start reporting services based on REPORTING_MODE environment variable.

    Modes (mutually exclusive):
        - 'nut': Run native NUT protocol server only (default)
        - 'snmp': Run SNMP agent only
        - 'upsd': Write NUT files for external nut-upsd container only

    Returns:
        NUTServer instance if started, None otherwise
    """
    mode = get_env("REPORTING_MODE", "nut").lower()
    server: NUTServer | None = None

    logger.info("Starting reporting services in mode: %s", mode)

    if mode == "nut":
        # Start native NUT protocol server only
        try:
            nut_port = get_env_int("NUT_SERVER_PORT", 3493)
            server = NUTServer(host="0.0.0.0", port=nut_port)
            server.start()
            logger.info("Native NUT server started on port %d", nut_port)
        except OSError as exc:
            logger.error("Failed to start NUT server: %s", exc)

    if mode == "snmp":
        # Start SNMP agent as subprocess (background process)
        import subprocess
        import sys

        try:
            subprocess.Popen(
                [sys.executable, "/app/nut_snmp_agent.py"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            snmp_port = get_env_int("SNMP_PORT", 161)
            logger.info("SNMP agent started on port %d", snmp_port)
        except OSError as exc:
            logger.error("Failed to start SNMP agent: %s", exc)

    if mode == "upsd":
        # In upsd mode, only write NUT files for external nut-upsd container
        # No SNMP, no native NUT server - just file output
        try:
            write_nut_status_file("OL", 100.0)
            logger.info(
                "Created initial NUT status file for upsd mode: %s", STATUS_FILE
            )
        except OSError as exc:
            logger.warning("Failed to create initial NUT status file: %s", exc)

    if mode not in ("nut", "snmp", "upsd"):
        logger.warning("Unknown REPORTING_MODE '%s', using 'nut'", mode)
        # Fall back to nut (native NUT protocol)
        return start_reporting_services_for_mode("nut")

    return server


def start_reporting_services_for_mode(mode: str) -> NUTServer | None:
    """Helper to start services for a specific mode (used for fallback)."""
    os.environ["REPORTING_MODE"] = mode
    return start_reporting_services()


def send_alert(message: str, config: Dict[str, Any], lang: str = "en") -> bool:
    """Send an email alert using SMTP settings from configuration."""
    if not config["smtp_server"] or not config["email_user"] or not config["notify_to"]:
        logger.warning("Missing email configuration; skipping alert: %s", message)
        return False

    if not config["email_pass"]:
        logger.warning("Missing email password; skipping alert")
        return False

    msg = MIMEText(message)
    msg["Subject"] = _("alert.subject", lang)
    msg["From"] = config["email_user"]
    msg["To"] = config["notify_to"]

    try:
        with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
            server.starttls()
            server.login(config["email_user"], config["email_pass"])
            server.send_message(msg)
        state["last_notified"] = time.strftime("%H:%M:%S")
        logger.info("Alert sent: %s", message)
        return True
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP authentication failed: %s", exc)
    except smtplib.SMTPException as exc:
        logger.warning("Failed to send email alert: %s", exc)
    except (OSError, ValueError) as exc:
        logger.warning("Unexpected error sending alert: %s", exc)
    return False


def determine_status(
    grid_connected: bool, soe: float, notified: bool
) -> tuple[str, bool]:
    """Determine the UPS status label and whether an outage notification should be sent."""
    if grid_connected:
        return "OL", False

    status = "OB LB" if soe <= BATTERY_THRESHOLD else "OB"
    should_notify = not notified
    return status, should_notify


def write_nut_status_file(status: str, soe: float) -> None:
    """Write the UPS state file atomically in NUT format for the UPS daemon to read.

    Uses temp file + atomic rename to prevent mid-write collisions.
    """
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    temp_file = f"{STATUS_FILE}.tmp"
    with open(temp_file, "w", encoding="utf-8") as handle:
        handle.write(f"ups.status: {status}\n")
        handle.write(f"battery.charge: {soe}\n")
        handle.flush()
        os.fsync(handle.fileno())  # Ensure data hits disk before rename
    os.replace(temp_file, STATUS_FILE)  # Atomic rename


def broadcast_event(event_type: str, data: Dict[str, Any]) -> None:
    """Broadcast an event to all connected SSE clients."""
    try:
        # Use asyncio.run_coroutine_threadsafe to safely add to queue from sync code
        event = {"event": event_type, "data": data, "timestamp": time.time()}
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(sse_queue.put(event), loop)
    except RuntimeError:
        # No event loop running, skip broadcast
        pass


def process_status(
    battery_status: BatteryStatus, config: Dict[str, Any], provider_name: str
) -> None:
    """Update runtime state and send notifications based on provider data."""
    prev_grid = state["grid"]
    prev_status = state["status"]

    state["soe"] = battery_status.soe
    state["grid"] = (
        "SystemGridConnected" if battery_status.grid_connected else "GridDown"
    )
    state["provider"] = provider_name

    # Get language for alerts from environment
    alert_lang = os.getenv("DEFAULT_LANGUAGE", "en")

    new_status, should_notify = determine_status(
        battery_status.grid_connected, battery_status.soe, state["notification_sent"]
    )
    if should_notify and send_alert(
        _("alert.grid_outage", alert_lang, soe=battery_status.soe), config, alert_lang
    ):
        state["notification_sent"] = True

    if battery_status.grid_connected:
        state["notification_sent"] = False

    state["status"] = new_status
    write_nut_status_file(new_status, battery_status.soe)

    # Broadcast SSE event on significant changes
    event_data = dict(state)
    event_data["grid_changed"] = prev_grid != state["grid"]
    event_data["status_changed"] = prev_status != new_status
    broadcast_event("status_update", event_data)


def poll_provider(provider: BatteryProvider) -> BatteryStatus | None:
    """Poll a single provider and return its status, or None on error."""
    try:
        return provider.fetch_status()
    except requests.RequestException as exc:
        provider_id = getattr(provider, "_bridge_id", "unknown")
        logger.warning("Provider %s network error: %s", provider_id, exc)
        return None
    except ValueError as exc:
        provider_id = getattr(provider, "_bridge_id", "unknown")
        logger.warning("Provider %s data error: %s", provider_id, exc)
        return None


def aggregate_status(
    provider_statuses: list[tuple[str, BatteryStatus | None]],
) -> tuple[str, float, str, list[dict]]:
    """Aggregate status from multiple providers.

    Returns:
        (status, min_soe, grid_state, individual_providers)
        - status: "OL" if all on grid, "OB" if any on battery, "OB LB" if any low battery
        - min_soe: lowest battery percentage across all providers
        - grid_state: "SystemGridConnected" if all on grid, "GridDown" if any on battery
        - individual_providers: list of individual provider status dicts
    """
    all_on_grid = True
    any_low_battery = False
    min_soe = 100.0
    provider_details: list[dict] = []

    for name, status in provider_statuses:
        if status is None:
            # Provider error - treat as offline
            provider_details.append(
                {
                    "name": name,
                    "status": "error",
                    "soe": 0.0,
                    "grid_connected": False,
                }
            )
            all_on_grid = False
            min_soe = min(min_soe, 0.0)
            continue

        provider_details.append(
            {
                "name": name,
                "status": "OK",
                "soe": status.soe,
                "grid_connected": status.grid_connected,
            }
        )

        if not status.grid_connected:
            all_on_grid = False

        if status.soe < BATTERY_THRESHOLD:
            any_low_battery = True

        min_soe = min(min_soe, status.soe)

    # Determine aggregate status
    if all_on_grid:
        aggregate = "OL"
        grid_state = "SystemGridConnected"
    elif any_low_battery:
        aggregate = "OB LB"
        grid_state = "GridDown"
    else:
        aggregate = "OB"
        grid_state = "GridDown"

    return aggregate, min_soe, grid_state, provider_details


def background_poller() -> None:
    """Run the battery provider poll loop for all providers in a background thread."""
    config = load_config()

    while True:
        try:
            # Poll all providers
            provider_statuses: list[tuple[str, BatteryStatus | None]] = []

            for provider in _app_state["providers"]:
                status = poll_provider(provider)
                provider_name = (
                    getattr(provider, "_bridge_name", None) or provider.provider_name
                )
                provider_id = getattr(provider, "_bridge_id", "unknown")
                display_name = f"{provider_name} ({provider_id})"
                provider_statuses.append((display_name, status))

            # Aggregate status across all providers
            _, min_soe, grid_state, provider_details = aggregate_status(
                provider_statuses
            )

            # Get previous state for change detection
            prev_grid = state["grid"]
            prev_status = state["status"]

            # Update global state
            state["soe"] = min_soe
            state["grid"] = grid_state
            state["providers"] = provider_details

            # Determine status for notifications
            any_on_battery = grid_state == "GridDown"
            new_status, _ = determine_status(
                not any_on_battery, min_soe, state["notification_sent"]
            )

            # Grid offline notification (with battery status)
            # Skip alerts if SOE is 0.0 (indicates data error, not actual battery level)
            if any_on_battery and not state["grid_offline_notified"] and min_soe > 0.0:
                alert_lang = os.getenv("DEFAULT_LANGUAGE", "en")
                if send_alert(
                    _("alert.grid_outage", alert_lang, soe=min_soe), config, alert_lang
                ):
                    state["grid_offline_notified"] = True
                    state["last_notified"] = time.strftime("%H:%M:%S")

            # Grid online notification (with battery status)
            if (
                not any_on_battery
                and state["grid_offline_notified"]
                and not state["grid_online_notified"]
                and min_soe > 0.0
            ):
                alert_lang = os.getenv("DEFAULT_LANGUAGE", "en")
                if send_alert(
                    _("alert.grid_restored", alert_lang, soe=min_soe),
                    config,
                    alert_lang,
                ):
                    state["grid_online_notified"] = True
                    state["last_notified"] = time.strftime("%H:%M:%S")

            # Reset grid notifications when grid state changes
            if not any_on_battery and state["grid_offline_notified"]:
                state["grid_offline_notified"] = False
            if any_on_battery and state["grid_online_notified"]:
                state["grid_online_notified"] = False

            # Battery warning level notification
            if (
                any_on_battery
                and min_soe <= BATTERY_WARNING
                and not state["warning_notified"]
                and min_soe > 0.0
            ):
                alert_lang = os.getenv("DEFAULT_LANGUAGE", "en")
                if send_alert(
                    _("alert.battery_warning", alert_lang, soe=min_soe),
                    config,
                    alert_lang,
                ):
                    state["warning_notified"] = True
                    state["last_notified"] = time.strftime("%H:%M:%S")

            # Battery critical level notification and shutdown signal
            if (
                any_on_battery
                and min_soe <= BATTERY_THRESHOLD
                and not state["shutdown_notified"]
                and min_soe > 0.0
            ):
                alert_lang = os.getenv("DEFAULT_LANGUAGE", "en")
                if send_alert(
                    _("alert.battery_critical", alert_lang, soe=min_soe),
                    config,
                    alert_lang,
                ):
                    state["shutdown_notified"] = True
                    state["last_notified"] = time.strftime("%H:%M:%S")

                # Send shutdown signal to NUT clients
                if not state["shutdown_signal_sent"]:
                    logger.warning(
                        "Battery at critical level (%.1f%%), sending shutdown signal",
                        min_soe,
                    )
                    # Update NUT status to indicate imminent shutdown
                    write_nut_status_file("OB LB FSD", min_soe)  # FSD = Forced Shutdown
                    state["shutdown_signal_sent"] = True

            # Reset battery notifications when grid is restored
            if not any_on_battery:
                state["warning_notified"] = False
                state["shutdown_notified"] = False
                state["shutdown_signal_sent"] = False

            state["status"] = new_status

            # Write aggregate status to NUT file
            write_nut_status_file(new_status, min_soe)

            # Broadcast SSE event on significant changes
            event_data = dict(state)
            event_data["grid_changed"] = prev_grid != grid_state
            event_data["status_changed"] = prev_status != new_status
            broadcast_event("status_update", event_data)

        except (OSError, ValueError, RuntimeError) as exc:
            logger.error("Error in background poller: %s", exc)

        time.sleep(config["poll_interval"])



if __name__ == "__main__":
    import uvicorn
    import os

    port = int(os.getenv("BRIDGE_PORT", "8100"))
    uvicorn.run(app, host="0.0.0.0", port=port)
