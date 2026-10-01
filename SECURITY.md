# Security

QCM is intended to run inside the existing QIDI Q1 Pro local environment.

## Scope

Security-sensitive areas include:

- privileged systemd control;
- root-owned runtime state;
- the persistent installation backup;
- shell-compatible configuration parsing;
- local HTTP camera endpoints;
- bundled third-party Crowsnest/uStreamer runtime.

## Reporting a security issue

Do not publish an unpatched security-sensitive issue with exploit details in a public issue tracker.

Use the repository owner's preferred private reporting mechanism once one is configured for the project.

## Design expectations

Changes should avoid:

- storing passwords or sudo credentials;
- downloading executable code during installation;
- silently replacing unrelated system files;
- broadening HTTP exposure unnecessarily;
- disabling rollback protections.

The installer only asks sudo to elevate its own execution; the sudo password is not written to disk by QCM.
