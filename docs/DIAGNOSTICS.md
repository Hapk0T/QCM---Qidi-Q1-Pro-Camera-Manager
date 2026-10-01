# Diagnostics and troubleshooting

## 1. Service state

Check all camera services:

```bash
sudo sh -c '
  echo "qcm=$(systemctl is-active qcm.service)"
  echo "crowsnest=$(systemctl is-active crowsnest-qidi.service)"
  echo "webcamd=$(systemctl is-active webcamd.service)"
'
```

Expected Crowsnest state:

```text
qcm=active
crowsnest=active
webcamd=inactive
```

Expected restored stock state:

```text
qcm=inactive
webcamd=active
```

## 2. Verify the port

```bash
ss -ltn | grep ':8080 '
```

Expected:

```text
127.0.0.1:8080
```

## 3. Verify a snapshot

```bash
curl -sS --max-time 3 \
  -o /tmp/qcm-test.jpg \
  -w "HTTP=%{http_code} SIZE=%{size_download}\n" \
  http://127.0.0.1:8080/?action=snapshot

file /tmp/qcm-test.jpg
```

A working example returns HTTP 200 and a valid JPEG.

## 4. Verify the QIDI HTTP path

```bash
curl -sS --max-time 3 \
  -o /tmp/qcm-qidi.jpg \
  -w "HTTP=%{http_code} SIZE=%{size_download}\n" \
  http://127.0.0.1/webcam/?action=snapshot

file /tmp/qcm-qidi.jpg
```

This checks the complete path through the QIDI HTTP layer.

## 5. Verify the selected backend

```bash
grep -E '^(QCM_BACKEND|QCM_DEVICE|QCM_RESOLUTION|QCM_FPS)' \
  /home/mks/klipper_config/webcam.txt
```

For the tested Crowsnest setup:

```text
QCM_BACKEND="crowsnest"
QCM_DEVICE="/dev/video4"
QCM_RESOLUTION="1280x720"
QCM_FPS="30"
```

## 6. Verify the generated Crowsnest configuration

```bash
cat /opt/qidi-camera/config/crowsnest.conf
```

The generated file should contain the selected device, resolution, FPS and `mode: mjpg`.

## 7. Verify the real uStreamer process

```bash
pgrep -af '/opt/qidi-camera/crowsnest|ustreamer'
```

The expected uStreamer process includes parameters equivalent to:

```text
--host 127.0.0.1
-p 8080
-d /dev/video4
-m MJPEG
-r 1280x720
-f 30
```

## 8. Check for duplicate camera processes

Two camera servers must not fight over `/dev/video4`.

```bash
pgrep -af 'crowsnest|mjpeg|ustreamer|webcamd'
```

If an old manual test process is still running, stop that test process before debugging the QCM-managed service.

This was an actual failure mode during development: an old test Crowsnest instance continued to run from `/tmp` and caused confusing camera behavior even though the production QCM Crowsnest service was healthy.

## 9. Interpreting curl stream timeouts

This command intentionally targets an endless stream:

```bash
curl --max-time 2 'http://127.0.0.1:8080/?action=stream'
```

Exit code `28` can be expected when bytes were received and the command simply reached its time limit.

The installer therefore evaluates both curl status and the number of received bytes.

## 10. QCM status journal

```bash
python3 /opt/qidi-camera/qcm/qcm.py --status
```

The displayed `last_error` may be historical. Confirm the live state with the service and HTTP checks before treating an old message as an active failure.

## 11. Crowsnest unit appears failed but the camera works

First compare:

```bash
systemctl status crowsnest-qidi.service --no-pager -l
systemctl is-active qcm.service
ss -ltn | grep ':8080 '
```

During development a service had previously been stopped by QCM/manual test activity and systemd retained a stale `failed` state while another Crowsnest instance was serving the camera. The service state alone was therefore not considered sufficient evidence of a camera failure.

## 12. Camera disappears after reboot

Separate these cases:

1. service does not start;
2. service starts but `/dev/video4` is unavailable;
3. backend serves locally but QIDI `/webcam/` is unavailable;
4. the firmware itself does not finish rebooting.

For the tested machine, a normal systemd reboot once left SSH, WebUI and the printer display unavailable until a full power-cycle boot. After power-cycle the QCM/Crowsnest stack came back normally.

Do not alter the QCM runtime to compensate for firmware shutdown behavior without reproducing the issue independently.

## 13. Full diagnostic bundle

A useful manual diagnostic set is:

```bash
python3 --version
uname -a
cat /etc/os-release
systemctl is-active qcm.service crowsnest-qidi.service webcamd.service
systemctl --no-pager -l status qcm.service crowsnest-qidi.service webcamd.service
pgrep -af 'crowsnest|mjpeg|ustreamer|webcamd'
ls -l /dev/video*
ss -ltn | grep ':8080 '
grep -E '^(QCM_|camera_usb_options)' /home/mks/klipper_config/webcam.txt
cat /opt/qidi-camera/config/crowsnest.conf 2>/dev/null || true
python3 /opt/qidi-camera/qcm/qcm.py --status
```
