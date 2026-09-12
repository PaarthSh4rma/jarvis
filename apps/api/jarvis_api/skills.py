import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MAX_SKILLS = 12
MAX_SKILL_FILE_BYTES = 12_288
MAX_SKILL_NAME_CHARACTERS = 64
MAX_SKILL_DESCRIPTION_CHARACTERS = 180
MAX_SKILL_PROCEDURE_CHARACTERS = 8_000
MAX_SKILL_INDEX_CHARACTERS = 3_000
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_SCOPES = {"project"}
REQUIRED_METADATA = {"name", "description", "scope", "version"}


class SkillRegistryError(RuntimeError):
    pass


class SkillValidationError(SkillRegistryError):
    pass


class SkillNotFoundError(SkillRegistryError):
    pass


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    scope: Literal["project"]
    version: int
    procedure: str
    path: Path

    def public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "scope": self.scope,
            "version": self.version,
        }


class SkillRegistry:
    def __init__(
        self,
        skills_root: Path,
        *,
        max_skills: int = MAX_SKILLS,
        max_file_bytes: int = MAX_SKILL_FILE_BYTES,
        max_procedure_characters: int = MAX_SKILL_PROCEDURE_CHARACTERS,
        max_index_characters: int = MAX_SKILL_INDEX_CHARACTERS,
    ) -> None:
        self.root = skills_root.expanduser().resolve()
        self.max_skills = max_skills
        self.max_file_bytes = max_file_bytes
        self.max_procedure_characters = max_procedure_characters
        self.max_index_characters = max_index_characters

    def discover(self) -> tuple[Skill, ...]:
        if not self.root.is_dir():
            raise SkillRegistryError("The configured skill registry is unavailable.")
        skill_files: list[Path] = []
        for directory in sorted(self.root.iterdir(), key=lambda item: item.name.casefold()):
            if directory.name.startswith("."):
                continue
            try:
                resolved_directory = directory.resolve(strict=True)
                resolved_directory.relative_to(self.root)
            except (FileNotFoundError, RuntimeError, ValueError) as error:
                raise SkillValidationError("A skill escapes the trusted registry root.") from error
            if not resolved_directory.is_dir():
                continue
            skill_file = resolved_directory / "SKILL.md"
            if not skill_file.exists():
                continue
            try:
                resolved_file = skill_file.resolve(strict=True)
                resolved_file.relative_to(self.root)
            except (FileNotFoundError, RuntimeError, ValueError) as error:
                raise SkillValidationError(
                    "A skill file escapes the trusted registry root."
                ) from error
            if not resolved_file.is_file():
                raise SkillValidationError("A skill definition must be a regular file.")
            skill_files.append(resolved_file)
        if len(skill_files) > self.max_skills:
            raise SkillValidationError("The skill registry exceeds its configured skill limit.")

        skills = tuple(self._parse(path) for path in skill_files)
        names = [skill.name for skill in skills]
        if len(names) != len(set(names)):
            raise SkillValidationError("The skill registry contains duplicate names.")
        return tuple(sorted(skills, key=lambda skill: skill.name))

    def get(self, name: str) -> Skill:
        if not self._valid_name(name):
            raise SkillNotFoundError(name)
        skill = next((item for item in self.discover() if item.name == name), None)
        if skill is None:
            raise SkillNotFoundError(name)
        return skill

    def selection_index(self) -> tuple[dict[str, object], ...]:
        selected: list[dict[str, object]] = []
        for skill in self.discover():
            item = skill.public_dict()
            candidate = [*selected, item]
            if len(json.dumps(candidate, separators=(",", ":"))) > self.max_index_characters:
                break
            selected.append(item)
        return tuple(selected)

    def _parse(self, path: Path) -> Skill:
        if path.stat().st_size > self.max_file_bytes:
            raise SkillValidationError("A skill definition exceeds the file-size limit.")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise SkillValidationError("A skill definition could not be read safely.") from error
        if not text.startswith("---\n"):
            raise SkillValidationError("A skill definition has malformed frontmatter.")
        closing = text.find("\n---\n", 4)
        if closing < 0:
            raise SkillValidationError("A skill definition has malformed frontmatter.")
        metadata: dict[str, str] = {}
        for line in text[4:closing].splitlines():
            key, separator, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if not separator or not key or not value or key in metadata:
                raise SkillValidationError("A skill definition has malformed metadata.")
            metadata[key] = value
        if set(metadata) != REQUIRED_METADATA:
            raise SkillValidationError("A skill definition has unsupported or missing metadata.")

        name = metadata["name"]
        description = metadata["description"]
        scope = metadata["scope"]
        if not self._valid_name(name):
            raise SkillValidationError("A skill name is invalid.")
        if not (1 <= len(description) <= MAX_SKILL_DESCRIPTION_CHARACTERS):
            raise SkillValidationError("A skill description is invalid.")
        if scope not in ALLOWED_SCOPES:
            raise SkillValidationError("A skill scope is invalid.")
        try:
            version = int(metadata["version"])
        except ValueError as error:
            raise SkillValidationError("A skill version is invalid.") from error
        if not 1 <= version <= 999:
            raise SkillValidationError("A skill version is invalid.")
        procedure = text[closing + 5 :].strip()
        if not procedure or len(procedure) > self.max_procedure_characters:
            raise SkillValidationError("A skill procedure is empty or exceeds its limit.")
        return Skill(
            name=name,
            description=description,
            scope=scope,  # type: ignore[arg-type]
            version=version,
            procedure=procedure,
            path=path,
        )

    @staticmethod
    def _valid_name(name: str) -> bool:
        return bool(
            1 <= len(name) <= MAX_SKILL_NAME_CHARACTERS
            and SKILL_NAME_PATTERN.fullmatch(name)
        )
