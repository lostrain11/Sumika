"""Runtime-neutral workspace inspection, checkpoint, diff, and recovery."""

from .runtime import WorkspaceError, WorkspaceRuntime

__all__ = ["WorkspaceError", "WorkspaceRuntime"]
