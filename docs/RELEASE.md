# Release notes — 0.2.0-alpha1

## Release identity

```text
QCM_v0.2.0-alpha1.zip
Size:   199762 bytes
SHA256: 10F55074ECB2B96A8326D8F1E3CC407BD9137176FC9C8AF604BD4E2354A6AB65
```

## Included components

```text
install.sh
qcm.py
qcm.service
crowsnest-qidi.service
webcam.txt.example
crowsnest/
```

The Crowsnest directory contains the minimal tested runtime, its libraries, uStreamer binary, static web assets and license files.

## Main capabilities

- backend abstraction;
- `webcamd` backend;
- Crowsnest backend;
- V4L2 device and control handling;
- configuration parsing and validation;
- backend-specific option validation;
- transactional application;
- rollback to known-good state;
- rejected configuration tracking;
- backend HTTP snapshot health check;
- MJPEG stream health check;
- QIDI `/webcam/` health check;
- status journal;
- CLI diagnostics;
- systemd integration;
- offline installer;
- repair;
- restore;
- uninstall.

## Tested configuration

```text
Camera:      /dev/video4
Backend:     crowsnest
Mode:        MJPEG
Resolution: 1280x720
FPS:         30
HTTP:        127.0.0.1:8080
Public path: /webcam/
```

## Deliberate non-goals

This release does not introduce a QCM web UI, online update system, cloud control, RTSP management, camera AI processing or QIDI firmware replacement.
