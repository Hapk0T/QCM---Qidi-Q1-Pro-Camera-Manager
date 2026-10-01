#!/usr/bin/env python3
# QCM - QIDI Camera Manager
# Python 3.7 compatible. Linux-only; uses libc inotify via ctypes.

from __future__ import print_function

import ctypes
import ctypes.util
import hashlib
import json
import os
import re
import select
import socket
import subprocess
import sys
import tempfile
import time
from collections import OrderedDict

APP = "QCM"
VERSION = "0.2.0-alpha1"

CONFIG_PATH = "/home/mks/klipper_config/webcam.txt"
STATE_DIR = "/opt/qidi-camera/qcm/state"
# Root-only authoritative last-known-good configuration.
KNOWN_GOOD_PATH = os.path.join(STATE_DIR, "known_good.conf")
# Legacy state from <=0.1.3; used once for migration only.
LEGACY_ACCEPTED_PATH = os.path.join(STATE_DIR, "accepted.conf")
STATUS_PATH = os.path.join(STATE_DIR, "status.json")
REJECTED_PATH = os.path.join(STATE_DIR, "rejected.conf")
REJECTED_REASON_PATH = os.path.join(STATE_DIR, "rejected.reason")
CROWSNEST_CONFIG = "/opt/qidi-camera/config/crowsnest.conf"
KLIPPY_UDS = "/tmp/klippy_uds"
V4L2_CTL = "/usr/bin/v4l2-ctl"
MOONRAKER_URL = "http://127.0.0.1:7125/printer/gcode/script"

LAST_GOOD_BEGIN = "# QCM-LAST-GOOD-BEGIN (READONLY MIRROR)\n"
LAST_GOOD_END = "# QCM-LAST-GOOD-END\n"

BACKENDS = {
    "crowsnest": {"service": "crowsnest-qidi.service"},
    "webcamd": {"service": "webcamd.service"},
}

DEFAULTS = OrderedDict([
    ("HOST", "127.0.0.1"),
    ("PORT", "8080"),
])
REQUIRED_KEYS = ("DEVICE", "RESOLUTION", "FPS")
KEY_RE = re.compile(
    r'^\s*QCM_(BACKEND|DEVICE|RESOLUTION|FPS|HOST|PORT|V4L2_CONTROLS|BACKEND_OPTIONS|CROWSNEST_CUSTOM_FLAGS)\s*=\s*'
    r'(?:(?:"((?:\\.|[^"\\])*)")|(?:\'((?:\\.|[^\'\\])*)\'))\s*(?:#.*)?$'
)
ANY_QCM_RE = re.compile(r'^\s*QCM_[A-Z0-9_]+\s*=')
RES_RE = re.compile(r'^(\d{2,5})x(\d{2,5})$')
INT_RE = re.compile(r'^\d+$')
LEGACY_RE = re.compile(r'^\s*camera_usb_options\s*=\s*(?:"([^"]*)"|\'([^\']*)\')\s*(?:#.*)?$')

# Unified backend-specific option schema. The public webcam.txt stays shell-compatible,
# while the adapter translates these options into the native backend configuration.
# Core camera fields (device/port/resolution/fps) intentionally do not belong here.
BACKEND_OPTION_RULES = {
    "crowsnest": {
        "crowsnest.log_path": "path",
        "crowsnest.log_level": "log_level",
        "crowsnest.delete_log": "bool",
        "crowsnest.no_proxy": "false_only",
        "cam1.mode": "mode",
        "cam1.custom_flags": "flags",
    },
    "webcamd": {},
}

DEFAULT_BACKEND_OPTIONS = OrderedDict([
    ("crowsnest.log_path", "/tmp/crowsnest.log"),
    ("crowsnest.log_level", "quiet"),
    ("crowsnest.delete_log", "true"),
    ("crowsnest.no_proxy", "false"),
    ("cam1.mode", "mjpg"),
])


class ConcurrentConfigChange(Exception):
    pass


def log(msg):
    sys.stdout.write("%s: %s\n" % (APP, msg))
    sys.stdout.flush()


