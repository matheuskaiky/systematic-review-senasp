from datetime import datetime, timezone


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
