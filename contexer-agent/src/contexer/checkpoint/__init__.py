"""Per-attempt snapshots so a bad attempt can be undone exactly."""

from contexer.checkpoint.shadow import ShadowRepo, SnapshotError

__all__ = ["ShadowRepo", "SnapshotError"]
