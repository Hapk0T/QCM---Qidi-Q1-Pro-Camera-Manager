# QCM — QIDI Camera Manager

QCM (QIDI Camera Manager) is a lightweight camera-stack management layer for the QIDI Q1 Pro.

The project was created to solve a specific problem: the Q1 Pro has a working but limited stock camera stack, while alternative Linux camera runtimes such as Crowsnest/uStreamer require careful integration with the printer's existing services, configuration and recovery paths.

QCM adds an explicit backend abstraction instead of deleting the stock implementation. The current alpha release can switch between the original QIDI `webcamd` backend and a bundled Crowsnest/uStreamer backend, validate configuration, perform health checks, commit known-good state and roll back failed changes.

> **Current release:** `0.2.0-alpha1`
>
> **Status:** tested on a real QIDI Q1 Pro. The release is an alpha and is deliberately conservative about modifying the stock firmware environment.

## Why QCM exists

The camera path on the Q1 Pro is not just a single streamer process. It sits inside a larger QIDI/Klipper/WebUI environment. Replacing the stock process directly creates unnecessary recovery and update risks.

QCM therefore follows five rules:

- preserve the original QIDI `webcamd` installation;
- keep the backend choice explicit;
- validate before and after applying changes;
- keep a persistent pre-installation backup;
- make the complete QCM/Crowsnest runtime available offline.

## Architecture

```mermaid
flowchart TD
    Camera[USB camera] --> V4L2[/dev/video4]
    V4L2 --> Stock[webcamd + mjpg-streamer]
    V4L2 --> CN[Crowsnest + uStreamer]
    QCM[QCM] --> Stock
    QCM --> CN
    CN --> HTTP[127.0.0.1:8080]
    Stock --> HTTP
    HTTP --> Nginx[QIDI nginx /webcam/]
    Nginx --> UI[Fluidd / QIDI WebUI]
```

QCM is the control plane. The selected backend is the data-plane implementation.

See [Architecture](docs/ARCHITECTURE.md) for the full model.

## Current release behavior

When the Crowsnest backend is selected, the tested configuration is:

```text
Backend:   crowsnest
Device:    /dev/video4
Mode:      MJPEG
Resolution: 1280x720
FPS:       30
Bind:      127.0.0.1:8080
Public URL: /webcam/
```

The stock backend remains installed and is disabled while Crowsnest is active.

Typical active state:

```text
qcm.service             enabled / active
crowsnest-qidi.service  disabled / active
webcamd.service         disabled / inactive
```

When the stock backend is restored, the expected state is:

```text
qcm.service     disabled / inactive
webcamd.service enabled / active
```

## Repository layout

The release source tree is intentionally small:

```text
QCM_v0.2.0-alpha1/
├── install.sh
├── qcm.py
├── qcm.service
├── crowsnest-qidi.service
├── webcam.txt.example
├── README.md
└── crowsnest/
    ├── crowsnest
    ├── LICENSE
    ├── libs/
    ├── bin/ustreamer/
    │   ├── LICENSE
    │   └── ustreamer
    └── ustreamer-www/
```

Runtime state is created on the printer and is not part of the source/release payload.

## Installation

The release is designed for offline installation.

```bash
bash install.sh install
```

The installer can be launched as `root` or by a normal user with sudo access. When started as a normal user, it asks sudo for authentication once and re-executes itself as root. The password is never stored by the installer.

Supported commands:

```text
install
repair
restore
uninstall
```

See [Installation and recovery](docs/INSTALLATION.md).

## Configuration

QCM uses:

```text
/home/mks/klipper_config/webcam.txt
```

Example:

```ini
QCM_BACKEND="crowsnest"
QCM_DEVICE="/dev/video4"
QCM_RESOLUTION="1280x720"
QCM_FPS="30"
QCM_HOST="127.0.0.1"
QCM_PORT="8080"
QCM_V4L2_CONTROLS="brightness=0,contrast=1,saturation=80,gamma=84,gain=1,sharpness=2,backlight_compensation=0"
QCM_BACKEND_OPTIONS="crowsnest.log_path=/tmp/crowsnest.log;crowsnest.log_level=quiet;crowsnest.delete_log=true;crowsnest.no_proxy=false;cam1.mode=mjpg"

camera_usb_options="-r 1280x720 -f 30 -d /dev/video4"
```

