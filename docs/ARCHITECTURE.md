# Architecture

## 1. Design goal

QCM is a control plane for the QIDI Q1 Pro camera stack.

It is not intended to be a replacement firmware layer. The stock camera implementation remains installed so the printer can return to its previous state.

## 2. Data path

### Crowsnest backend

```text
USB camera
   │
   ▼
V4L2 /dev/video4
   │
   ▼
uStreamer
   │
   ▼
Crowsnest
   │
   ▼
127.0.0.1:8080
   │
   ▼
QIDI nginx
   │
   ▼
/webcam/
   │
   ├── Fluidd
   └── QIDI WebUI
```

### Stock backend

```text
USB camera
   │
   ▼
V4L2 /dev/video4
   │
   ▼
webcamd
   │
   ▼
mjpg-streamer
   │
   ▼
QIDI HTTP layer
   │
   ▼
/webcam/
```

Only one backend should own `/dev/video4` at a time.

## 3. Control plane

QCM reads:

```text
/home/mks/klipper_config/webcam.txt
```

and produces backend-specific runtime actions.

Core paths:

```text
/opt/qidi-camera/qcm/
/opt/qidi-camera/config/crowsnest.conf
/opt/qidi-camera/qcm/state/
```

Important state files include:

```text
known_good.conf
accepted.conf
status.json
rejected.conf
rejected.reason
```

`known_good.conf` is internal root-only state. `webcam.txt` remains the user-visible configuration surface.

## 4. Backend state machine

```text
                    +----------------+
                    |    QCM idle    |
                    +--------+-------+
                             |
                             v
                  +----------------------+
                  | parse + validate     |
                  +----------+-----------+
                             |
                             v
                  +----------------------+
                  | capability checks   |
                  +----------+-----------+
                             |
                             v
                  +----------------------+
                  | backend apply       |
                  +----------+-----------+
                             |
                    +--------+--------+
                    |                 |
                   OK                FAIL
                    |                 |
                    v                 v
              +-----------+      +-----------+
              | health    |      | rollback  |
              | check     |      |           |
              +-----+-----+      +-----------+
                    |
                    v
              +-----------+
              |  commit   |
              +-----------+
```

## 5. Backend switching

Switching is transactional. The important safety invariant is:

```text
old working backend
        |
        v
apply new backend
        |
        +---- health OK -> commit
        |
        +---- health FAIL -> restore old state
```

## 6. Crowsnest integration

The release embeds a minimal Crowsnest legacy/v3 runtime.

The following design choices are intentional:

- no `.git` repository is required at runtime;
- runtime version reporting does not depend on Git metadata;
- the mandatory RTSP binary check was removed;
- RTSP support is not selected by QCM in this release;
- the uStreamer binary is shipped in the package.

`crowsnest/libs/rtspsimple.sh` is retained to minimize divergence from the tested legacy/v3 runtime even though QCM does not use RTSP.

## 7. systemd ownership

QCM service:

```text
/etc/systemd/system/qcm.service
```

QCM Crowsnest service:

```text
/etc/systemd/system/crowsnest-qidi.service
```

Stock QIDI service:

```text
/etc/systemd/system/webcamd.service
```

Stock QIDI executable:

```text
/usr/local/bin/webcamd
```

QCM owns only its own service/runtime paths. The stock service and executable are preserved as rollback targets.

## 8. Configuration generation

For the Crowsnest backend QCM generates:

```text
/opt/qidi-camera/config/crowsnest.conf
```

The generated file is runtime state. It is not the authoritative user configuration.

The authoritative user-facing file remains:

```text
/home/mks/klipper_config/webcam.txt
```

## 9. Health-check model

A backend being `active` is not enough to declare the camera healthy.

The release checks actual HTTP data.

For an MJPEG stream, an infinite response is expected. The test therefore accepts a curl timeout after data has been received, rather than requiring the stream connection to terminate normally.

## 10. Why the public port remains 8080

The tested QIDI WebUI already expects the camera to be reachable through its existing `/webcam/` path. QCM therefore keeps the local camera service on `127.0.0.1:8080` and leaves the QIDI nginx layer intact.

This avoids unnecessary WebUI-specific changes.
