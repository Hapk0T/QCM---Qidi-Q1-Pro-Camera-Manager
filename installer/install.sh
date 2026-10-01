#!/bin/bash
set -euo pipefail

VERSION="0.2.0-alpha1"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
INSTALL_ROOT="/opt/qidi-camera"
QCM_DIR="${INSTALL_ROOT}/qcm"
CN_DIR="${INSTALL_ROOT}/crowsnest"
CN_CONFIG_DIR="${INSTALL_ROOT}/config"
CN_CONFIG="${CN_CONFIG_DIR}/crowsnest.conf"
BACKUP_DIR="/home/mks/.qcm-backup"
CONFIG_PATH="/home/mks/klipper_config/webcam.txt"
WEBCAMD_BIN="/usr/local/bin/webcamd"
WEBCAMD_SERVICE="/etc/systemd/system/webcamd.service"
QCM_SERVICE="/etc/systemd/system/qcm.service"
CN_SERVICE="/etc/systemd/system/crowsnest-qidi.service"
LOCK_FILE="/run/lock/qcm-installer.lock"

log() { printf '[QCM installer] %s\n' "$*"; }
die() { printf '[QCM installer] ERROR: %s\n' "$*" >&2; exit 1; }

need_root() {
    if [ "$(id -u)" -eq 0 ]; then
        return 0
    fi

    command -v sudo >/dev/null 2>&1 || die "нужен sudo для запуска без root"
    sudo -v || die "не удалось получить права через sudo"
    exec sudo bash "$0" "$@"
}

check_base() {
    local arch py
    arch="$(dpkg --print-architecture 2>/dev/null || true)"
    [ "$arch" = "arm64" ] || die "нужна arm64, обнаружено: ${arch:-unknown}"
    command -v systemctl >/dev/null || die "systemctl не найден"
    command -v python3 >/dev/null || die "python3 не найден"
    command -v dpkg-query >/dev/null || die "dpkg-query не найден"
    py="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')" || die "python3 не запускается"
    [ "$py" = "3.7" ] || log "предупреждение: обнаружен Python ${py}, QCM тестировался на Python 3.7"
}

check_command_deps() {
    local c
    for c in crudini curl ffmpeg v4l2-ctl find xargs logger flock; do
        command -v "$c" >/dev/null || die "не найдена системная зависимость: ${c}"
    done
    for c in libevent-2.1-6 libevent-pthreads-2.1-6 libjpeg62-turbo; do
        dpkg-query -W -f='${Status}\n' "$c" 2>/dev/null | grep -qx 'install ok installed' \
            || die "не установлен системный пакет: ${c}"
    done
}

check_payload() {
    local f
    for f in \
        "$SCRIPT_DIR/qcm.py" \
        "$SCRIPT_DIR/qcm.service" \
        "$SCRIPT_DIR/crowsnest-qidi.service" \
        "$SCRIPT_DIR/webcam.txt.example" \
        "$SCRIPT_DIR/crowsnest/crowsnest" \
        "$SCRIPT_DIR/crowsnest/LICENSE" \
        "$SCRIPT_DIR/crowsnest/bin/ustreamer/ustreamer" \
        "$SCRIPT_DIR/crowsnest/bin/ustreamer/LICENSE"; do
        [ -f "$f" ] || die "отсутствует файл пакета: ${f#"$SCRIPT_DIR"/}"
    done

    # Archive formats created on Windows may not preserve Unix executable bits.
    # The installer applies the required modes during deployment.
    python3 -c 'import sys; compile(open(sys.argv[1], "r").read(), sys.argv[1], "exec")' "$SCRIPT_DIR/qcm.py" || die "qcm.py не проходит syntax check"
}

backup_ready() {
    [ -f "$BACKUP_DIR/manifest" ]
}

is_installed() {
    [ -e "$QCM_SERVICE" ] || [ -e "$CN_SERVICE" ] || [ -d "$QCM_DIR" ] || [ -d "$CN_DIR" ]
}