See [Configuration](docs/CONFIGURATION.md).

## CLI

```bash
python3 /opt/qidi-camera/qcm/qcm.py --help
python3 /opt/qidi-camera/qcm/qcm.py --check-config
python3 /opt/qidi-camera/qcm/qcm.py --self-test
python3 /opt/qidi-camera/qcm/qcm.py --list-controls
python3 /opt/qidi-camera/qcm/qcm.py --status
python3 /opt/qidi-camera/qcm/qcm.py --apply-once
python3 /opt/qidi-camera/qcm/qcm.py --dry-run
```

## Transaction model

Configuration application follows:

```text
parse
  -> validate
  -> capability check
  -> generate backend configuration
  -> apply
  -> healthcheck
  -> commit
```

A failed operation attempts rollback to the last known-good state, including backend state and V4L2 controls.

## Health checks

The release verifies both the local backend and the QIDI-facing HTTP path.

Backend snapshot:

```text
http://127.0.0.1:8080/?action=snapshot
```

QIDI path:

```text
http://127.0.0.1/webcam/?action=snapshot
```

The MJPEG stream is intentionally endless. A curl timeout is therefore not a failure by itself when a useful amount of stream data has already been received.

## Backup and rollback

The original pre-installation state is stored outside the QCM runtime:

```text
/home/mks/.qcm-backup
```

The backup is created once and is deliberately not replaced by `repair` or later reinstalls.

The manifest records the `webcam.txt` presence, UID, GID, mode and the recorded `webcamd` enabled/active state.

## Tested lifecycle

The following sequence has been executed on a real QIDI Q1 Pro:

```text
repair       -> camera works
restore      -> stock webcamd works
uninstall    -> stock webcamd works
install      -> QCM/Crowsnest works
cold boot    -> QCM/Crowsnest works
```

The verified Crowsnest path returns HTTP 200 and a valid `1280x720` JPEG through `/webcam/`.

## Known limitations

This release is intentionally narrow in scope.

Not included:

- a QCM web UI;
- online update infrastructure;
- cloud management;
- automatic system-package upgrades;
- RTSP management;
- AI/ONNX processing;
- Obico integration;
- QIDI UI modification;
- firmware replacement.

A normal systemd reboot was also observed to behave unusually on the tested firmware image: the SSH connection, WebUI and printer display did not immediately return. A full power-cycle boot recovered normally, and QCM/Crowsnest started correctly afterward. This is recorded as a platform-specific observation, not as a QCM feature.

See [Known issues](docs/KNOWN_ISSUES.md).

## Compatibility snapshot

The project was tested against the legacy QIDI environment used by the Q1 Pro test machine. The exact dependency state observed during release testing was:

```text
crudini                  0.7-1
curl                     7.64.0-4+deb10u2
ffmpeg                   7:4.1.9-0+deb10u1
v4l-utils                1.16.3-3
libevent-2.1-6           2.1.8-stable-4
libevent-pthreads-2.1-6 2.1.8-stable-4
libjpeg62-turbo          1:1.5.2-2+deb10u1
```

These versions are a test-environment snapshot, not a promise that every compatible machine must use exactly these versions. The installer checks for required commands and libraries but does not upgrade them.

## Development

Read [Development](docs/DEVELOPMENT.md) before modifying the runtime or installer.

The most important rule is to test changes against the real Q1 Pro behavior and preserve the `0.2.0-alpha1` recovery model.

## Release

The current release artifact is:

```text
QCM_v0.2.0-alpha1.zip
Size:   199762 bytes
SHA256: 10F55074ECB2B96A8326D8F1E3CC407BD9137176FC9C8AF604BD4E2354A6AB65
```

See [Release notes](docs/RELEASE.md) and [Changelog](CHANGELOG.md).

## Third-party components

The release contains a minimal, modified Crowsnest legacy/v3 runtime and a tested uStreamer binary. The corresponding license files are included in the payload under `crowsnest/LICENSE` and `crowsnest/bin/ustreamer/LICENSE`.

See [Licensing notes](docs/LICENSES.md).
