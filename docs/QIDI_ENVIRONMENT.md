# QIDI Q1 Pro environment notes

This document records the environment assumptions that matter to QCM development.

## Test platform

The release was validated on a real QIDI Q1 Pro using the legacy QIDI Linux userspace.

The development notes identified the environment as an Armbian/Debian Buster-era image with Python 3.7.x. The exact printer/firmware environment should be treated as the compatibility target for this alpha rather than as a generic requirement for all printers.

The tested camera is exposed as:

```text
/dev/video4
```

## Stock camera stack

The stock service is:

```text
/etc/systemd/system/webcamd.service
```

Its executable is:

```text
/usr/local/bin/webcamd
```

The tested unit is a simple systemd wrapper for the `webcamd` program and runs it as the `mks` user.

The stock configuration used during testing was:

```text
camera_usb_options="-r 1280x720 -f 10 -d /dev/video4"
```

## QCM runtime locations

```text
/opt/qidi-camera/qcm/
/opt/qidi-camera/crowsnest/
/opt/qidi-camera/config/
```

## Why this environment is treated carefully

The QIDI userspace is older than many current Linux camera stacks. Installing current packages or current Crowsnest releases indiscriminately can introduce compatibility problems.

The QCM alpha therefore ships the tested runtime and treats system dependencies as existing prerequisites.

## Observed dependency versions

The release test machine reported:

```text
crudini                  0.7-1
curl                     7.64.0-4+deb10u2
ffmpeg                   7:4.1.9-0+deb10u1
v4l-utils                1.16.3-3
libevent-2.1-6           2.1.8-stable-4
libevent-pthreads-2.1-6 2.1.8-stable-4
libjpeg62-turbo          1:1.5.2-2+deb10u1
```

APT offered newer candidates for `curl` and `ffmpeg`, but they were intentionally not upgraded as part of release testing.

## Camera ownership rule

The same V4L2 device must not be opened by both `webcamd` and Crowsnest at the same time.

When Crowsnest is active:

```text
webcamd = inactive
crowsnest = active
```

When the stock configuration is restored:

```text
webcamd = active
crowsnest = inactive
```

## Firmware reboot observation

During release QA, an orderly systemd reboot left the printer unreachable until a hard power-cycle was performed. After cold boot the printer, QCM and Crowsnest were healthy again.

This note is intentionally kept in the project documentation so future changes are not incorrectly blamed for or designed around an unrelated firmware shutdown behavior without reproduction.
