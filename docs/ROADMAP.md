# Roadmap

The roadmap is intentionally separated from the `0.2.0-alpha1` release contract. Future work must not silently redefine the behavior of the released recovery path.

## Completed in 0.2.0-alpha1

- QCM backend abstraction;
- stock `webcamd` backend;
- Crowsnest/uStreamer backend;
- transactional configuration application;
- rollback and known-good state;
- V4L2 handling;
- HTTP and MJPEG health checks;
- offline runtime bundle;
- install/repair/restore/uninstall lifecycle;
- persistent pre-installation backup;
- real Q1 Pro validation.

## Candidate next work

### Configuration and state

- tighten schema/versioning for `webcam.txt`;
- make state migration explicit between QCM releases;
- improve distinction between historical errors and current live health;
- add machine-readable diagnostics suitable for future WebUI/API use.

### Backend framework

- formalize backend interface and lifecycle methods;
- isolate backend implementations from transaction logic;
- expand backend capability declarations;
- make device/port ownership checks explicit.

### User experience

- optional QCM WebUI;
- clearer status and recovery messages;
- configuration backup/export;
- safer assisted backend switching.

### Integration

- further evaluate Fluidd/QIDI WebUI camera behavior;
- evaluate firmware-update persistence;
- investigate the platform-specific reboot behavior without weakening camera recovery.

### Distribution

- reproducible release build;
- automated Linux package QA;
- checksums/signing;
- CI for Python/Bash static checks.

## Non-goals unless explicitly revisited

- replacing QIDI firmware;
- destructive removal of the stock camera stack;
- requiring an online installer;
- automatic system-package upgrades;
- silently modifying unrelated QIDI services.
