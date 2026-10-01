# Known issues and caveats

## 1. Alpha release

`0.2.0-alpha1` is an alpha release. The architecture and recovery path are the priority; the project is not yet a general-purpose camera manager for arbitrary printers.

## 2. Tested platform scope is narrow

The release is built around the legacy QIDI Q1 Pro environment used for development and testing.

It should not be assumed to work unchanged on other QIDI models, firmware images or Linux userspaces.

## 3. Stock firmware shutdown behavior

A normal `systemd reboot` once caused the tested Q1 Pro to become unreachable over SSH and its WebUI/display did not immediately return. A complete power-cycle boot recovered the printer, and QCM/Crowsnest started normally afterward.

The project does not currently claim to control or fix this firmware-level reboot behavior.

## 4. Persistent backup is authoritative

The backup at:

```text
/home/mks/.qcm-backup
```

is intentionally immutable after its first valid creation.

A stale or manually constructed backup therefore changes what `restore` and `uninstall` consider the pre-installation state.

For a production deployment, the installer should be run on the intended baseline machine without pre-populating this directory.

## 5. QCM status is partly journal-oriented

`--status` can display a historical `last_error`. It is not a replacement for live service and HTTP checks.

## 6. Only one backend should own the camera

The stock backend and Crowsnest should not be allowed to open `/dev/video4` simultaneously.

Manual test processes can also create conflicts. Always check `pgrep -af` output when troubleshooting.

## 7. Windows archives need extra care

The final release archive was built specifically to preserve Linux-friendly entry paths. When rebuilding on Windows, validate both path separators and executable permissions after extraction on Linux.
