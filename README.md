# Tesla Powerwall UPS Bridge

<p align="center">
  <img src="logo.svg" alt="Tesla Powerwall UPS Bridge Logo" width="200"/>
</p>

<p align="center">
  <a href="https://github.com/darthbert/tesla-ups/actions/workflows/test.yml">
    <img src="https://github.com/darthbert/tesla-ups/actions/workflows/test.yml/badge.svg" alt="Tests">
  </a>
  <a href="https://codecov.io/gh/darthbert/tesla-ups">
    <img src="https://codecov.io/gh/darthbert/tesla-ups/branch/main/graph/badge.svg" alt="Coverage">
  </a>
</p>

This project monitors a Tesla Powerwall through a local proxy and reports grid outages to a Network UPS Tools (NUT) server. When a Powerwall outage is detected, it writes NUT-compatible UPS status data and can send a notification email.

## Scope

- Poll the Powerwall proxy API for battery and grid state
- Write a NUT UPS status file at `/var/lib/nut/ups/powerwall.dev`
- Detect grid outages and low battery conditions
- Send email notifications when an outage begins
- Provide a small FastAPI dashboard and JSON status endpoint

## Architecture (Bridge)

- `pypowerwall` container: fetches Powerwall data from the home energy system
- `nut-upsd` container (optional): exposes NUT UPS state via legacy NUT server (only needed for advanced features)
- `powerwall-bridge` container: polls the Powerwall API, runs native NUT server (optional), and sends notifications

### Deployment Options

- **Option A: Native NUT Server (Simplified, Recommended)**

  ```text
  Powerwall -> pypowerwall proxy -> powerwall-bridge [NUT native protocol]
                        \-> dashboard / API
  ```

  - Set `REPORTING_MODE=nut` (default)
  - No `nut-upsd` container required
  - NUT clients connect directly to bridge on port 3493

- **Option B: Legacy NUT Server (Full NUT Features)**

  ```text
  Powerwall -> pypowerwall proxy -> powerwall-bridge -> NUT status file -> nut-upsd
                        \-> dashboard / API
  ```

  - Keep `nut-upsd` container with `dummy-ups` driver
  - Use if you need authentication, SSL, event scripts (`upssched`), or multiple UPS devices

## Files

- `bridge.py` - main FastAPI application and NUT bridge logic
- `providers/` - battery provider package (abstract interface + implementations)
- `nut-snmp/` - SNMP agent for Synology DSM UPS monitoring
- `nut-config-example/` - example NUT configuration files
- `Dockerfile` - container image definition for the bridge service
- `docker-compose.yml` / `portainer-stack.yml` - Docker Compose stack for local/Portainer deployment
- `requirements.txt` - runtime Python dependencies
- `homeassistant/` - Home Assistant custom component for real-time sensor integration

## Home Assistant Integration

A dedicated Home Assistant custom component is included in the `homeassistant/` directory. It provides:

- **Real-time sensors** via Server-Sent Events (SSE)
- **Battery charge percentage** sensor
- **UPS status** sensor (OL/OB/OB LB)
- **Grid state** sensor (connected/down)
- **Binary sensors** for on-battery and low-battery alerts
- **Automatic fallback** to polling if SSE fails

**Installation:**

```bash
# Copy the integration to Home Assistant
cp -r homeassistant/tesla_ups /config/custom_components/
```

See [homeassistant/README.md](homeassistant/README.md) for detailed installation and configuration instructions.

- `requirements-dev.txt` - developer/test dependencies
- `tests/` - unit and integration tests

## Dependencies

- Docker
- Docker Compose
- Python 3.11 (for local development and tests)

## Environment

The bridge service supports these environment variables:

### SMTP / Email Notifications