save_backup() {
    local enabled active uid gid mode exists

    backup_ready && return 0

    log "сохраняю исходное состояние в ${BACKUP_DIR}"
    install -d -m 700 "$BACKUP_DIR"

    if [ -f "$CONFIG_PATH" ]; then
        exists=1
        cp -a "$CONFIG_PATH" "$BACKUP_DIR/webcam.txt"
        uid="$(stat -c '%u' "$CONFIG_PATH")"
        gid="$(stat -c '%g' "$CONFIG_PATH")"
        mode="$(stat -c '%a' "$CONFIG_PATH")"
    else
        exists=0
        uid=0
        gid=0
        mode=644
        rm -f "$BACKUP_DIR/webcam.txt"
    fi

    enabled="$(systemctl is-enabled webcamd.service 2>/dev/null || true)"
    active="$(systemctl is-active webcamd.service 2>/dev/null || true)"

    case "$enabled" in
        enabled|disabled) ;;
        *) die "неподдерживаемое исходное состояние webcamd.service: is-enabled=${enabled:-unknown}" ;;
    esac
    case "$active" in
        active|inactive) ;;
        *) die "неподдерживаемое исходное состояние webcamd.service: is-active=${active:-unknown}" ;;
    esac

    {
        printf 'QCM_BACKUP_VERSION=1\n'
        printf 'CONFIG_EXISTS=%s\n' "$exists"
        printf 'CONFIG_UID=%s\n' "$uid"
        printf 'CONFIG_GID=%s\n' "$gid"
        printf 'CONFIG_MODE=%s\n' "$mode"
        printf 'WEBCAMD_ENABLED=%s\n' "$enabled"
        printf 'WEBCAMD_ACTIVE=%s\n' "$active"
    } > "$BACKUP_DIR/manifest"
    chmod 600 "$BACKUP_DIR/manifest"
}

load_backup() {
    backup_ready || die "нет исходного backup: ${BACKUP_DIR}"
    # shellcheck disable=SC1091
    . "$BACKUP_DIR/manifest"
    [ "${QCM_BACKUP_VERSION:-}" = "1" ] || die "неизвестный формат backup"
}

stop_our_stack() {
    systemctl stop qcm.service 2>/dev/null || true
    systemctl stop crowsnest-qidi.service 2>/dev/null || true
}

disable_stock_webcamd() {
    [ -f "$WEBCAMD_SERVICE" ] || die "штатный ${WEBCAMD_SERVICE} отсутствует"
    systemctl disable --now webcamd.service 2>/dev/null || true
}

install_payload() {
    log "устанавливаю QCM runtime"

    install -d -m 755 "$QCM_DIR" "$CN_CONFIG_DIR"
    install -d -m 755 "$INSTALL_ROOT"

    install -m 755 "$SCRIPT_DIR/qcm.py" "$QCM_DIR/qcm.py"
    install -m 644 "$SCRIPT_DIR/qcm.service" "$QCM_SERVICE"
    install -m 644 "$SCRIPT_DIR/crowsnest-qidi.service" "$CN_SERVICE"

    rm -rf "$CN_DIR"
    cp -a "$SCRIPT_DIR/crowsnest" "$CN_DIR"
    chmod 755 "$CN_DIR/crowsnest" "$CN_DIR/bin/ustreamer/ustreamer"

    # QCM writes the generated Crowsnest config itself.
    rm -f "$CN_CONFIG"
}

start_our_stack() {
    systemctl daemon-reload
    systemctl disable crowsnest-qidi.service >/dev/null 2>&1 || true
    systemctl enable qcm.service >/dev/null
    systemctl restart qcm.service
}

health_check() {
    local i snapshot stream rc snapshot_size stream_size
    snapshot="$(mktemp /tmp/qcm-installer-snapshot.XXXXXX.jpg)"
    stream="$(mktemp /tmp/qcm-installer-stream.XXXXXX.mjpg)"

    for i in $(seq 1 30); do
        rc=0
        curl -fsS --max-time 2 -o "$snapshot" 'http://127.0.0.1:8080/?action=snapshot' >/dev/null 2>&1 || rc=$?
        snapshot_size="$(stat -c '%s' "$snapshot" 2>/dev/null || echo 0)"

        if [ "$rc" -eq 0 ] && [ "$snapshot_size" -gt 1000 ]; then
            rc=0
            curl -fsS --max-time 2 -o "$stream" 'http://127.0.0.1:8080/?action=stream' >/dev/null 2>&1 || rc=$?
            stream_size="$(stat -c '%s' "$stream" 2>/dev/null || echo 0)"

            # MJPEG stream is intentionally endless: curl exits with 28 on timeout.
            if { [ "$rc" -eq 0 ] || [ "$rc" -eq 28 ]; } && [ "$stream_size" -gt 1000 ]; then
                rm -f "$snapshot" "$stream"
                return 0
            fi
        fi
        sleep 1
    done
    rm -f "$snapshot" "$stream"
    return 1
}

