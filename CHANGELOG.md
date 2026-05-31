# Changelog

<!-- markdownlint-disable MD024 -->

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.4] - 2026-05-31

### Fixed

- `battery.charge` reported as `0` by the native NUT server (`upsc ups@localhost battery.charge`) even when the web dashboard showed the correct value. Root cause: the NUT protocol spec requires `battery.charge` to be an integer (0–100); the bridge was sending a Python float string (e.g. `"89.4"`), which NUT clients could not parse and silently fell back to `0`. Fixed by rounding `soe` to the nearest integer before sending it over the protocol.

## [1.2.3] - 2026-05-24

### Fixed

- Alert system now skips alerts when SOE is 0.0 (indicates data error from Powerwall API, not actual battery level)
- Startup banner now correctly displays POLL_INTERVAL from environment variable instead of hardcoded default

## [1.2.2] - 2026-05-24

### Added

- Configurable battery alert thresholds: BATTERY_WARNING (default: 30%) and BATTERY_THRESHOLD (default: 15%)
- Grid offline notification with current battery status
- Grid restored notification with current battery status
- Battery warning level alert when battery reaches BATTERY_WARNING
- Battery critical level alert and NUT shutdown signal when battery reaches BATTERY_THRESHOLD
- NUT shutdown signal mechanism (FSD status) for client systems
- Unit tests for alert threshold functionality

### Changed

- Alert behavior to include battery status in all notifications
- State tracking to prevent duplicate alerts for same event

### Documentation Updates

- Updated README with alert threshold environment variables and behavior

## [1.2.1] - 2026-05-24

### Added

- Home Assistant integration section to main README
- STATUS_FILE environment variable for configurable NUT status file location
- Comprehensive local testing instructions for all reporting modes
- .gitignore entries for IDE files, config files, and AI metadata
- Startup banner displaying version and configuration on startup
- Additional NUT variables for Synology DSM compatibility (battery.runtime, battery.type, device.model, etc.)

### Changed

- **BREAKING**: Default bridge port changed from 8000 to 8100 to avoid conflicts
- **BREAKING**: Removed 'both' reporting mode - now mutually exclusive modes: nut, snmp, upsd
- Default REPORTING_MODE changed to 'nut'
- nut-upsd container is now optional (use Docker Compose profiles)
- SNMP port corrected from 161/udp to 1161/udp in Dockerfile
- All documentation updated to reflect new port (8100) and reporting modes
- ATTRIBUTIONS.md updated to match actual dependencies
- NUT server port configurable via NUT_SERVER_PORT environment variable

### Fixed

- Permission denied errors when writing NUT status files locally
- SNMP agent default bridge API URL to use new port 8100
- Home Assistant config flow default bridge URL to use new port 8100
- Docker Compose healthcheck URLs to use new port 8100
- Dockerfile missing nut_server.py copy causing ModuleNotFoundError
- Dockerfile healthcheck port from 8000 to 8100
- NUT server LOGOUT command logging as error (now silently handled as normal disconnection)

### Removed

- Outdated SNMP tests (test_snmp.py) due to pysnmp 7.x incompatibility
- IDE and config files from git tracking (.gemini/, .vscode/, nut-config/, settings.json, *.code-workspace)
- References to 'both' reporting mode from all documentation

### Dependencies

- Pinned pysnmp to 4.x for compatibility

### Documentation Updates

- Updated README with Home Assistant integration section
- Updated all port references (8000 → 8100) across all files
- Clarified deployment options and reporting modes
- Added detailed step-by-step local testing instructions
- Updated Home Assistant documentation with new port references

## [1.1.0] - Previous Release

### Added

- Native NUT protocol server implementation
- SNMP agent for Synology DSM integration
- Server-Sent Events (SSE) endpoint for real-time updates
- Home Assistant custom component integration
- Multi-language support (English, Hawaiian, Italian, Navajo)
- Atomic file writing for NUT status files

### Changed

- Refactored reporting mode management
- Updated Docker Compose configuration
- Enhanced provider loading system

## [1.0.0] - Initial Release

### Added

- Initial Tesla Powerwall UPS Bridge implementation
- NUT status file generation
- Email alert notifications
- Web dashboard
- FastAPI REST API
- Docker containerization
- Provider abstraction layer for battery systems
