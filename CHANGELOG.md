# Changelog

## 0.2.0-alpha1 — 2026-10-01

First documented alpha release of the QCM management layer.

### Added

- backend abstraction for stock `webcamd` and Crowsnest;
- configuration parsing and validation;
- V4L2 capability/control handling;
- transactional apply/commit model;
- known-good configuration state;
- rollback on failed backend application;
- rejected configuration tracking;
- backend and QIDI HTTP health checks;
- MJPEG stream health check that understands endless streams;
- `--status`, `--check-config`, `--self-test`, `--list-controls`, `--dry-run` and `--apply-once` CLI paths;
- systemd integration;
- offline QCM/Crowsnest/uStreamer payload;
- installer with `install`, `repair`, `restore` and `uninstall`;
- persistent pre-installation backup;
- normal-user installer execution through sudo;
- runtime permission normalization for Linux executables.

### Crowsnest runtime changes

- removed mandatory RTSP binary dependency check;
- removed RTSP version detection;
- removed Git dependence from runtime version detection;
- retained the legacy/v3 runtime structure while minimizing unrelated changes.

### Tested fixes during release QA

- MJPEG stream timeout no longer misclassified as failure when data was received;
- old manual Crowsnest test processes identified as a source of camera conflicts;
- Windows archive path separator problem fixed in final Linux release archive;
- executable permission loss in Windows-created archives handled by the installer.

### Known platform observation

A normal systemd reboot on the tested Q1 Pro firmware once failed to return SSH/WebUI/display until a full power-cycle. The power-cycle boot completed normally and QCM/Crowsnest started correctly.
