# Development guide

## Development principles

QCM should remain a small, deterministic control layer.

Changes should prefer:

- explicit state transitions;
- reversible operations;
- offline operation;
- compatibility with the old QIDI userspace;
- clear separation between user configuration and generated backend state.

Avoid broad changes to the QIDI firmware environment.

## Source/runtime paths

On the printer:

```text
/opt/qidi-camera/qcm/qcm.py
/opt/qidi-camera/qcm/state/
/opt/qidi-camera/config/crowsnest.conf
/opt/qidi-camera/crowsnest/
/etc/systemd/system/qcm.service
/etc/systemd/system/crowsnest-qidi.service
```

## QCM entry point

The current implementation is a single Python entry point:

```text
qcm.py
```

The code is intentionally self-contained for the old Python 3.7 environment.

## Python compatibility

The release was tested on Python 3.7.x.

Do not casually introduce language features that require a newer Python version.

Recommended local check:

```bash
python3 -m py_compile qcm.py
```

## Shell compatibility

The Crowsnest runtime uses Bash scripts and a bundled uStreamer binary.

Recommended checks:

```bash
bash -n crowsnest
for f in crowsnest/libs/*.sh; do bash -n "$f" || exit 1; done
```

## Installer rules

The installer has a strict ownership boundary.

QCM-owned:

```text
/etc/systemd/system/qcm.service
/etc/systemd/system/crowsnest-qidi.service
/opt/qidi-camera/qcm
/opt/qidi-camera/crowsnest
/opt/qidi-camera/config/crowsnest.conf
```

QIDI-owned and preserved:

```text
/usr/local/bin/webcamd
/etc/systemd/system/webcamd.service
```

Do not turn a QCM feature into a destructive firmware migration.

## Installer testing

Minimum installer checks:

```bash
bash -n install.sh
bash install.sh --help
```

On a real printer the lifecycle test should cover:

```text
install
repair
restore
uninstall
install again
cold boot
```

The backup must remain unchanged by `repair`.

## Package testing

The release archive must be tested on Linux after packaging.

Important checks:

```bash
unzip -t QCM_v0.2.0-alpha1.zip
bash -n QCM_v0.2.0-alpha1/install.sh
python3 -m py_compile QCM_v0.2.0-alpha1/qcm.py
```

When an archive is created on Windows, verify the archive entry paths explicitly. Linux archive paths must use `/`, not `\`.

Windows-created archives can also lose Unix executable bits. The installer therefore explicitly sets `755` for the deployed `crowsnest` and `ustreamer` executables.

## Release build discipline

A release should be built from a clean tree.

Do not include:

```text
.git
__pycache__
*.bak
*.tmp
runtime state
backup directories
logs
```

The release payload should contain the runtime and source artifacts needed for offline deployment, not the printer's live state.

## Code review checklist

Before merging a QCM change, verify:

- no new online dependency was introduced into the installer;
- stock `webcamd` remains recoverable;
- configuration validation still precedes apply;
- a failed apply still has a rollback path;
- health checks test real camera data rather than only process state;
- Python 3.7 compatibility is preserved;
- generated state is not accidentally committed into the release payload.
