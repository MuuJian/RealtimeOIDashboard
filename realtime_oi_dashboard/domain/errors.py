"""Internal control-flow signals for the realtime OI dashboard."""


class PollingStopped(Exception):
    """Cancel in-flight polling and HTTP retries during shutdown."""