- `SMTP_SERVER` - SMTP host for email notifications (e.g., `smtp.gmail.com`)
- `SMTP_PORT` - SMTP port (default: `587`)
- `EMAIL_USER` - SMTP login user (your email address)
- `EMAIL_PASS` - SMTP password or [App Password](https://myaccount.google.com/apppasswords) (requires 2-Step Verification on Google account)
- `NOTIFY_TO` - Notification recipient email or phone gateway address

### Alert Thresholds

- `BATTERY_WARNING` - Battery warning level in percent (default: `30.0`). Sends alert when battery drops to this level while on grid power.
- `BATTERY_THRESHOLD` - Battery critical/shutdown level in percent (default: `15.0`). Sends alert and shutdown signal when battery drops to this level while on grid power.

**Alert Behavior:**
- **Grid Offline**: Sends alert when grid goes offline (includes current battery status)
- **Grid Restored**: Sends alert when grid comes back online (includes current battery status)
- **Battery Warning**: Sends alert when battery reaches `BATTERY_WARNING` level (default: 30%)
- **Battery Critical**: Sends alert and NUT shutdown signal when battery reaches `BATTERY_THRESHOLD` level (default: 15%)

### General Settings

- `DEFAULT_LANGUAGE` - Interface language (`en`, `haw`, `it`, `nv`, default: `en`)
- `POLL_INTERVAL` - Polling interval in seconds (default: `15`)

### Port Configuration

All service ports can be customized via environment variables:

- `PW_PORT` - PyPowerwall web UI port (default: `8675`)
- `NUT_PORT` - NUT UPS daemon port (default: `3493`)
- `BRIDGE_PORT` - Tesla UPS Bridge dashboard port (default: `8100`)
- `SNMP_PORT` - SNMP agent port for Synology DSM (default: `161`)
- `NUT_SERVER_PORT` - Native NUT protocol server port (default: `3493`, used when `REPORTING_MODE=nut`)

### NUT Server Configuration

When using `REPORTING_MODE=nut` (native NUT protocol), these environment variables configure the NUT server:

- `NUT_UPS_NAME` - UPS device name (default: `ups`). Some NUT clients (e.g., Synology DSM) require specific names like `ups`.
- `NUT_USERNAME` - NUT authentication username (default: `monuser`)
- `NUT_PASSWORD` - NUT authentication password (default: `secret`)

Example using custom ports:

```bash
PW_PORT=8080
NUT_PORT=3494
BRIDGE_PORT=9000
SNMP_PORT=161
NUT_SERVER_PORT=3493
```

### Reporting Modes

The bridge supports three mutually exclusive reporting modes via the `REPORTING_MODE` environment variable:

- **`nut`** (default) - Run native NUT protocol server only. Direct NUT client connections without separate container.
- **`snmp`** - Run SNMP agent only. For Synology DSM and other SNMP-based monitoring.
- **`upsd`** - Write NUT files for external `nut-upsd` container only. Use this if you need legacy NUT server features (authentication, SSL, event scripts) that the native server doesn't provide.

```bash
# For NUT-only environments (native protocol server, default)
# Direct NUT connections on port 3493, no separate container needed
REPORTING_MODE=nut

# For Synology DSM UPS monitoring (SNMP only)
# Note: SNMP does NOT require the nut-upsd container at all
REPORTING_MODE=snmp

# For external nut-upsd container (legacy compatibility)
# Writes NUT files only - nut-upsd provides the NUT protocol server
REPORTING_MODE=upsd
```

**Note on `nut-upsd`:** The separate `nut-upsd` container is only needed if you specifically require its advanced features (authentication, SSL, event scripts). Both SNMP and native NUT protocol work directly from the bridge without it.

### Email Authentication

**Gmail requires App Passwords** (Google disabled "Less Secure Apps"):

1. Enable [2-Step Verification](https://myaccount.google.com/signinoptions/two-step-verification) on your Google account
2. Generate an [App Password](https://myaccount.google.com/apppasswords) (16-character code)
3. Use the App Password in `EMAIL_PASS`:

```bash
EMAIL_USER=your.email@gmail.com
EMAIL_PASS=xxxx xxxx xxxx xxxx  # 16-char app password
```

For other email providers, use your regular SMTP password.

## Internationalization

The dashboard and email alerts support multiple languages:

- **English** (`en`) - Default
- **Hawaiian** (`haw`) - ʻŌlelo Hawaiʻi
- **Italian** (`it`)
- **Navajo** (`nv`) - Diné Bizaad

Access the dashboard in any supported language:

```text
http://bridge-host:8100/?lang=it
http://bridge-host:8100/?lang=haw
http://bridge-host:8100/?lang=nv
```

Or set your browser's preferred language. The bridge also respects the `Accept-Language` HTTP header for automatic language detection.

## SNMP Support for Synology DSM

The bridge includes a built-in SNMP agent for Synology NAS UPS monitoring integration. This allows DSM to display Powerwall battery status directly in the UPS widget.

### Architecture (SNMP)

```text
Powerwall -> pypowerwall -> powerwall-bridge (SNMP agent) -> Synology DSM
                              ↓
                         NUT status file
```

### Configuration

Set these environment variables in your `.env` file:

- `SNMP_PORT` - SNMP port (default: `161`)
- `SNMP_COMMUNITY` - SNMP community string (default: `public`)
- `NUT_HOST` - NUT server hostname (default: `nut-upsd`)
- `NUT_PORT` - NUT server port (default: `3493`)
- `NUT_USER` - NUT username (default: `admin`)
- `NUT_PASS` - NUT password (default: `admin`)

### Synology DSM Setup

1. **Control Panel → Hardware & Power → UPS**
2. Select **SNMP UPS** as UPS type
3. Configure:
   - **IP address:** Your Docker host IP (e.g., `192.168.1.34`)
   - **Port:** `161` (or your custom `SNMP_PORT`)
   - **SNMP MIB:** `auto` or `ietf` (RFC 1628 standard MIB)
   - **SNMP version:** `v2c`
   - **Community:** `public` (or your custom `SNMP_COMMUNITY`)

4. Save and the UPS widget will display Powerwall status

**Troubleshooting:**

- If you get "Cannot connect to the network", check that:
  - The bridge container is running: `docker ps | grep powerwall-bridge`
  - Port 161 is not blocked by firewall
  - You're using the Docker **host** IP, not container IP

### Security Note

The SNMP agent uses read-only community strings. For production, change `SNMP_COMMUNITY` from the default `public` and restrict access via firewall rules.

## Provider Configuration

Providers are configured via environment variables. The bridge supports multiple Powerwalls via numbered provider variables.

### Single Provider (Legacy)

For a single Powerwall:

```bash
PROXY_URL=http://pypowerwall:8675
PROVIDER_TIMEOUT=10
```

### Multi-Provider Configuration

For multiple Powerwalls, use numbered environment variables:

```bash
# Provider 1 (Main House)
PROVIDER_1_TYPE=powerwall
PROVIDER_1_PROXY_URL=http://pypowerwall:8675
PROVIDER_1_TIMEOUT=10
PROVIDER_1_NAME=Main House

# Provider 2 (Guest House)
PROVIDER_2_TYPE=powerwall
PROVIDER_2_PROXY_URL=http://pypowerwall2:8675
PROVIDER_2_TIMEOUT=10
PROVIDER_2_NAME=Guest House
```

- **`PROVIDER_N_TYPE`** — provider type (`powerwall` is the only built-in type)
- **`PROVIDER_N_PROXY_URL`** — base URL of the pypowerwall proxy (e.g., `http://pypowerwall:8675`)
- **`PROVIDER_N_TIMEOUT`** — connection timeout in seconds (default: `10`)
- **`PROVIDER_N_NAME`** — optional custom name for display

At startup the bridge loads all configured providers, instantiates them, and runs health checks. A failed health check logs a warning but does not abort startup.

### Writing a custom provider

1. Create `providers/myprovider.py` and implement the `BatteryProvider` ABC:

   ```python
   from providers.base import BatteryProvider, BatteryStatus

   class MyProvider(BatteryProvider):
       def __init__(self, base_url: str, timeout: int = 5) -> None:
           self._base_url = base_url
           self._timeout = timeout

       @property
       def provider_name(self) -> str:
           return "My Battery System"

       def fetch_status(self) -> BatteryStatus:
           # call your system's API and return a BatteryStatus
           ...
   ```

2. Register it in `providers/__init__.py` by adding an entry to `_PROVIDER_CLASS_MAP`:

   ```python
   _PROVIDER_CLASS_MAP = {
       "powerwall": ("providers.powerwall", "PowerwallProvider"),
       "myprovider": ("providers.myprovider", "MyProvider"),
   }
   ```

3. Configure via environment variables:

   ```bash
   PROVIDER_1_TYPE=myprovider
   PROVIDER_1_PROXY_URL=http://mybattery:1234
   ```

## Docker Deployment

### Option 1: Pre-built Image (Recommended)

Use the pre-built Docker Hub image:

```bash
# 1. Download example files
curl -O https://raw.githubusercontent.com/darthbert/tesla-ups/main/docker-compose.hub.yml
mv docker-compose.hub.yml docker-compose.yml

# 2. Configure
cp .env.example .env
nano .env  # Edit your credentials

# 3. Run
docker compose up -d
```

### Option 2: Build Locally

```bash
git clone https://github.com/darthbert/tesla-ups.git
cd tesla-ups
cp .env.example .env
nano .env
docker compose up -d --build
```

### Publishing to Docker Hub

Set up GitHub Actions secrets (`DOCKER_USERNAME`, `DOCKER_PASSWORD`), then push tags:

```bash
git tag v1.0.0
git push origin v1.0.0
```

**Note for Forks:** GitHub Actions secrets are not inherited in forks. If you fork this repository, you must:

1. Add your own `DOCKER_USERNAME` and `DOCKER_PASSWORD` secrets in your fork's settings
2. Update `IMAGE_NAME` in `.github/workflows/docker-publish.yml` to use your Docker Hub username
3. Or build and push manually: `docker build -t yourname/tesla-ups-bridge . && docker push yourname/tesla-ups-bridge`

## Usage

Build and start the stack:

```bash
docker compose -f compose.yaml up --build
```

Or use the standard compose file:

```bash
docker compose up --build
```

The bridge dashboard will be available on `http://localhost:8100/` and the status endpoint on `http://localhost:8100/api/status`.

## Testing

### Prerequisites

- Python 3.11 or later
- A virtual environment is recommended to isolate dependencies

### Set up the test environment

Create and activate a virtual environment, then install both runtime and developer dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Run the full test suite

```bash
pytest
```

Pytest is configured via `pytest.ini`. Tests are discovered automatically from the `tests/` directory. The `-v` flag is always on so each test name is printed, and `--tb=short` keeps tracebacks concise.

### Run a specific test file

```bash
pytest tests/test_bridge.py
pytest tests/test_api.py
```

### Run tests by marker

Tests are marked as either `unit` or `integration`:

```bash
pytest -m unit
pytest -m integration
```

### Development Testing

- **Step 1: Set up the development environment**

  ```bash
  # Create virtual environment
  python3 -m venv .venv
  source .venv/bin/activate

  # Install dependencies
  pip install -r requirements.txt
  pip install -r requirements-dev.txt

  # Run all tests to verify setup
  pytest
  ```

- **Step 2: Test Mode 1 - Native NUT Protocol (Default)**

  This mode runs the built-in NUT protocol server on port 3493. No external NUT container needed.

  ```bash
  # Start the bridge in NUT mode (no Powerwall required, uses mock data)
  REPORTING_MODE=nut python bridge.py

  # In another terminal, test with netcat:
  echo -e "VER\n" | nc localhost 3493
  echo -e "LIST UPS\n" | nc localhost 3493
  echo -e "LIST VAR ups\n" | nc localhost 3493
  echo -e "GET VAR ups ups.status\n" | nc localhost 3493
  echo -e "GET VAR ups battery.charge\n" | nc localhost 3493

  # Expected responses:
  # VER: "Tesla-UPS-Bridge 1.0"
  # LIST UPS: "UPS ups"
  # GET VAR: "VAR ups ups.status OL" or "OB"
  ```

- **Step 3: Test with real NUT client (`upsc`)**

  ```bash
  # Install NUT client (if not already installed)
  # macOS: brew install nut
  # Ubuntu/Debian: sudo apt install nut-client
  # Arch: sudo pacman -S nut

  # Query the native NUT server
  upsc ups@localhost:3493
  upsc ups@localhost:3493 ups.status
  upsc ups@localhost:3493 battery.charge

  # Expected output: Current UPS status and battery percentage
  ```

- **Step 4: Test Mode 2 - SNMP Agent (Synology DSM)**

  This mode runs the SNMP agent on port 161 for Synology DSM monitoring.

  ```bash
  # Start bridge in SNMP mode
  REPORTING_MODE=snmp python bridge.py

  # Query with snmpwalk (community: public, port: 161)
  snmpwalk -v 1 -c public localhost:161 .1.3.6.1.2.1.33

  # Expected output: RFC 1628 UPS MIB OIDs with battery and status data
  ```

- **Step 5: Test Mode 3 - NUT File Output (External nut-upsd)**

  This mode writes NUT status files for an external `nut-upsd` container to consume.

  ```bash
  # Start bridge in upsd mode
  REPORTING_MODE=upsd python bridge.py

  # Check that NUT status file is being written
  cat /var/lib/nut/ups/ups.dev

  # Expected output:
  # ups.status: OL
  # battery.charge: 100

  # To test with external nut-upsd container:
  # 1. Start nut-upsd container with dummy-ups driver
  # 2. Mount the same volume as the bridge
  # 3. Query nut-upsd with upsc
  ```

- **Step 6: Test the Web Dashboard and API**

  All modes expose the web dashboard and JSON API on port 8100.

  ```bash
  # Start bridge in any mode (default is nut)
  python bridge.py

  # Test the JSON status endpoint
  curl http://localhost:8100/api/status

  # Expected output: JSON with charge, status, grid_online, providers

  # Test the web dashboard
  curl http://localhost:8100/
  # Or open in browser: http://localhost:8100/
  ```

- **Step 7: Test Atomic File Writing**

  Verify that the atomic write pattern works correctly.

  ```bash
  # Start bridge in upsd or nut mode
  REPORTING_MODE=upsd python bridge.py

  # In another terminal, monitor the NUT file
  watch -n 1 'cat /var/lib/nut/ups/powerwall.dev'

  # Verify that:
  # 1. File is always complete (never partial)
  # 2. No .tmp file remains after write
  # 3. File updates atomically (no mid-write corruption)
  ```

- **Step 8: Run Integration Tests**

  ```bash
  # Run integration tests (includes NUT server TCP tests)
  pytest -m integration

  # These tests verify:
  # - NUT server startup/shutdown
  # - TCP connection acceptance
  # - Protocol commands (VER, LIST, GET)
  ```

- **Step 9: Clean Up**

  ```bash
  # Stop the bridge (Ctrl+C in terminal)
  # Verify no processes remain
  ps aux | grep bridge.py
  ps aux | grep nut_snmp_agent.py

  # Clean up test files if needed
  rm -f /var/lib/nut/ups/ups.dev
  rm -f /var/lib/nut/ups/ups.dev.tmp
  ```

### What the tests cover

- **`tests/test_bridge.py`** — unit tests for core bridge logic:
  - `determine_status` — grid-connected, outage, and low-battery UPS status labels
  - `send_alert` — skips sending when SMTP configuration is absent
  - `write_nut_status_file` — verifies atomic file writes (temp file + rename)
  - `process_powerwall_data` — end-to-end state update, alert dispatch, and file write
- **`tests/test_api.py`** — FastAPI endpoint tests using `TestClient`:
  - `GET /api/status` — returns the current state dict as JSON
  - `GET /` — returns the HTML dashboard with expected status fields
- **`tests/test_nut_server.py`** — integration tests for native NUT protocol:
  - Server startup/shutdown
  - TCP connection acceptance
  - Protocol commands (`VER`, `LIST VAR`, etc.)
- **`tests/test_reporting_modes.py`** — unit tests for `REPORTING_MODE` configuration:
  - Mode `nut` — starts only NUT server (default)
  - Mode `snmp` — starts only SNMP agent
  - Mode `upsd` — writes NUT files for external nut-upsd only
  - Invalid mode handling

All tests use `monkeypatch` and `tmp_path` pytest fixtures; no live Powerwall or SMTP server is required.

## NUT Integration

The bridge writes UPS status to a NUT-compatible file format that can be consumed by the `dummy-ups` driver.

### NUT Configuration Files

Create these files on your host for the NUT container:

**`nut-config/ups.conf`:**

```ini
[ups]
    driver = dummy-ups
    port = /var/lib/nut/ups/ups.dev
    mode = dummy-once
    desc = "Tesla Powerwall via Bridge"
```

**`nut-config/upsd.conf`:**

```text
LISTEN 0.0.0.0 3493
MAXAGE 30
```

**`nut-config/upsd.users`:**

```text
[admin]
    password = admin
    upsmon master
```

### NUT Docker Service (Legacy Method)

The `nut-upsd` container is **optional** — the bridge now has a built-in NUT protocol server. Use this legacy approach only if you need specific NUT server features not yet implemented in the native server.

```yaml
nut-upsd:
  image: instantlinux/nut-upsd:latest
  container_name: nut-upsd
  restart: always
  privileged: true
  volumes:
    - ./nut-config:/etc/nut
    - ups_status:/var/lib/nut/ups
  environment:
    - UPS_NAME=ups
    - UPS_DRIVER=dummy-ups
  ports:
    - "3493:3493"
  depends_on:
    powerwall-bridge:
      condition: service_healthy
```

**Key points:**

- Use `dummy-ups` driver (reads from status file)
- Set `UPS_DRIVER=dummy-ups` environment variable
- Mount shared volume `ups_status` for the status file
- Use `depends_on` with `condition: service_healthy` to ensure bridge starts first

**When to use `nut-upsd` vs. native NUT server:**

| Feature | `nut-upsd` Container | Native NUT Server (`REPORTING_MODE=nut`) |
| --------- | --------------------- | ------------------------------------------ |
| **NUT Protocol** | Full implementation | Core commands only (VER, LIST, GET) |
| **Client auth** | Username/password | Username/password (monuser/secret) |
| **SSL/TLS** | Supported | Not yet implemented |
| **Event scripts** | `upssched`, `upsmon` actions | Not yet implemented |
| **Multiple UPS** | Supported | Single UPS (ups) |
| **Resource usage** | Extra container | Built into bridge |
| **Configuration** | NUT config files | Environment variables |

**Recommendation:** Use the native NUT server (`REPORTING_MODE=nut`) unless you need authentication, event scripts, or multiple UPS devices.

### Native NUT Protocol (Recommended)

The bridge now includes a native NUT protocol server. This eliminates the need for the separate `nut-upsd` container when using NUT-only environments.

**To use native NUT protocol:**

1. Set `REPORTING_MODE=nut` in your environment
2. Point NUT clients directly to the bridge container on port 3493
3. Remove the `nut-upsd` service from your Docker Compose

**Protocol Commands Supported:**

- `VER` - Server version
- `NETVER` - Protocol version
- `LIST UPS` - List available UPS devices
- `LIST VAR <ups>` - List all variables
- `GET VAR <ups> <var>` - Get specific variable (e.g., `ups.status`, `battery.charge`)
- `GET UPSDESC <ups>` - Get UPS description
- `LOGIN <ups> <username> <password>` - Authenticate (username: `monuser`, password: `secret`)

**Example:**

```bash
# Query UPS status directly from bridge
upsc ups@localhost:3493 ups.status
upsc ups@localhost:3493 battery.charge
```

**Migration from NUT container to native protocol:**

Change your Docker Compose:

```yaml
# nut-upsd is now optional - use profiles to start it only when needed
# For REPORTING_MODE=nut (default), no nut-upsd needed
# For REPORTING_MODE=upsd, start with: docker-compose --profile upsd up

# Just keep the bridge with REPORTING_MODE=nut (default):
powerwall-bridge:
  image: darthbert/tesla-ups-bridge:latest
  environment:
    - REPORTING_MODE=nut  # or snmp, or upsd
  ports:
    - "8100:8100"
    - "3493:3493"  # NUT protocol (only for REPORTING_MODE=nut)
    - "161:161/udp"  # SNMP (only for REPORTING_MODE=snmp or upsd)
```

## Health Checks

The bridge includes a Docker healthcheck:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/api/status"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 10s
```

The bridge also creates an initial NUT status file on startup so the `dummy-ups` driver can start immediately.

## Improvements and future additions

- Add NUT event handler support for graceful shutdown commands
- Add more robust retry and backoff for Powerwall API failures
- Integrate with Slack, Telegram, or SMS notification services
- Add CI automation (e.g. GitHub Actions) for tests and Docker image builds
- Add metrics / Prometheus export for outage monitoring
- Add secrets management for SMTP credentials

## License

This project is released under the MIT License.
