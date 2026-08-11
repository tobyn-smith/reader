"""where things live.

the database and the reading pdfs sit outside the repository on purpose. the
repo holds code, templates, and one reviewed export file. nothing else. that way
a stray `git add -A` cannot put a semester of other people's copyrighted text
into a public history.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOME = Path.home() / ".seminar-vault"


@dataclass(frozen=True)
class Config:
    home: Path
    database: Path
    library: Path
    inbox: Path
    cache: Path
    public_export: Path
    public_site: Path
    private_site: Path
    threshold: float

    def ensure(self) -> "Config":
        for directory in (self.home, self.library, self.inbox, self.cache):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def load() -> Config:
    home = Path(os.environ.get("VAULT_HOME", DEFAULT_HOME)).expanduser()
    return Config(
        home=home,
        database=Path(os.environ.get("VAULT_DB", home / "vault.sqlite")).expanduser(),
        library=Path(os.environ.get("VAULT_LIBRARY", home / "library")).expanduser(),
        inbox=Path(os.environ.get("VAULT_INBOX", home / "inbox")).expanduser(),
        cache=Path(os.environ.get("VAULT_CACHE", home / "cache")).expanduser(),
        # the one data file that is allowed inside the repository
        public_export=Path(
            os.environ.get("VAULT_PUBLIC_EXPORT", REPO_ROOT / "data" / "public.json")
        ).expanduser(),
        public_site=Path(os.environ.get("VAULT_PUBLIC_SITE", REPO_ROOT / "_site_public")).expanduser(),
        private_site=Path(
            os.environ.get("VAULT_PRIVATE_SITE", REPO_ROOT / "_site_private")
        ).expanduser(),
        threshold=float(os.environ.get("VAULT_CONFIDENCE_THRESHOLD", "0.75")),
    )
