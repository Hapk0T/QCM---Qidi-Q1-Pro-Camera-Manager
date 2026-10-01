# Installation, repair, restore and uninstall

## Requirements

The current release targets the QIDI Q1 Pro environment used for development and testing.

The installer expects:

```text
arm64
systemctl
python3
dpkg-query
sudo (when launched as non-root)
crudini
curl
ffmpeg
v4l2-ctl
find
xargs
logger
flock
libevent-2.1-6
libevent-pthreads-2.1-6
libjpeg62-turbo
```

The installer checks dependencies but does not upgrade them.

## Offline installation

The release contains the QCM runtime, Crowsnest runtime and uStreamer binary. No Git repository is required and the installer does not use the upstream Crowsnest installer.

Extract the release directory and run:

```bash
bash install.sh install
```

The script may also be run directly if it has an executable bit:

```bash
./install.sh install
```

The first form is preferred when extracting on Windows because Windows-created archives may not preserve Unix execute permissions.

## sudo behavior

When launched by a normal user, the installer does:

```text
sudo -v
```

and then re-executes itself through:

```text
sudo bash "$0" "$@"
```

The sudo password is not stored in the script.

## First install

`install` performs these operations:

1. refuse to overwrite an already detected QCM installation;
2. create the persistent backup if it does not exist;
3. disable the stock `webcamd` backend;
4. deploy QCM and Crowsnest runtime files;
5. set executable permissions for `crowsnest` and `ustreamer`;
6. write the release `webcam.txt.example` as the initial active QCM configuration;
7. enable/restart `qcm.service`;
8. run the camera health check;
9. report success only after the backend is responding.

## Persistent backup

Backup location:

```text
/home/mks/.qcm-backup
```

The backup is created once.

If a valid backup already exists, a later `install` or `repair` reuses it rather than silently replacing it.

Backup contents include:

```text
webcam.txt          original configuration, if present
manifest            baseline metadata and webcamd state
```

The manifest records:

```text
CONFIG_EXISTS
CONFIG_UID
CONFIG_GID
CONFIG_MODE
WEBCAMD_ENABLED
WEBCAMD_ACTIVE
```

## Important backup rule

The backup represents the baseline that existed when it was first created.

That means a manually pre-created or stale backup changes what `restore` and `uninstall` will return to. This is intentional: the installer treats the first valid backup as immutable baseline state.

## repair

Use:

```bash
bash install.sh repair
```

`repair` is for re-deploying the current QCM/Crowsnest runtime when the installation is already present.

It does not replace the persistent baseline backup.

It stops the QCM-controlled stack, disables stock `webcamd`, reinstalls the bundled runtime, restarts QCM and performs the health check.

## restore

Use:

```bash
bash install.sh restore
```

`restore` does not remove the QCM runtime. It restores the recorded pre-installation state and disables QCM/Crowsnest.

The restored state includes:

- `webcam.txt` contents and metadata;
- `webcamd` enabled/disabled state;
- `webcamd` active/inactive state.

## uninstall

Use:

```bash
bash install.sh uninstall
```

`uninstall` first restores the saved baseline, then removes QCM-owned runtime and systemd files.

The persistent backup remains at:

```text
/home/mks/.qcm-backup
```

This is deliberate so a later reinstall can use the same original baseline.

## Files the installer owns

```text
/etc/systemd/system/qcm.service
/etc/systemd/system/crowsnest-qidi.service

/opt/qidi-camera/qcm
/opt/qidi-camera/crowsnest
/opt/qidi-camera/config/crowsnest.conf
```

The installer does not intentionally remove:

```text
/usr/local/bin/webcamd
/etc/systemd/system/webcamd.service
```

or unrelated QIDI/Klipper files.

## Post-install verification

Run:

```bash
systemctl is-active qcm.service
systemctl is-active crowsnest-qidi.service
systemctl is-active webcamd.service
```

Then:

```bash
curl -sS --max-time 3 \
  -o /tmp/qcm-test.jpg \
  -w "HTTP=%{http_code} SIZE=%{size_download}\n" \
  http://127.0.0.1:8080/?action=snapshot
```

And:

```bash
file /tmp/qcm-test.jpg
```

The tested result is HTTP 200 with a valid `1280x720` JPEG.
