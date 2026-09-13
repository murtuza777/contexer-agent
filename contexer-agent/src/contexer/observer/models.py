"""Data models for browser observations."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class BrowserObservation(BaseModel):
    """Structured capture of a webpage's runtime state via Playwright."""

    url: str
    page_title: str = ""
    visible_text: str = ""
    html: str = ""
    console_errors: list[str] = Field(default_factory=list)
    page_errors: list[str] = Field(default_factory=list)
    interactive_elements: list[str] = Field(default_factory=list)
    headings: list[str] = Field(default_factory=list)
    status_code: Optional[int] = None
    screenshot_path: Optional[str] = None
    screenshot_base64: Optional[str] = None
    success: bool = True
    error: Optional[str] = None

    @property
    def has_errors(self) -> bool:
        """True if there are console errors, uncaught exceptions, or network failure."""
        return not self.success or bool(self.console_errors) or bool(self.page_errors)
