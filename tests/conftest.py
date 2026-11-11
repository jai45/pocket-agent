"""Shared test setup.

config.py requires secrets at import time; tests never use real values or
the network, so dummy values are enough.
"""

import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
