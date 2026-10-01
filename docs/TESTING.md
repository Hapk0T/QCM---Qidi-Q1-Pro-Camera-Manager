# Test matrix

## Release QA summary

`0.2.0-alpha1` was tested on a real QIDI Q1 Pro.

## Static checks

| Test | Result |
|---|---|
| `bash -n install.sh` | PASS |
| `python3 -m py_compile qcm.py` | PASS |
| release ZIP integrity | PASS |
| release ZIP Linux extraction | PASS |
| `install.sh` from extracted ZIP | PASS |
| executable permission repair | PASS |

## Installer lifecycle

| Scenario | Result |
|---|---|
| fresh `install` | PASS |
| `repair` | PASS |
| `restore` | PASS |
| `uninstall` | PASS |
| reinstall after uninstall | PASS |
| `repair` from extracted release ZIP | PASS |

## Camera validation

| Check | Result |
|---|---|
| `/dev/video4` available | PASS |
| Crowsnest local snapshot | PASS |
| QIDI `/webcam/` snapshot | PASS |
| valid JPEG | PASS |
| 1280x720 frame | PASS |
| 30 FPS Crowsnest configuration | PASS |
| stock webcamd restore | PASS |
| power-cycle boot | PASS |

## Verified state

Crowsnest mode:

```text
qcm.service             enabled / active
crowsnest-qidi.service  disabled / active
webcamd.service         disabled / inactive
```

Stock mode after restore/uninstall:

```text
qcm.service     disabled / inactive
webcamd.service enabled / active
```

## Packaging problems found and fixed

### Problem: MJPEG health check treated timeout as failure

An endless stream naturally caused curl to exit with status `28` after receiving data.

The health check was changed to treat timeout as acceptable when enough stream data had already been received.

### Problem: installer could not be started from a normal user

The installer was changed to obtain sudo once and re-execute through `sudo bash`.

### Problem: Windows ZIP paths used backslashes

`Compress-Archive` produced entries such as:

```text
QCM_v0.2.0-alpha1\qcm.py
```

That archive form is unsuitable as a Linux release package. The final archive was rebuilt with Unix-style `/` paths.

### Problem: Windows ZIP lost Unix executable bits

Files were extracted as `666`.

The installer now sets the required modes during deployment:

```text
755 crowsnest
755 ustreamer
```

### Problem: old manual test processes interfered with camera ownership

A previous Crowsnest test instance remained alive from `/tmp` and competed for the same camera/HTTP resources. The test processes were removed and the production QCM stack then produced the expected 1280x720 frame.

These checks are now part of the release-testing mindset: inspect live processes before concluding that the installed runtime is broken.
