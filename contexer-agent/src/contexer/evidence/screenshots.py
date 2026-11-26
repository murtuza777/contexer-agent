"""The screenshots of a run that may leave the machine: one per check of one contract.

A pull request can show them, so they are picked with care. The coding agent had a shell in the
checkout, and a result that names another file as a check's screenshot must not make Contexer
publish that file. A file counts only when it is inside the run's own folder and is the kind of
image the browser runner writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from contexer.gate.models import RunResult

# A page at JPEG quality 70 is a few hundred kilobytes; a file past this is not one of ours.
MAX_IMAGE_BYTES = 4_000_000
_MAGIC = {".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".png": b"\x89PNG\r\n\x1a\n"}


@dataclass(frozen=True)
class CheckScreenshot:
    check_id: str
    description: str
    passed: bool
    name: str  # the file's name where it is published: letters, digits, dots, dashes
    data: bytes


def image_in_run(
    path: str | Path | None, run_dir: str | Path, kinds: tuple[str, ...] = (".jpg",), limit: int | None = MAX_IMAGE_BYTES
) -> bytes | None:
    """The image at ``path``, or None unless it is inside ``run_dir`` and is an image of one of ``kinds``.

    The path is resolved first, so a link inside the run folder to a file outside it does not count.
    The first bytes are read too: a renamed ``.env`` is not an image. ``limit`` is for what gets
    published; the report on the machine has none.
    """
    if not path or not run_dir:
        return None
    try:
        file, folder = Path(path).resolve(), Path(run_dir).resolve()
        kind = file.suffix.lower()
        if kind not in kinds or not file.is_relative_to(folder) or not file.is_file():
            return None
        if limit is not None and file.stat().st_size > limit:
            return None
        data = file.read_bytes()
    except OSError:
        return None
    return data if (limit is None or len(data) <= limit) and data.startswith(_MAGIC[kind]) else None


def check_screenshots(result: RunResult | None, contract_id: str, run_dir: str | Path) -> list[CheckScreenshot]:
    """One screenshot per check of ``contract_id``: the page when the check was judged.

    For a failed check that is the last screen it reached. A trace is never used: it records request
    headers, and with them a signed-in session.
    """
    found: list[CheckScreenshot] = []
    for held in result.contracts if result is not None else []:
        if held.contract.id != contract_id or held.verification is None:
            continue
        for row in held.verification.criteria_results:
            data = image_in_run(row.check_result.screenshot, run_dir) if row.check_result is not None else None
            if data is None:
                continue
            stem = re.sub(r"[^A-Za-z0-9-]+", "-", row.criterion_id).strip("-") or "check"
            found.append(CheckScreenshot(row.criterion_id, row.description, row.passed, f"{len(found) + 1:02d}-{stem[:60]}.jpg", data))
    return found