def atomic_write(path, data, mode=0o644, preserve_owner=False):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    old_stat = None
    if preserve_owner and os.path.exists(path):
        old_stat = os.stat(path)
    fd, tmp = tempfile.mkstemp(prefix=".qcm-", dir=directory or ".")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if old_stat is not None:
            os.chown(tmp, old_stat.st_uid, old_stat.st_gid)
            os.chmod(tmp, old_stat.st_mode & 0o7777)
        os.replace(tmp, path)
        if directory:
            dfd = os.open(directory, os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_public_config(path):
    if not os.path.isfile(path):
        raise ValueError("configuration file not found: %s" % path)

    values = OrderedDict(DEFAULTS)
    seen = set()
    legacy = {}
    with open(path, "r") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip("\n")
            m = KEY_RE.match(line)
            if m:
                key = m.group(1)
                val = m.group(2) if m.group(2) is not None else m.group(3)
                val = val.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
                if key in seen:
                    raise ValueError("duplicate QCM_%s at line %d" % (key, lineno))
                seen.add(key)
                values[key] = val
                continue

            lm = LEGACY_RE.match(line)
            if lm:
                legacy["camera_usb_options"] = lm.group(1) if lm.group(1) is not None else lm.group(2)

    options = legacy.get("camera_usb_options", "")
    if "DEVICE" not in seen:
        dm = re.search(r'(?:^|\s)-d\s+(/dev/(?:video[0-9]+|v4l/[^\s]+))(?=\s|$)', options)
        if dm:
            values["DEVICE"] = dm.group(1)
            seen.add("DEVICE")
    if "RESOLUTION" not in seen:
        rm = re.search(r'(?:^|\s)-r\s+(\d{2,5}x\d{2,5})(?=\s|$)', options)
        if rm:
            values["RESOLUTION"] = rm.group(1)
            seen.add("RESOLUTION")
    if "FPS" not in seen:
        fm = re.search(r'(?:^|\s)-f\s+(\d+)(?=\s|$)', options)
        if fm:
            values["FPS"] = fm.group(1)
            seen.add("FPS")

    if "BACKEND" not in seen:
        values["BACKEND"] = "auto"
    values.pop("_legacy", None)

    missing = [k for k in REQUIRED_KEYS if k not in seen]
    if missing:
        raise ValueError("missing required setting(s): %s" % ", ".join("QCM_%s" % k for k in missing))
    return values


def parse_backend_options(raw):
    """Parse semicolon-separated section.key=value backend options."""
    if raw is None:
        return OrderedDict()
    text = raw.strip()
    if not text:
        return OrderedDict()
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ValueError("BACKEND_OPTIONS contains an invalid NUL/newline")
    options = OrderedDict()
    for item in text.split(";"):
        item = item.strip()
        if not item:
            raise ValueError("BACKEND_OPTIONS contains an empty item")
        if "=" not in item:
            raise ValueError("backend option '%s' must use section.key=value" % item)
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not re.match(r'^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$', name):
            raise ValueError("invalid backend option name '%s'" % name)
        if name in options:
            raise ValueError("duplicate backend option '%s'" % name)
        options[name] = value
    return options


def normalize_backend_options(cfg):
    """Normalize backend-specific settings and expand safe defaults into the effective config."""
    backend = cfg["BACKEND"].strip().lower()
    supplied = parse_backend_options(cfg.get("BACKEND_OPTIONS", ""))
    legacy_custom = cfg.get("CROWSNEST_CUSTOM_FLAGS", "")
    if legacy_custom.strip():
        if "cam1.custom_flags" in supplied:
            raise ValueError("CROWSNEST_CUSTOM_FLAGS duplicates BACKEND_OPTIONS cam1.custom_flags")
        supplied["cam1.custom_flags"] = legacy_custom.strip()
    if backend != "crowsnest" and supplied:
        raise ValueError("BACKEND_OPTIONS are supported only by backend crowsnest")
    rules = BACKEND_OPTION_RULES.get(backend, {})
    for name, value in supplied.items():
        rule = rules.get(name)
        if rule is None:
            raise ValueError("backend option '%s' is not supported by %s" % (name, backend))
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("backend option '%s' contains invalid NUL/newline" % name)
        if rule == "bool" and value.lower() not in ("true", "false"):
            raise ValueError("backend option '%s' must be true or false" % name)
        if rule == "false_only" and value.lower() != "false":
            raise ValueError("backend option '%s' must remain false; QIDI webcam endpoint is local" % name)
        if rule == "log_level" and value.lower() not in ("quiet", "verbose", "debug"):
            raise ValueError("backend option '%s' must be quiet, verbose or debug" % name)
        if rule == "mode" and value.lower() not in ("mjpg", "mjpeg"):
            raise ValueError("backend option '%s' must be mjpg or mjpeg" % name)
        if rule == "path":
            if not value.startswith("/"):
                raise ValueError("backend option '%s' must be an absolute path" % name)
            if len(value) > 240:
                raise ValueError("backend option '%s' path is too long" % name)
        if name in ("crowsnest.log_path", "crowsnest.log_level", "crowsnest.delete_log",
                    "crowsnest.no_proxy", "cam1.mode") and not value:
            raise ValueError("backend option '%s' cannot be empty" % name)

    if backend == "crowsnest":
        effective = OrderedDict(DEFAULT_BACKEND_OPTIONS)
        effective.update(supplied)
    else:
        effective = OrderedDict()
    cfg["BACKEND_OPTIONS"] = ";".join("%s=%s" % (k, v) for k, v in effective.items())
    cfg["_backend_options_map"] = effective
    cfg.pop("CROWSNEST_CUSTOM_FLAGS", None)
    return cfg


def backend_options_map(cfg):
    try:
        return cfg["_backend_options_map"]
    except KeyError:
        return parse_backend_options(cfg.get("BACKEND_OPTIONS", ""))


def camera_capability_check(device, resolution, fps):
    if not os.path.exists(V4L2_CTL) or not os.access(V4L2_CTL, os.X_OK):
        return True, ""
    try:
        p = subprocess.Popen([V4L2_CTL, "-d", device, "--list-formats-ext"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = p.communicate()
        if p.returncode != 0:
            return True, ""
        text = out.decode("utf-8", "replace")
    except Exception:
        return True, ""

    wanted = resolution.lower()
    lines = text.splitlines()
    in_mjpg = False
    found_resolution = False
    max_fps = None
    any_mjpg = False
    res_re = re.compile(r'Size:\s+Discrete\s+(\d+)x(\d+)', re.I)
    fps_re = re.compile(r'\(([0-9]+(?:\.[0-9]+)?)\s*fps\)', re.I)
    for line in lines:
        upper = line.upper()
        if "'MJPG'" in upper or "'MJPEG'" in upper:
            in_mjpg = True
            any_mjpg = True
            continue
        if in_mjpg and "'" in line and "MJPG" not in upper and "MJPEG" not in upper:
            in_mjpg = False
        if in_mjpg:
            rm = res_re.search(line)
            if rm:
                current = rm.group(1) + "x" + rm.group(2)
                if current.lower() == wanted:
                    found_resolution = True
                    max_fps = None
                elif found_resolution:
                    break
            if found_resolution:
                fm = fps_re.search(line)
                if fm:
                    val = float(fm.group(1))
                    max_fps = val if max_fps is None else max(max_fps, val)
    if any_mjpg and not found_resolution:
        return False, "camera %s does not advertise MJPEG %s" % (device, resolution)
    if found_resolution and max_fps is not None and fps > max_fps + 1e-6:
        return False, "camera %s advertises MJPEG %s up to %.3g FPS; requested %s FPS" % (
            device, resolution, max_fps, fps)
    return True, ""


def active_backend():
    for name, meta in BACKENDS.items():
        rc, _, _ = systemctl("is-active", "--quiet", meta["service"])
        if rc == 0:
            return name
    return None




def parse_v4l2_controls(raw):
    """Parse comma-separated name=value V4L2 controls."""
    if raw is None:
        return OrderedDict()
    text = raw.strip()
    if not text:
        return OrderedDict()
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ValueError("V4L2_CONTROLS contains an invalid control string")
    controls = OrderedDict()
    for item in text.split(","):
        item = item.strip()
        if not item:
            raise ValueError("V4L2_CONTROLS contains an empty item")
        if "=" not in item:
            raise ValueError("V4L2 control '%s' must use name=value" % item)
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not re.match(r'^[A-Za-z0-9_.-]+$', name):
            raise ValueError("invalid V4L2 control name '%s'" % name)
        if not re.match(r'^-?\d+$', value):
            raise ValueError("V4L2 control '%s' must use a numeric value" % name)
        if name in controls:
            raise ValueError("duplicate V4L2 control '%s'" % name)
        controls[name] = int(value)
    return controls


def read_v4l2_controls(device):
    """Return capability metadata keyed by V4L2 control name."""
    if not os.path.exists(V4L2_CTL) or not os.access(V4L2_CTL, os.X_OK):
        return None
    try:
        p = subprocess.Popen([V4L2_CTL, "-d", device, "--list-ctrls-menus"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        if p.returncode != 0:
            return None
        text = out.decode("utf-8", "replace")
    except Exception:
        return None

    controls = OrderedDict()
    # v4l2-ctl prints one control per line, but bool controls may omit min/max/step.
    header_re = re.compile(
        r'^\s*([A-Za-z0-9_.-]+)\s+0x[0-9A-Fa-f]+\s+'
        r'\((int|bool|menu|button|integer64|bitmask|int-menu)\)\s*:\s*(.*)$', re.I)
    range_re = re.compile(r'\bmin=(-?\d+)\s+max=(-?\d+)(?:\s+step=(-?\d+))?\b', re.I)
    flags_re = re.compile(r'\bflags=([^\s]+)', re.I)
    for line in text.splitlines():
        m = header_re.match(line)
        if not m:
            continue
        name, kind, tail = m.group(1), m.group(2).lower(), m.group(3)
        rm = range_re.search(tail)
        if rm:
            lo, hi = int(rm.group(1)), int(rm.group(2))
            step = int(rm.group(3)) if rm.group(3) else 1
        elif kind == "bool":
            lo, hi, step = 0, 1, 1
        elif kind == "button":
            lo, hi, step = 0, 0, 1
        else:
            continue
        fm = flags_re.search(tail)
        controls[name] = {
            "kind": kind,
            "min": lo,
            "max": hi,
            "step": step,
            "flags": fm.group(1) if fm else "",
        }
    return controls


def validate_v4l2_controls(device, raw):
    controls = parse_v4l2_controls(raw)
    if not controls:
        return controls
    caps = read_v4l2_controls(device)
    if caps is None:
        # Runtime application/healthcheck remains authoritative when v4l2-ctl is unavailable.
        return controls
    for name, value in controls.items():
        if name not in caps:
            raise ValueError("V4L2 control '%s' is not available on %s" % (name, device))
        cap = caps[name]
        if cap["kind"] in ("button",):
            raise ValueError("V4L2 control '%s' is a button and cannot be configured as a value" % name)
        if value < cap["min"] or value > cap["max"]:
            raise ValueError("V4L2 control '%s' value %s outside range %s..%s" % (
                name, value, cap["min"], cap["max"]))
        if cap["step"] > 0 and ((value - cap["min"]) % cap["step"] != 0):
            raise ValueError("V4L2 control '%s' value %s does not match step %s" % (
                name, value, cap["step"]))
    return controls


def apply_v4l2_controls(device, controls):
    if not controls:
        return True, ""
    if not os.path.exists(V4L2_CTL) or not os.access(V4L2_CTL, os.X_OK):
        return True, "v4l2-ctl unavailable; skipped explicit V4L2 control application"
    for name, value in controls.items():
        try:
            p = subprocess.Popen([V4L2_CTL, "-d", device, "-c", "%s=%s" % (name, value)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate()
            if p.returncode != 0:
                return False, "failed to set V4L2 control %s=%s: %s" % (
                    name, value, err.decode("utf-8", "replace").strip() or out.decode("utf-8", "replace").strip())
        except Exception as exc:
            return False, "failed to set V4L2 control %s=%s: %s" % (name, value, exc)
    return True, ""


def verify_v4l2_controls(device, controls):
    if not controls or not os.path.exists(V4L2_CTL) or not os.access(V4L2_CTL, os.X_OK):
        return True, ""
    for name, expected in controls.items():
        try:
            p = subprocess.Popen([V4L2_CTL, "-d", device, "-C", name],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate()
            if p.returncode != 0:
                return False, "cannot read V4L2 control %s: %s" % (
                    name, err.decode("utf-8", "replace").strip())
            m = re.search(r':\s*(-?\d+)\s*$', out.decode("utf-8", "replace").strip())
            if not m:
                return False, "cannot parse current V4L2 control %s" % name
            actual = int(m.group(1))
            if actual != expected:
                return False, "V4L2 control %s expected %s, got %s" % (name, expected, actual)
        except Exception as exc:
            return False, "cannot verify V4L2 control %s: %s" % (name, exc)
    return True, ""

def validate_config(cfg):
    backend = cfg["BACKEND"].strip().lower()
    if backend == "auto":
        active = active_backend()
        backend = active if active in BACKENDS else "webcamd"
    if backend not in BACKENDS:
        raise ValueError("unsupported backend '%s' (allowed: %s)" % (backend, ", ".join(sorted(BACKENDS))))

    device = cfg["DEVICE"]
    if not device.startswith("/dev/"):
        raise ValueError("DEVICE must be an absolute /dev/... path")
    if not os.path.exists(device):
        raise ValueError("camera device does not exist: %s" % device)

    m = RES_RE.match(cfg["RESOLUTION"])
    if not m:
        raise ValueError("invalid RESOLUTION '%s' (expected WxH)" % cfg["RESOLUTION"])
    w, h = int(m.group(1)), int(m.group(2))
    if not (16 <= w <= 8192 and 16 <= h <= 8192):
        raise ValueError("resolution outside allowed range: %s" % cfg["RESOLUTION"])

    if not INT_RE.match(cfg["FPS"]):
        raise ValueError("FPS must be an integer")
    fps = int(cfg["FPS"])
    if not (1 <= fps <= 120):
        raise ValueError("FPS outside allowed range 1..120: %s" % fps)

    ok, reason = camera_capability_check(device, cfg["RESOLUTION"], fps)
    if not ok:
        raise ValueError(reason)

    if cfg["HOST"] != "127.0.0.1":
        raise ValueError("HOST must remain 127.0.0.1; QIDI nginx expects a local camera backend")
    if cfg["PORT"] != "8080":
        raise ValueError("PORT must remain 8080; QIDI nginx /webcam/ maps to 8080")

    controls_raw = cfg.get("V4L2_CONTROLS", "")
    controls = validate_v4l2_controls(device, controls_raw)
    cfg["V4L2_CONTROLS"] = ",".join("%s=%s" % (k, v) for k, v in controls.items())

    cfg["BACKEND"] = backend
    cfg = normalize_backend_options(cfg)
    return cfg


def quote_value(value):
    value = str(value)
    return value.replace("\\", "\\\\").replace('"', '\\"')


def backend_options_text(cfg):
    return cfg.get("BACKEND_OPTIONS", "")


def cfg_text(cfg):
    return (
        "# QCM known-good configuration (root-only)\n"
        'QCM_BACKEND="%s"\n'
        'QCM_DEVICE="%s"\n'
        'QCM_RESOLUTION="%s"\n'
        'QCM_FPS="%s"\n'
        'QCM_HOST="%s"\n'
        'QCM_PORT="%s"\n'
        'QCM_V4L2_CONTROLS="%s"\n'
        'QCM_BACKEND_OPTIONS="%s"\n'
        'camera_usb_options="-r %s -f %s -d %s"\n'
    ) % (
        quote_value(cfg["BACKEND"]), quote_value(cfg["DEVICE"]), quote_value(cfg["RESOLUTION"]),
        quote_value(cfg["FPS"]), quote_value(cfg["HOST"]), quote_value(cfg["PORT"]),
        quote_value(cfg.get("V4L2_CONTROLS", "")), quote_value(backend_options_text(cfg)),
        quote_value(cfg["RESOLUTION"]), quote_value(cfg["FPS"]), quote_value(cfg["DEVICE"]),
    )


def active_block(cfg):
    return [
        "# QCM ACTIVE CONFIGURATION",
        'QCM_BACKEND="%s"' % quote_value(cfg["BACKEND"]),
        'QCM_DEVICE="%s"' % quote_value(cfg["DEVICE"]),
        'QCM_RESOLUTION="%s"' % quote_value(cfg["RESOLUTION"]),
        'QCM_FPS="%s"' % quote_value(cfg["FPS"]),
        'QCM_HOST="%s"' % quote_value(cfg["HOST"]),
        'QCM_PORT="%s"' % quote_value(cfg["PORT"]),
        'QCM_V4L2_CONTROLS="%s"' % quote_value(cfg.get("V4L2_CONTROLS", "")),
        'QCM_BACKEND_OPTIONS="%s"' % quote_value(backend_options_text(cfg)),
        "# Legacy compatibility for QIDI webcamd:",
        'camera_usb_options="-r %s -f %s -d %s"' % (quote_value(cfg["RESOLUTION"]), quote_value(cfg["FPS"]), quote_value(cfg["DEVICE"])),
    ]


def last_good_block(cfg):
    return [
        LAST_GOOD_BEGIN.rstrip("\n"),
        "# These lines are a READONLY MIRROR of the root-only known_good.conf.",
        "# Do not edit; QCM repairs this block from the root-only copy.",
        '# QCM_BACKEND="%s"' % quote_value(cfg["BACKEND"]),
        '# QCM_DEVICE="%s"' % quote_value(cfg["DEVICE"]),
        '# QCM_RESOLUTION="%s"' % quote_value(cfg["RESOLUTION"]),
        '# QCM_FPS="%s"' % quote_value(cfg["FPS"]),
        '# QCM_HOST="%s"' % quote_value(cfg["HOST"]),
        '# QCM_PORT="%s"' % quote_value(cfg["PORT"]),
        '# QCM_V4L2_CONTROLS="%s"' % quote_value(cfg.get("V4L2_CONTROLS", "")),
        '# QCM_BACKEND_OPTIONS="%s"' % quote_value(backend_options_text(cfg)),
        '# camera_usb_options="-r %s -f %s -d %s"' % (quote_value(cfg["RESOLUTION"]), quote_value(cfg["FPS"]), quote_value(cfg["DEVICE"])),
        LAST_GOOD_END.rstrip("\n"),
    ]


def render_public_config(original, cfg, include_mirror=True):
    """Preserve QIDI/user comments while normalizing the QCM active block and mirror."""
    lines = original.splitlines()
    out = []
    in_mirror = False
    mirror_changed = False
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line == LAST_GOOD_BEGIN.rstrip("\n"):
            in_mirror = True
            mirror_changed = True
            continue
        if in_mirror:
            if line == LAST_GOOD_END.rstrip("\n"):
                in_mirror = False
            continue
        if ANY_QCM_RE.match(line):
            continue
        if LEGACY_RE.match(line):
            continue
        out.append(line)

    while out and out[-1] == "":
        out.pop()
    out.append("")
    if include_mirror:
        out.extend(last_good_block(cfg))
        out.append("")
    out.extend(active_block(cfg))
    out.append("")
    return "\n".join(out)


def crowsnest_text(cfg):
    opts = OrderedDict(DEFAULT_BACKEND_OPTIONS)
    opts.update(backend_options_map(cfg))
    lines = [
        "[crowsnest]",
        "log_path: {0}".format(opts["crowsnest.log_path"]),
        "log_level: {0}".format(opts["crowsnest.log_level"]),
        "delete_log: {0}".format(opts["crowsnest.delete_log"]),
        "no_proxy: {0}".format(opts["crowsnest.no_proxy"]),
        "",
        "[cam 1]",
        "mode: {0}".format(opts["cam1.mode"]),
        "port: {port}".format(port=cfg["PORT"]),
        "device: {device}".format(device=cfg["DEVICE"]),
        "resolution: {resolution}".format(resolution=cfg["RESOLUTION"]),
        "max_fps: {fps}".format(fps=cfg["FPS"]),
    ]
    controls = cfg.get("V4L2_CONTROLS", "")
    if controls:
        lines.append("v4l2ctl: {0}".format(controls))
    if "cam1.custom_flags" in opts and opts["cam1.custom_flags"]:
        lines.append("custom_flags: {0}".format(opts["cam1.custom_flags"]))
    return "\n".join(lines) + "\n"

def systemctl(*args, **kwargs):
    check = kwargs.pop("check", False)
    cmd = ["systemctl"] + list(args)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    if check and p.returncode != 0:
        raise RuntimeError("%s failed: %s" % (" ".join(cmd), err.decode("utf-8", "replace").strip()))
    return p.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def healthcheck(cfg, service, timeout=8.0):
    deadline = time.time() + timeout
    last = "service inactive"
    while time.time() < deadline:
        rc, _, _ = systemctl("is-active", service)
        if rc != 0:
            last = "service %s is not active" % service
            time.sleep(0.25)
            continue
        try:
            p = subprocess.Popen(
                ["curl", "-sS", "--max-time", "3", "-o", "/tmp/qcm-health.jpg",
                 "http://127.0.0.1:8080/?action=snapshot"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, err = p.communicate()
            if p.returncode != 0:
                last = "snapshot request failed: %s" % err.decode("utf-8", "replace").strip()
                time.sleep(0.25); continue
            with open("/tmp/qcm-health.jpg", "rb") as f:
                if not f.read(16).startswith(b"\xff\xd8\xff"):
                    last = "snapshot did not return JPEG data"; time.sleep(0.25); continue

            p = subprocess.Popen(
                ["curl", "-sS", "--max-time", "3", "-o", "/tmp/qcm-health-nginx.jpg",
                 "http://127.0.0.1/webcam/?action=snapshot"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, err = p.communicate()
            if p.returncode != 0:
                last = "QIDI /webcam/ snapshot failed: %s" % err.decode("utf-8", "replace").strip()
                time.sleep(0.25); continue
            with open("/tmp/qcm-health-nginx.jpg", "rb") as f:
                if not f.read(16).startswith(b"\xff\xd8\xff"):
                    last = "QIDI /webcam/ did not return JPEG data"; time.sleep(0.25); continue

            p = subprocess.Popen(
                ["curl", "-sS", "--max-time", "2", "-o", "/tmp/qcm-health-stream.bin",
                 "http://127.0.0.1/webcam/?action=stream"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, err = p.communicate()
            size = os.path.getsize("/tmp/qcm-health-stream.bin") if os.path.exists("/tmp/qcm-health-stream.bin") else 0
            if size < 1024 or p.returncode not in (0, 28):
                last = "QIDI /webcam/ stream check failed (curl=%s, bytes=%s): %s" % (
                    p.returncode, size, err.decode("utf-8", "replace").strip())
                time.sleep(0.25); continue
            return True, "service + snapshots + QIDI /webcam/ MJPEG stream OK"
        except Exception as exc:
            last = str(exc)
        time.sleep(0.25)
    return False, last


def write_internal_config(cfg):
    if cfg["BACKEND"] == "crowsnest":
        atomic_write(CROWSNEST_CONFIG, crowsnest_text(cfg), 0o644)


def disable_managed_backends():
    for backend in BACKENDS:
        systemctl("disable", BACKENDS[backend]["service"])


def stop_backend(name):
    if name in BACKENDS:
        systemctl("stop", BACKENDS[name]["service"])


def start_backend(name):
    service = BACKENDS[name]["service"]
    systemctl("daemon-reload")
    systemctl("start", service, check=True)


def stop_all_except(name=None):
    for backend in BACKENDS:
        if backend != name:
            systemctl("stop", BACKENDS[backend]["service"])


def send_klippy(script):
    if not os.path.exists(KLIPPY_UDS):
        return False, "Klipper UDS not found: %s" % KLIPPY_UDS
    payload = json.dumps({"id": 1, "method": "gcode/script", "params": {"script": script}}).encode("utf-8") + b"\x03"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    try:
        sock.connect(KLIPPY_UDS)
        sock.sendall(payload)
        try:
            sock.recv(4096)
        except socket.timeout:
            pass
        return True, "ok"
    except Exception as exc:
        return False, str(exc)
    finally:
        sock.close()


def send_moonraker_gcode(script):
    payload = json.dumps({"script": script}).encode("utf-8")
    try:
        p = subprocess.Popen(
            ["curl", "-sS", "--max-time", "3", "-X", "POST",
             "-H", "Content-Type: application/json",
             "--data-binary", payload.decode("utf-8"), MOONRAKER_URL],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        if p.returncode == 0:
            return True, "moonraker HTTP OK"
        return False, err.decode("utf-8", "replace").strip() or ("curl exit %s" % p.returncode)
    except Exception as exc:
        return False, str(exc)


def notification_script(short_msg, detail):
    safe_short = short_msg.replace("\n", " ").replace("\r", " ")[:55]
    safe_detail = detail.replace("\n", " ").replace("\r", " ").replace('"', "'")[:220]
    return 'M117 %s\nRESPOND TYPE=error MSG="QCM: %s"' % (safe_short, safe_detail)


def notify_error(short_msg, detail):
    script = notification_script(short_msg, detail)
    ok, reason = send_moonraker_gcode(script)
    if ok:
        log("notification sent via Moonraker")
        return True
    ok2, reason2 = send_klippy(script)
    if ok2:
        log("notification sent via Klipper UDS fallback")
        return True
    log("warning: notification delivery failed: Moonraker=%s; UDS=%s" % (reason, reason2))
    return False


def write_status(state, **extra):
    # Keep the most recent error permanently visible in status.json. A transient
    # RESPOND/M117 message may disappear from the UI, but the machine state should
    # retain the diagnostic until a later error replaces it.
    previous = {}
    try:
        if os.path.isfile(STATUS_PATH):
            with open(STATUS_PATH, "r") as f:
                previous = json.load(f)
    except Exception:
        previous = {}

    d = OrderedDict()
    d["version"] = VERSION
    d["timestamp"] = int(time.time())
    d["state"] = state
    previous_error = previous.get("last_error")
    if previous_error and "last_error" not in extra:
        d["last_error"] = previous_error
    d.update(extra)
    try:
        atomic_write(STATUS_PATH, json.dumps(d, indent=2, sort_keys=False) + "\n", 0o644)
    except Exception as exc:
        log("warning: cannot write status: %s" % exc)


def save_rejected(raw_text, reason):
    try:
        atomic_write(REJECTED_PATH, raw_text, 0o644)
        atomic_write(REJECTED_REASON_PATH, reason.strip() + "\n", 0o644)
    except Exception as exc:
        log("warning: cannot save rejected config: %s" % exc)


def ensure_state_dir():
    if not os.path.isdir(STATE_DIR):
        os.makedirs(STATE_DIR)
    try:
        os.chmod(STATE_DIR, 0o700)
    except OSError:
        pass


def load_known_good():
    path = KNOWN_GOOD_PATH
    if not os.path.isfile(path) and os.path.isfile(LEGACY_ACCEPTED_PATH):
        # One-time migration from the old state model.
        try:
            cfg = validate_config(parse_public_config(LEGACY_ACCEPTED_PATH))
            atomic_write(path, cfg_text(cfg), 0o600)
            log("migrated legacy accepted.conf to root-only known_good.conf")
        except Exception:
            pass
    if not os.path.isfile(path):
        return None
    try:
        return validate_config(parse_public_config(path))
    except Exception as exc:
        log("warning: invalid known_good.conf: %s" % exc)
        return None


def snapshot_user_config():
    with open(CONFIG_PATH, "r") as f:
        return f.read()


def write_public_with_good(original_text, good_cfg):
    rendered = render_public_config(original_text, good_cfg, include_mirror=True)
    # webcam.txt must remain writable by the WebUI/mks; preserve existing owner/mode.
    atomic_write(CONFIG_PATH, rendered, 0o644, preserve_owner=True)


def mirror_matches(text, good_cfg):
    expected = "\n".join(last_good_block(good_cfg)) + "\n"
    start = text.find(LAST_GOOD_BEGIN.rstrip("\n"))
    if start < 0:
        return False
    end = text.find(LAST_GOOD_END.rstrip("\n"), start)
    if end < 0:
        return False
    end_line = end + len(LAST_GOOD_END.rstrip("\n"))
    actual = text[start:end_line] + "\n"
    return actual == expected


def replace_last_good_mirror(text, good_cfg):
    block = "\n".join(last_good_block(good_cfg))
    begin = LAST_GOOD_BEGIN.rstrip("\n")
    end = LAST_GOOD_END.rstrip("\n")
    start = text.find(begin)
    if start >= 0:
        finish = text.find(end, start)
        if finish >= 0:
            finish += len(end)
            return text[:start] + block + text[finish:]
    lines = text.splitlines()
    while lines and lines[-1] == "":
        lines.pop()
    lines.extend(["", block, ""])
    return "\n".join(lines)


def repair_public_mirror(good_cfg):
    try:
        current = snapshot_user_config()
        if mirror_matches(current, good_cfg):
            return False
        repaired = replace_last_good_mirror(current, good_cfg)
        atomic_write(CONFIG_PATH, repaired, 0o644, preserve_owner=True)
        log("repaired last-good mirror from root-only known_good.conf")
        return True
    except Exception as exc:
        log("warning: cannot repair last-good mirror: %s" % exc)
        return False


def commit_good(candidate_text, candidate_cfg):
    # Root-only source of truth first; after this point the machine always has a
    # known-good configuration even if the user-facing file write is interrupted.
    atomic_write(KNOWN_GOOD_PATH, cfg_text(candidate_cfg), 0o600)
    rendered = render_public_config(candidate_text, candidate_cfg, include_mirror=True)
    atomic_write(CONFIG_PATH, rendered, 0o644, preserve_owner=True)


def apply_config(candidate, known_good, dry_run=False):
    candidate_user_text = snapshot_user_config()
    candidate_user_hash = hashlib.sha256(candidate_user_text.encode("utf-8")).hexdigest()
    old_backend = known_good["BACKEND"] if known_good else active_backend()
    controls = parse_v4l2_controls(candidate.get("V4L2_CONTROLS", ""))
    log("applying backend=%s device=%s resolution=%s fps=%s" % (
        candidate["BACKEND"], candidate["DEVICE"], candidate["RESOLUTION"], candidate["FPS"]))
    if dry_run:
        log("dry-run: would stop old backend, generate internal config, start candidate, health-check, commit")
        return True

    write_status("APPLYING", backend=candidate["BACKEND"], candidate=candidate,
                 last_good=(known_good if known_good else None))
    try:
        write_internal_config(candidate)
        disable_managed_backends()
        stop_all_except(None)
        time.sleep(0.2)
        start_backend(candidate["BACKEND"])
        ok, reason = apply_v4l2_controls(candidate["DEVICE"], controls)
        if not ok:
            raise RuntimeError(reason)
        ok, reason = healthcheck(candidate, BACKENDS[candidate["BACKEND"]]["service"])
        if not ok:
            raise RuntimeError(reason)
        ok, reason = verify_v4l2_controls(candidate["DEVICE"], controls)
        if not ok:
            raise RuntimeError(reason)
        latest_hash = file_hash(CONFIG_PATH)
        if latest_hash != candidate_user_hash:
            raise ConcurrentConfigChange("configuration changed again while candidate was being applied")
        commit_good(candidate_user_text, candidate)
        write_status("RUNNING", backend=candidate["BACKEND"], config=candidate,
                     last_good=candidate)
        log("apply OK")
        return True
    except ConcurrentConfigChange as exc:
        log("candidate became stale: %s" % exc)
        stop_backend(candidate["BACKEND"])
        if old_backend in BACKENDS:
            try:
                if known_good:
                    write_internal_config(known_good)
                old_controls = parse_v4l2_controls(known_good.get("V4L2_CONTROLS", "")) if known_good else OrderedDict()
                start_backend(old_backend)
                if known_good:
                    ok, rollback_controls_reason = apply_v4l2_controls(known_good["DEVICE"], old_controls)
                    if not ok:
                        raise RuntimeError(rollback_controls_reason)
                if known_good:
                    ok, rollback_health_reason = healthcheck(known_good, BACKENDS[old_backend]["service"])
                    if not ok:
                        raise RuntimeError(rollback_health_reason)
                    ok, rollback_ctrl_reason = verify_v4l2_controls(known_good["DEVICE"], parse_v4l2_controls(known_good.get("V4L2_CONTROLS", "")))
                    if not ok:
                        raise RuntimeError(rollback_ctrl_reason)
            except Exception as rollback_exc:
                log("runtime restore after concurrent edit failed: %s" % rollback_exc)
        write_status("APPLYING", backend=old_backend,
                     note="newer config save detected; waiting for next apply")
        return False
    except Exception as exc:
        reason = str(exc)
        log("apply FAILED: %s" % reason)
        try:
            save_rejected(snapshot_user_config(), reason)
        except Exception:
            pass
        if known_good:
            try:
                current = snapshot_user_config()
                write_public_with_good(current, known_good)
            except Exception as restore_exc:
                log("config rollback failed: %s" % restore_exc)
            try:
                write_internal_config(known_good)
            except Exception as internal_exc:
                log("internal backend config rollback failed: %s" % internal_exc)
            stop_backend(candidate["BACKEND"])
            try:
                old_controls = parse_v4l2_controls(known_good.get("V4L2_CONTROLS", ""))
                start_backend(known_good["BACKEND"])
                ok, old_ctrl_apply_reason = apply_v4l2_controls(known_good["DEVICE"], old_controls)
                if not ok:
                    raise RuntimeError(old_ctrl_apply_reason)
                ok, old_reason = healthcheck(known_good, BACKENDS[known_good["BACKEND"]]["service"])
                if not ok:
                    log("rollback backend health check FAILED: %s" % old_reason)
                ok, old_ctrl_reason = verify_v4l2_controls(known_good["DEVICE"], old_controls)
                if not ok:
                    log("rollback V4L2 control check FAILED: %s" % old_ctrl_reason)
            except Exception as rollback_exc:
                log("runtime rollback failed: %s" % rollback_exc)
        else:
            # No stored rollback point yet. Best effort: restart the backend that
            # was active before the transaction if one existed.
            stop_backend(candidate["BACKEND"])
            if old_backend in BACKENDS:
                try:
                    start_backend(old_backend)
                except Exception:
                    pass
        write_status("ERROR", backend=(known_good["BACKEND"] if known_good else old_backend),
                     error=reason, last_error=OrderedDict([
                         ("time", int(time.time())),
                         ("reason", reason),
                         ("restored", bool(known_good)),
                     ]), restored=bool(known_good))
        notify_error("QCM ERROR: camera config restored", reason)
        return False


class Inotify(object):
    IN_CLOSE_WRITE = 0x00000008
    IN_MOVED_TO = 0x00000080
    IN_CREATE = 0x00000100
    IN_ATTRIB = 0x00000004

    def __init__(self, directory):
        libc_name = ctypes.util.find_library("c") or "libc.so.6"
        self.libc = ctypes.CDLL(libc_name, use_errno=True)
        self.libc.inotify_init1.argtypes = [ctypes.c_int]
        self.libc.inotify_init1.restype = ctypes.c_int
        self.libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self.libc.inotify_add_watch.restype = ctypes.c_int
        fd = self.libc.inotify_init1(0)
        if fd < 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
        self.fd = fd
        wd = self.libc.inotify_add_watch(
            self.fd, directory.encode("utf-8"),
            self.IN_CLOSE_WRITE | self.IN_MOVED_TO | self.IN_CREATE | self.IN_ATTRIB,
        )
        if wd < 0:
            err = ctypes.get_errno()
            os.close(self.fd)
            raise OSError(err, os.strerror(err))

    def events(self, timeout=1.0):
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return []
        raw = os.read(self.fd, 65536)
        events = []
        pos = 0
        header_size = 16
        while pos + header_size <= len(raw):
            wd, mask, cookie, length = __import__("struct").unpack_from("iIII", raw, pos)
            pos += header_size
            name = raw[pos:pos + length].split(b"\0", 1)[0].decode("utf-8", "replace") if length else ""
            pos += length
            events.append((mask, name))
        return events

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


def wait_settle(path, seconds=0.35):
    time.sleep(seconds)
    for _ in range(10):
        try:
            a = file_hash(path)
            time.sleep(0.05)
            b = file_hash(path)
            if a == b:
                return
        except OSError:
            time.sleep(0.05)


def bootstrap(known_good):
    # Never overwrite the editable ACTIVE configuration on startup merely because
    # the mirror was tampered with. The root-only known_good is authoritative only
    # for the commented mirror and for rollback after validation/apply failure.
    if known_good:
        repair_public_mirror(known_good)

    try:
        cfg = validate_config(parse_public_config(CONFIG_PATH))
    except Exception as exc:
        reason = str(exc)
        if known_good:
            try:
                save_rejected(snapshot_user_config(), reason)
                current = snapshot_user_config()
                write_public_with_good(current, known_good)
                write_internal_config(known_good)
                disable_managed_backends()
                stop_all_except(known_good["BACKEND"])
                old_controls = parse_v4l2_controls(known_good.get("V4L2_CONTROLS", ""))
                start_backend(known_good["BACKEND"])
                ok, rollback_ctrl_reason = apply_v4l2_controls(known_good["DEVICE"], old_controls)
                if not ok:
                    raise RuntimeError(rollback_ctrl_reason)
                ok, rollback_reason = healthcheck(known_good, BACKENDS[known_good["BACKEND"]]["service"])
                if ok:
                    ok, rollback_ctrl_reason = verify_v4l2_controls(known_good["DEVICE"], old_controls)
                    if not ok:
                        rollback_reason = rollback_ctrl_reason
                if not ok:
                    reason = "%s; rollback healthcheck failed: %s" % (reason, rollback_reason)
            except Exception as rollback_exc:
                log("boot rollback failed: %s" % rollback_exc)
            notify_error("QCM ERROR: invalid camera config restored", reason)
            write_status("ERROR", backend=known_good["BACKEND"], error=reason,
                         last_error=OrderedDict([
                             ("time", int(time.time())),
                             ("reason", reason),
                             ("restored", True),
                         ]), restored=True)
            return known_good
        notify_error("QCM ERROR: invalid camera config", reason)
        write_status("ERROR", error=reason,
                     last_error=OrderedDict([
                         ("time", int(time.time())),
                         ("reason", reason),
                         ("restored", False),
                     ]), restored=False)
        return None

    disable_managed_backends()

    if known_good is None:
        active = active_backend()
        if active == cfg["BACKEND"]:
            ok, _ = healthcheck(cfg, BACKENDS[active]["service"])
            if ok:
                known_good = cfg
                atomic_write(KNOWN_GOOD_PATH, cfg_text(cfg), 0o600)
                write_public_with_good(snapshot_user_config(), cfg)
                log("boot: existing backend is healthy; adopted as last-good")
                write_status("RUNNING", backend=active, config=cfg, last_good=cfg)
                return known_good
        apply_config(cfg, None)
        return cfg if active_backend() == cfg["BACKEND"] else None

    # Ensure that no other managed backend remains running. If the requested
    # backend is already healthy, keep it running and avoid a needless restart.
    stop_all_except(cfg["BACKEND"])
    active = active_backend()
    if cfg != known_good or active != cfg["BACKEND"]:
        success = apply_config(cfg, known_good)
        return cfg if success else known_good

    ok, reason = healthcheck(cfg, BACKENDS[cfg["BACKEND"]]["service"])
    if not ok:
        log("boot: known-good backend is unhealthy: %s; re-applying" % reason)
        apply_config(cfg, known_good)
    else:
        write_status("RUNNING", backend=cfg["BACKEND"], config=cfg, last_good=known_good)
    return known_good


def run_daemon(dry_run=False, apply_once=False):
    ensure_state_dir()
    watch_dir = os.path.dirname(CONFIG_PATH)
    if not os.path.isdir(watch_dir):
        raise RuntimeError("config directory not found: %s" % watch_dir)

    known_good = load_known_good()
    requested = None
    requested_error = None
    if apply_once:
        try:
            requested = validate_config(parse_public_config(CONFIG_PATH))
        except Exception as exc:
            requested_error = str(exc)
    if dry_run:
        cfg = validate_config(parse_public_config(CONFIG_PATH))
        log("config OK: %s" % dict(cfg))
        apply_config(cfg, known_good or cfg, dry_run=True)
        return 0

    known_good = bootstrap(known_good)
    if apply_once:
        if requested_error is not None:
            log("apply-once rejected requested configuration: %s" % requested_error)
            return 2
        try:
            effective = validate_config(parse_public_config(CONFIG_PATH))
            active = active_backend()
            if requested != effective:
                log("apply-once rolled back requested configuration")
                return 1
            if active != effective["BACKEND"]:
                log("apply-once verification failed: active backend=%s, requested=%s" % (active, effective["BACKEND"]))
                return 1
            ok, reason = healthcheck(effective, BACKENDS[effective["BACKEND"]]["service"])
            if not ok:
                log("apply-once verification failed: %s" % reason)
                return 1
        except Exception as exc:
            log("apply-once verification failed: %s" % exc)
            return 1
        log("apply-once complete")
        return 0

    ino = Inotify(watch_dir)
    log("started v%s; watching %s" % (VERSION, CONFIG_PATH))
    try:
        pending = False
        while True:
            for mask, name in ino.events(timeout=1.0):
                if name != os.path.basename(CONFIG_PATH):
                    continue
                if mask & (Inotify.IN_CLOSE_WRITE | Inotify.IN_MOVED_TO | Inotify.IN_CREATE | Inotify.IN_ATTRIB):
                    pending = True
            if not pending:
                continue
            pending = False
            wait_settle(CONFIG_PATH)
            try:
                raw = snapshot_user_config()
                candidate = validate_config(parse_public_config(CONFIG_PATH))
            except Exception as exc:
                reason = str(exc)
                log("config rejected before apply: %s" % reason)
                if known_good:
                    try:
                        save_rejected(snapshot_user_config(), reason)
                    except Exception:
                        pass
                    try:
                        write_public_with_good(snapshot_user_config(), known_good)
                    except Exception as restore_exc:
                        log("config rollback failed: %s" % restore_exc)
                    notify_error("QCM ERROR: invalid camera config", reason)
                    write_status("ERROR", backend=known_good["BACKEND"], error=reason,
                                 last_error=OrderedDict([
                                     ("time", int(time.time())),
                                     ("reason", reason),
                                     ("restored", True),
                                 ]), restored=True)
                else:
                    notify_error("QCM ERROR: invalid camera config", reason)
                    write_status("ERROR", error=reason,
                                 last_error=OrderedDict([
                                     ("time", int(time.time())),
                                     ("reason", reason),
                                     ("restored", False),
                                 ]), restored=False)
                continue

            if candidate == known_good:
                repair_public_mirror(known_good)
                write_status("RUNNING", backend=known_good["BACKEND"], config=known_good, last_good=known_good)
                continue

            success = apply_config(candidate, known_good)
            if success:
                known_good = candidate
    finally:
        ino.close()


def self_test():
    """Pure local checks; never starts/stops services and never sends G-code."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "webcam.txt")
        source = (
            "# user comments\n"
            'QCM_BACKEND="crowsnest"\n'
            'QCM_DEVICE="/dev/null"\n'
            'QCM_RESOLUTION="1280x720"\n'
            'QCM_FPS="10"\n'
            'QCM_HOST="127.0.0.1"\n'
            'QCM_PORT="8080"\n'
            'QCM_V4L2_CONTROLS="brightness=0,contrast=1"\n'
            'QCM_BACKEND_OPTIONS="crowsnest.log_level=quiet;crowsnest.delete_log=true;crowsnest.no_proxy=false;cam1.mode=mjpg;cam1.custom_flags=--slowdown"\n'
            'camera_usb_options="-r 1280x720 -f 10 -d /dev/null"\n'
        )
        with open(path, "w") as f:
            f.write(source)
        cfg = parse_public_config(path)
        assert cfg["BACKEND"] == "crowsnest"
        assert cfg["DEVICE"] == "/dev/null"
        assert cfg["FPS"] == "10"
        rendered = render_public_config(source, cfg, include_mirror=True)
        assert "# QCM_BACKEND=\"crowsnest\"" in rendered
        assert 'QCM_BACKEND="crowsnest"' in rendered
        assert "QCM_QCM_" not in rendered
        assert "QCM_V4L2_CONTROLS" in rendered
        assert "QCM_BACKEND_OPTIONS" in rendered
        assert "[crowsnest]" in crowsnest_text(cfg)
        assert "log_path: /tmp/crowsnest.log" in crowsnest_text(cfg)
        assert "v4l2ctl: brightness=0,contrast=1" in crowsnest_text(cfg)
        assert "custom_flags: --slowdown" in crowsnest_text(cfg)
        assert "no_proxy: false" in crowsnest_text(cfg)
        assert parse_v4l2_controls("brightness=0,contrast=1")["brightness"] == 0
        normalized = normalize_backend_options({"BACKEND": "crowsnest", "BACKEND_OPTIONS": "cam1.mode=mjpg"})
        assert "crowsnest.log_path=/tmp/crowsnest.log" in normalized["BACKEND_OPTIONS"]
        assert "crowsnest.log_level=quiet" in normalized["BACKEND_OPTIONS"]
        assert "crowsnest.delete_log=true" in normalized["BACKEND_OPTIONS"]
        assert "crowsnest.no_proxy=false" in normalized["BACKEND_OPTIONS"]
        assert "cam1.mode=mjpg" in normalized["BACKEND_OPTIONS"]
        class FakePopen(object):
            returncode = 0
            def __init__(self, *args, **kwargs):
                pass
            def communicate(self):
                return (
                    b"power_line_frequency 0x00980918 (menu) : min=0 max=2 default=1 value=1\n"
                    b"brightness 0x00980900 (int) : min=-64 max=64 step=1 default=0 value=0\n", b""
                )
        old_popen = globals()["subprocess"].Popen
        old_exists = os.path.exists
        old_access = os.access
        try:
            globals()["subprocess"].Popen = FakePopen
            os.path.exists = lambda path: True
            os.access = lambda path, mode: True
            caps = read_v4l2_controls("/dev/video4")
            assert caps["power_line_frequency"]["max"] == 2
            assert caps["power_line_frequency"]["step"] == 1
        finally:
            globals()["subprocess"].Popen = old_popen
            os.path.exists = old_exists
            os.access = old_access
        try:
            parse_v4l2_controls("brightness=abc")
        except ValueError:
            pass
        else:
            raise AssertionError("non-numeric V4L2 value was accepted")

        opts = parse_backend_options("crowsnest.log_level=debug;cam1.mode=mjpg;cam1.custom_flags=--foo 1")
        assert opts["crowsnest.log_level"] == "debug"
        assert opts["cam1.custom_flags"] == "--foo 1"
        bad = dict(cfg)
        bad["BACKEND"] = "webcamd"
        bad["BACKEND_OPTIONS"] = "crowsnest.log_level=quiet"
        try:
            validate_config(bad)
        except Exception:
            pass
        # Validate-only test uses /dev/null, so no hardware access occurs beyond
        # the mocked control capability test above.

        tampered = rendered.replace('# QCM_FPS="10"', '# QCM_FPS="99"')
        fixed = replace_last_good_mirror(tampered, cfg)
        assert '# QCM_FPS="10"' in fixed
        assert 'QCM_FPS="10"' in fixed
        assert '# QCM_FPS="99"' not in fixed

        old_status = globals().get('STATUS_PATH')
        globals()['STATUS_PATH'] = os.path.join(td, 'status.json')
        try:
            write_status('ERROR', error='test error', last_error=OrderedDict([('reason', 'test error')]))
            write_status('RUNNING', backend='webcamd')
            with open(globals()['STATUS_PATH'], 'r') as f:
                saved = json.load(f)
            assert saved['last_error']['reason'] == 'test error'
        finally:
            globals()['STATUS_PATH'] = old_status
        old_snapshot_user_config = globals()["snapshot_user_config"]
        old_active_backend = globals()["active_backend"]
        old_write_status = globals()["write_status"]
        dry_run_status_calls = []

        try:
            globals()["snapshot_user_config"] = lambda: source
            globals()["active_backend"] = lambda: "crowsnest"
            globals()["write_status"] = (
                lambda *args, **kwargs: dry_run_status_calls.append((args, kwargs))
            )

            dry_candidate = OrderedDict(cfg)
            assert apply_config(dry_candidate, cfg, dry_run=True) is True
            assert dry_run_status_calls == []
        finally:
            globals()["snapshot_user_config"] = old_snapshot_user_config
            globals()["active_backend"] = old_active_backend
            globals()["write_status"] = old_write_status

        dup = source + 'QCM_FPS="20"\n'
        with open(path, "w") as f:
            f.write(dup)
        try:
            parse_public_config(path)
        except ValueError as exc:
            assert "duplicate QCM_FPS" in str(exc)
        else:
            raise AssertionError("duplicate QCM_FPS was not rejected")

    assert "M117 QCM TEST" in notification_script("QCM TEST", "detail")
    assert "RESPOND TYPE=error" in notification_script("QCM TEST", "detail")
    print("QCM self-test: OK")
    return 0

def show_status():
    if not os.path.isfile(STATUS_PATH):
        print("QCM STATUS: no status file")
        return 1

    try:
        with open(STATUS_PATH, "r") as f:
            status = json.load(f)
    except Exception as exc:
        print("QCM STATUS ERROR: %s" % exc, file=sys.stderr)
        return 2

    print("QCM status: %s" % status.get("state", "UNKNOWN"))
    print("Backend: %s" % status.get("backend", "unknown"))

    cfg = status.get("config") or {}
    if cfg:
        print("Camera: %s" % cfg.get("DEVICE", "unknown"))
        print("Mode: %sx%s @ %s FPS" % (
            cfg.get("RESOLUTION", "?").split("x")[0],
            cfg.get("RESOLUTION", "?").split("x")[-1],
            cfg.get("FPS", "?")
        ))
        print("Endpoint: http://%s:%s" % (
            cfg.get("HOST", "?"),
            cfg.get("PORT", "?")
        ))

    last_error = status.get("last_error")
    if last_error:
        reason = last_error.get("reason") if isinstance(last_error, dict) else last_error
        print("Last error: %s" % reason)

    return 0

def list_controls():
    if not os.path.exists(CONFIG_PATH):
        print("QCM: configuration file not found: %s" % CONFIG_PATH, file=sys.stderr)
        return 2
    try:
        cfg = validate_config(parse_public_config(CONFIG_PATH))
        caps = read_v4l2_controls(cfg["DEVICE"])
        if caps is None:
            print("QCM: v4l2-ctl unavailable or camera controls could not be queried", file=sys.stderr)
            return 2
        print(json.dumps(caps, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print("QCM CONTROL ERROR: %s" % exc, file=sys.stderr)
        return 2

def main(argv):
    dry_run = "--dry-run" in argv
    apply_once = "--apply-once" in argv
    check = "--check-config" in argv

    if "--help" in argv or "-h" in argv:
        print(
            "QCM - QIDI Camera Manager\n\n"
            "Usage:\n"
            "  qcm.py                 run daemon\n"
            "  qcm.py --check-config  validate webcam config\n"
            "  qcm.py --self-test     run internal tests\n"
            "  qcm.py --list-controls list V4L2 controls\n"
            "  qcm.py --status        show current saved status\n"
            "  qcm.py --apply-once    apply config once and exit\n"
            "  qcm.py --dry-run       validate without applying\n"
        )
        return 0

    known = {
        "--dry-run",
        "--apply-once",
        "--check-config",
        "--list-controls",
        "--self-test",
        "--help",
        "-h",
        "--status",
    }

    unknown = [arg for arg in argv if arg not in known]

    if unknown:
        print(
            "QCM ERROR: unknown argument(s): %s" %
            ", ".join(unknown),
            file=sys.stderr
        )
        return 2

    if "--status" in argv:
        return show_status()

    if "--list-controls" in argv:
        return list_controls()

    if "--self-test" in argv:
        try:
            return self_test()
        except Exception as exc:
            print("QCM SELF-TEST ERROR: %s" % exc, file=sys.stderr)
            return 3

    if check:
        try:
            cfg = validate_config(parse_public_config(CONFIG_PATH))
            print(json.dumps(cfg, indent=2, sort_keys=True))
            return 0
        except Exception as exc:
            print("QCM CONFIG ERROR: %s" % exc, file=sys.stderr)
            return 2

    try:
        return run_daemon(dry_run=dry_run, apply_once=apply_once)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        log("FATAL: %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
