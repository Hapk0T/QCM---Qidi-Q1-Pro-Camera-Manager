# Configuration reference

## Authoritative configuration file

```text
/home/mks/klipper_config/webcam.txt
```

The file is intentionally shell-compatible because that matches the existing QIDI/Klipper camera configuration mechanism.

## QCM variables

### QCM_BACKEND

Selects the backend.

Supported values in `0.2.0-alpha1`:

```text
crowsnest
webcamd
```

### QCM_DEVICE

V4L2 device path.

Tested value:

```text
/dev/video4
```

### QCM_RESOLUTION

Requested camera resolution.

Tested value:

```text
1280x720
```

### QCM_FPS

Requested maximum frame rate.

Tested Crowsnest value:

```text
30
```

### QCM_HOST

Local HTTP bind address.

Tested value:

```text
127.0.0.1
```

### QCM_PORT

Local camera HTTP port.

Tested value:

```text
8080
```

### QCM_V4L2_CONTROLS

Comma-separated V4L2 controls passed to the backend.

Tested Crowsnest value:

```text
brightness=0,contrast=1,saturation=80,gamma=84,gain=1,sharpness=2,backlight_compensation=0
```

### QCM_BACKEND_OPTIONS

Semicolon-separated backend-specific options.

For the Crowsnest backend, the tested release configuration is:

```text
crowsnest.log_path=/tmp/crowsnest.log;crowsnest.log_level=quiet;crowsnest.delete_log=true;crowsnest.no_proxy=false;cam1.mode=mjpg
```

Backend-specific options are validated against the selected backend. Crowsnest options should not be left in a configuration whose backend is `webcamd`.

## Legacy QIDI variable

The stock-compatible camera parameter can remain in the file:

```text
camera_usb_options="-r 1280x720 -f 30 -d /dev/video4"
```

It remains useful for compatibility and for restoring/understanding the stock backend.

## Example configuration

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

## Generated Crowsnest configuration

QCM generates:

```text
/opt/qidi-camera/config/crowsnest.conf
```

For the tested configuration:

```ini
[crowsnest]
log_path: /tmp/crowsnest.log
log_level: quiet
delete_log: true
no_proxy: false

[cam 1]
mode: mjpg
port: 8080
device: /dev/video4
resolution: 1280x720
max_fps: 30
v4l2ctl: brightness=0,contrast=1,saturation=80,gamma=84,gain=1,sharpness=2,backlight_compensation=0
```

Do not treat this generated file as the primary user configuration. QCM regenerates it from its managed configuration.

## State files

QCM keeps state under:

```text
/opt/qidi-camera/qcm/state/
```

Notable files:

```text
known_good.conf
accepted.conf
status.json
rejected.conf
rejected.reason
```

`known_good.conf` is protected internal state. `status.json` may retain historical error information, so a `last_error` entry does not necessarily mean the current runtime is failing.
