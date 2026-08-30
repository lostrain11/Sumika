# Sumika DSH Desktop Automation

This package is the optional DSH bridge for Sumika's controlled desktop
automation runtime.  It exposes structured catalog, open, observe, act, close
and takeover tools while the Core owns application registration, leases,
permissions, idempotency and audit receipts.

The bridge does not discover arbitrary windows, invoke a shell, read desktop
credentials, or enable global mouse/keyboard input.  Application protocols and
Electron CDP are preferred; Windows UI Automation and foreground takeover stay
explicitly configured and approved.  Credential entry, login, deletion,
publishing, purchasing, upload and download actions remain human-confirmed.

Install only in a managed DSH profile after reviewing the package:

```powershell
dsh plugin --profile <profile> add file:<repo>\plugins\dsh-desktop-automation
```

The Sumika Core endpoint is loopback-only and can be overridden with
`SUMIKA_CORE_ENDPOINT`.  The package is MIT-licensed Sumika code and copies no
DSH, ZCode or third-party application source.
