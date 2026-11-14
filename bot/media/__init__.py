"""Turning Telegram photos and voice notes into things the agent can read."""

# Telegram reports file sizes before download, so we can refuse big files
# without spending bandwidth or memory on them.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def too_big_message(size_bytes: int) -> str:
    """Friendly refusal text, e.g. 'That file is a bit big (12.3 MB)...'."""
    return (
        f"That file is a bit big ({size_bytes / 1024 / 1024:.1f} MB). "
        f"Please send something under {MAX_UPLOAD_BYTES // 1024 // 1024} MB."
    )