restore_config() {
    load_backup

    if [ "$CONFIG_EXISTS" = "1" ]; then
        install -d -m 755 "$(dirname "$CONFIG_PATH")"
        cp -a "$BACKUP_DIR/webcam.txt" "$CONFIG_PATH"
        chown "$CONFIG_UID:$CONFIG_GID" "$CONFIG_PATH"
        chmod "$CONFIG_MODE" "$CONFIG_PATH"
    else
        rm -f "$CONFIG_PATH"
    fi
}

restore_webcamd_state() {
    load_backup

    systemctl daemon-reload
    systemctl stop webcamd.service 2>/dev/null || true
    systemctl disable webcamd.service 2>/dev/null || true

    if [ "$WEBCAMD_ENABLED" = "enabled" ]; then
        systemctl enable webcamd.service >/dev/null
    fi

    if [ "$WEBCAMD_ACTIVE" = "active" ]; then
        systemctl start webcamd.service
    fi
}

restore_state() {
    log "восстанавливаю состояние до установки QCM"
    stop_our_stack
    systemctl disable qcm.service 2>/dev/null || true
    systemctl disable crowsnest-qidi.service 2>/dev/null || true
    restore_config
    restore_webcamd_state
}

remove_payload() {
    log "удаляю QCM runtime"
    systemctl stop qcm.service 2>/dev/null || true
    systemctl stop crowsnest-qidi.service 2>/dev/null || true
    systemctl disable qcm.service 2>/dev/null || true
    systemctl disable crowsnest-qidi.service 2>/dev/null || true

    rm -f "$QCM_SERVICE" "$CN_SERVICE"
    rm -rf "$QCM_DIR" "$CN_DIR"
    rm -f "$CN_CONFIG"
    rmdir "$CN_CONFIG_DIR" 2>/dev/null || true
    rmdir "$INSTALL_ROOT" 2>/dev/null || true
    systemctl daemon-reload
}

install_mode() {
    if is_installed; then
        die "обнаружена существующая установка QCM; используйте repair"
    fi

    if backup_ready; then
        log "использую ранее сохранённый исходный backup ${BACKUP_DIR}"
    else
        save_backup
    fi

    disable_stock_webcamd
    stop_our_stack
    install_payload

    # First install always activates the release configuration.
    # The original file and its metadata remain in BACKUP_DIR for restore/uninstall.
    install -d -m 755 "$(dirname "$CONFIG_PATH")"
    install -m 644 "$SCRIPT_DIR/webcam.txt.example" "$CONFIG_PATH"
    if [ "${CONFIG_EXISTS:-0}" = "1" ]; then
        chown "$CONFIG_UID:$CONFIG_GID" "$CONFIG_PATH"
        chmod "$CONFIG_MODE" "$CONFIG_PATH"
    fi

    start_our_stack

    health_check || die "healthcheck после установки не пройден"
    log "INSTALL OK — камера управляется QCM"
}

repair_mode() {
    backup_ready || die "repair невозможен: нет исходного backup"

    save_backup
    stop_our_stack
    disable_stock_webcamd
    install_payload
    start_our_stack

    health_check || die "healthcheck после repair не пройден"
    log "REPAIR OK"
}

restore_mode() {
    backup_ready || die "restore невозможен: нет исходного backup"
    restore_state
    log "RESTORE OK"
}

uninstall_mode() {
    backup_ready || die "uninstall невозможен: нет исходного backup"
    restore_state
    remove_payload
    log "UNINSTALL OK"
    log "backup сохранён в ${BACKUP_DIR}"
}

usage() {
    cat <<USAGE
QCM installer ${VERSION}

Использование:
  $0 install
  $0 repair
  $0 restore
  $0 uninstall
USAGE
}

main() {
    local mode="${1:-}"

    case "$mode" in
        -h|--help|help)
            usage
            exit 0
            ;;
        install|repair)
            ;;
        restore|uninstall)
            ;;
        *)
            usage
            exit 2
            ;;
    esac

    need_root "$@"

    install -d -m 755 /run/lock
    exec 9>"$LOCK_FILE"
    flock -n 9 || die "другой экземпляр установщика уже запущен"

    case "$mode" in
        install|repair)
            check_base
            check_command_deps
            check_payload
            ;;
        restore|uninstall)
            ;;
    esac

    case "$mode" in
        install) install_mode ;;
        repair) repair_mode ;;
        restore) restore_mode ;;
        uninstall) uninstall_mode ;;
    esac
}

main "$@"
