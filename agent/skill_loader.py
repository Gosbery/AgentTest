"""
SkillLoader — scans skills/ directory and parses SKILL.md files.

Implements the two-layer injection strategy:
  Layer 1: Lightweight descriptions in system prompt (~100 tokens/skill)
  Layer 2: Full skill body via load_skill tool (~2000 tokens, on demand)
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass(frozen=True)
class Skill:
    """A single skill with name, description, and body."""
    name: str
    description: str
    body: str
    tags: str = ""


class SkillLoader:
    """
    Scans a skills directory at init time and provides lookup by name.

    Usage:
        loader = SkillLoader(directory)
        descriptions = loader.get_skill_descriptions()  # Layer 1
        body = loader.load_skill("git")                  # Layer 2
    """

    def __init__(self, directory: Optional[str] = None):
        if directory is None:
            # Default to skills/ under project root
            directory = str(Path.cwd() / "skills")

        self._skills: Dict[str, Skill] = {}
        self._scan_directory(directory)

    def _scan_directory(self, directory: str) -> None:
        """Walk the skills directory and parse each SKILL.md."""
        base = Path(directory)
        if not base.is_dir():
            return

        for skill_dir in sorted(base.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                skill = self._parse_skill_file(skill_file)
                self._skills[skill.name] = skill
            except Exception:
                # Skip malformed skill files silently
                pass

    def _parse_skill_file(self, path: Path) -> Skill:
        """
        Parse a SKILL.md file with YAML frontmatter.

        Format:
        ---
        name: git
        description: Git workflow helpers
        tags: vcs, workflow
        ---
        Body content here...
        """
        content = path.read_text(encoding="utf-8")

        if not content.startswith("---"):
            raise ValueError(f"Missing frontmatter in {path}")

        # Split frontmatter from body
        parts = content.split("---", 2)
        if len(parts) < 3:
            raise ValueError(f"Malformed frontmatter in {path}")

        frontmatter = parts[1].strip()
        body = parts[2].strip()

        # Parse YAML-like frontmatter (simple key: value parsing)
        name = ""
        description = ""
        tags = ""

        for line in frontmatter.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if key == "name":
                name = value
            elif key == "description":
                description = value
            elif key == "tags":
                tags = value

        if not name:
            raise ValueError(f"Missing name in {path}")

        return Skill(
            name=name,
            description=description or f"Skill: {name}",
            body=body or "",
            tags=tags,
        )

    def get_skill_descriptions(self) -> Dict[str, str]:
        """
        Layer 1: Return {name: description} for all skills.
        Used to build the system prompt menu.
        """
        return {name: skill.description for name, skill in self._skills.items()}

    def load_skill(self, name: str) -> Optional[str]:
        """
        Layer 2: Return full skill body by name.
        Returns None if skill not found.
        """
        skill = self._skills.get(name)
        if skill is None:
            return None
        return skill.body

    def list_skills(self) -> list:
        """Return list of available skill names."""
        return list(self._skills.keys())

    def has_skill(self, name: str) -> bool:
        """Check if a skill exists."""
        return name in self._skills
