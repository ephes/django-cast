from __future__ import annotations


class VoxhelmError(RuntimeError):
    """Raised when Voxhelm transcription or artifact retrieval fails."""


class VoxhelmConnectionError(VoxhelmError):
    """Raised when Voxhelm cannot be reached or drops the connection before answering."""
