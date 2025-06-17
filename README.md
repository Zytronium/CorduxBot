## **High-Level Features**

| Feature                   | Summary                                                                                   |
|---------------------------|-------------------------------------------------------------------------------------------|
| User-specific sandboxes   | Each user gets 1 or 2 ephemeral sandboxes, expires after 20 mins (extendable to 8h).      |
| Thread-based interaction  | A dedicated thread is created per sandbox for each user to interact securely.             |
| Auto-delete               | After timeout or on demand, sandboxes self-destruct.                                      |
| One-shot sandboxes        | Users can run a single command in a disposable sandbox.                                   |
| Global experiment sandbox | A shared 2-week rotating sandbox for all users with destructive command filtering.        |
| Live I/O                  | Global sandbox mirrors input/output to a chosen channel; listens to all user input there. |

---

## Commands Overview (Examples)

| Command                  | Description                                            |
|--------------------------|--------------------------------------------------------|
| `/sandbox start`         | Creates new sandbox for user.                          |
| `/sandbox enter`         | Opens a thread for user-specific terminal.             |
| `/sandbox extend <time>` | Extends sandbox TTL (max 8h).                          |
| `/sandbox delete`        | Immediately stops and removes sandbox.                 |
| `/run <cmd>`             | Runs one-time sandbox command and replies with output. |
| `/global join`           | Registers current channel as global sandbox I/O hub.   |

---

## Optional Cordux Stack

| Component          | Tool                                                |
|--------------------|-----------------------------------------------------|
| Sandbox containers | Docker with Alpine, Debian, or custom `cordux-base` |
| Bot language       | Python (discord.py + asyncio)                       |
| Scheduling         | `asyncio.sleep`, APScheduler, or cron               |
| Storage            | `sqlite` or `redis` (for TTL, container info)       |
| Logging            | File logs or Discord threads/log channels           |
| Filtering          | Regex + command parsing before passing to shell     |
