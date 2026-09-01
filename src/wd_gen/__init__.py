"""wd_gen: Targeted OSINT/CTF username and password wordlist generator from a target profile"""

from __future__ import annotations

__version__ = "0.1.0"

from .cli import main
from .generate import Candidate, Config, WdGenError, generate
from .profile import Profile

__all__ = [
    "Candidate",
    "Config",
    "Profile",
    "WdGenError",
    "__version__",
    "generate",
    "main",
]
