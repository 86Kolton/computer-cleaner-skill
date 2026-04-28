# Security Policy

This project is designed around conservative cleanup behavior:

- The bundled scanner is read-only and does not delete, move, rename, upload, or modify user files.
- Cleanup execution must be performed only after explicit per-item confirmation.
- Sensitive filenames, directory trees, screenshots, and file contents should stay local unless the user explicitly allows sharing.
- High-risk Windows, Docker, WSL, virtual machine, database, browser profile, and cloud-sync locations require separate confirmation and a rollback plan.

If you find a safety issue, open a GitHub issue with a minimal reproduction. Do not include private directory listings or personal files.
