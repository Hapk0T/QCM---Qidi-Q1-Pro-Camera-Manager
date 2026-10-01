# Contributing

## Before changing code

Read:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/INSTALLATION.md`
- `docs/DEVELOPMENT.md`
- `docs/TESTING.md`

The recovery contract is part of the project design, not an optional feature.

## Changes should preserve

1. stock QIDI `webcamd` as a rollback target;
2. offline installer operation;
3. Python 3.7 compatibility for the tested platform;
4. explicit backend ownership of `/dev/video4`;
5. validation before apply;
6. health check before commit;
7. persistent baseline backup behavior;
8. separation of user configuration and generated runtime state.

## Recommended validation

```bash
bash -n install.sh
python3 -m py_compile qcm.py
```

On a real printer, repeat the lifecycle described in `docs/TESTING.md` after changes affecting installation, backend switching, recovery or camera startup.

## Commit scope

Prefer small, reviewable changes.

Examples:

```text
fix: accept MJPEG timeout after received data
fix: preserve stock webcamd during uninstall
feat: add backend validation rule
refactor: isolate crowsnest config generation
```
