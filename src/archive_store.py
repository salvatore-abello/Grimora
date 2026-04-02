from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Iterator
import zipfile

from . import config
from .config import logger
from .models import Transcript, TranscriptInfo
from .parser import parse_transcript
from .utils import stable_slug


DEFAULT_ARCHIVE_DATE = datetime(2006, 6, 30, tzinfo=UTC)
SPLIT_ARCHIVE_PATTERN = re.compile(r"^(?P<archive>.+\.zip)\.part(?P<part>\d+)$")


@dataclass(frozen=True)
class ArchiveSource:
    id: str
    archive_key: str
    parts: tuple[Path, ...]
    display_name: str
    description: str
    added: datetime
    signature: tuple[tuple[str, int, int], ...]


class ArchiveStore:
    def __init__(self, transcripts_directory: str):
        self.transcripts_directory = Path(transcripts_directory)
        self._sources: dict[str, ArchiveSource] = {}
        self._info_cache: dict[str, TranscriptInfo] = {}
        self._transcript_cache: dict[str, Transcript] = {}

    def refresh(self) -> None:
        self.transcripts_directory.mkdir(parents=True, exist_ok=True)

        metadata = self._load_metadata()
        discovered = self._discover_sources(metadata)

        stale_ids = set(self._sources) - set(discovered)
        for transcript_id in stale_ids:
            self._info_cache.pop(transcript_id, None)
            self._transcript_cache.pop(transcript_id, None)

        for transcript_id, source in discovered.items():
            previous = self._sources.get(transcript_id)
            if previous != source:
                self._info_cache.pop(transcript_id, None)
                self._transcript_cache.pop(transcript_id, None)

        self._sources = discovered

    def list_infos(self) -> list[TranscriptInfo]:
        self.refresh()

        infos: list[TranscriptInfo] = []
        for transcript_id in sorted(self._sources):
            try:
                infos.append(self.get_info(transcript_id))
            except Exception as exc:
                logger.warning("Skipping transcript %s because it could not be indexed: %s", transcript_id, exc)

        return infos

    def get_info(self, transcript_id: str) -> TranscriptInfo:
        self.refresh()

        if transcript_id in self._info_cache:
            return self._info_cache[transcript_id]

        source = self._require_source(transcript_id)
        info = self._scan_info(source)
        self._info_cache[transcript_id] = info
        return info

    def get_transcript(self, transcript_id: str) -> Transcript:
        self.refresh()

        if transcript_id in self._transcript_cache:
            return self._transcript_cache[transcript_id]

        source = self._require_source(transcript_id)
        transcript = self._parse_source(source)
        self._transcript_cache[transcript_id] = transcript
        self._info_cache[transcript_id] = transcript.info
        return transcript

    def save_metadata(self, archive_key: str, name: str, description: str) -> None:
        metadata = self._load_metadata()

        normalized_name = name.strip()
        normalized_description = description.strip()

        if normalized_name or normalized_description:
            metadata[archive_key] = {
                "name": normalized_name,
                "description": normalized_description,
            }
        else:
            metadata.pop(archive_key, None)

        with open(config.TRANSCRIPTS_METADATA, "w", encoding="utf8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2, sort_keys=True)

    @staticmethod
    def archive_key_from_filename(filename: str) -> str | None:
        match = SPLIT_ARCHIVE_PATTERN.fullmatch(filename)
        if match is not None:
            return match.group("archive")

        if filename.endswith(".zip"):
            return filename

        return None

    @staticmethod
    def transcript_id_from_archive_key(archive_key: str) -> str:
        return stable_slug(archive_key, prefix="transcript")

    def _require_source(self, transcript_id: str) -> ArchiveSource:
        source = self._sources.get(transcript_id)
        if source is None:
            raise KeyError(transcript_id)
        return source

    def _load_metadata(self) -> dict[str, dict[str, str]]:
        metadata_path = Path(config.TRANSCRIPTS_METADATA)
        if not metadata_path.exists():
            return {}

        try:
            with open(metadata_path, "r", encoding="utf8") as f:
                raw_metadata = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read transcript metadata file %s: %s", metadata_path, exc)
            return {}

        if not isinstance(raw_metadata, dict):
            logger.warning("Transcript metadata file %s is not a mapping", metadata_path)
            return {}

        metadata: dict[str, dict[str, str]] = {}
        for archive_key, entry in raw_metadata.items():
            if not isinstance(entry, dict):
                continue

            metadata[str(archive_key)] = {
                "name": str(entry.get("name", "") or ""),
                "description": str(entry.get("description", "") or ""),
            }

        return metadata

    def _discover_sources(self, metadata: dict[str, dict[str, str]]) -> dict[str, ArchiveSource]:
        whole_archives: dict[str, Path] = {}
        split_archives: dict[str, dict[int, Path]] = {}

        metadata_name = Path(config.TRANSCRIPTS_METADATA).name

        for path in sorted(self.transcripts_directory.iterdir()):
            if not path.is_file() or path.name == metadata_name:
                continue

            archive_key = self.archive_key_from_filename(path.name)
            if archive_key is None:
                continue

            split_match = SPLIT_ARCHIVE_PATTERN.fullmatch(path.name)
            if split_match is not None:
                split_archives.setdefault(archive_key, {})[int(split_match.group("part"))] = path
                continue

            whole_archives[archive_key] = path

        discovered: dict[str, ArchiveSource] = {}

        for archive_key, path in whole_archives.items():
            source = self._build_source(archive_key, [path], metadata)
            discovered[source.id] = source

        for archive_key, indexed_parts in split_archives.items():
            if archive_key in whole_archives:
                logger.warning("Ignoring split archive parts for %s because a full zip already exists", archive_key)
                continue

            ordered_parts = [indexed_parts[index] for index in sorted(indexed_parts)]
            source = self._build_source(archive_key, ordered_parts, metadata)
            discovered[source.id] = source

        return discovered

    def _build_source(
        self,
        archive_key: str,
        parts: list[Path],
        metadata: dict[str, dict[str, str]],
    ) -> ArchiveSource:
        archive_name = archive_key.removesuffix(".zip")
        archive_metadata = metadata.get(archive_key, {})

        signature = tuple(
            (part.name, part.stat().st_size, part.stat().st_mtime_ns)
            for part in parts
        )
        added = datetime.fromtimestamp(
            max(part.stat().st_mtime for part in parts),
            tz=UTC,
        )

        return ArchiveSource(
            id=self.transcript_id_from_archive_key(archive_key),
            archive_key=archive_key,
            parts=tuple(parts),
            display_name=archive_metadata.get("name") or archive_name,
            description=archive_metadata.get("description") or "",
            added=added,
            signature=signature,
        )

    def _scan_info(self, source: ArchiveSource) -> TranscriptInfo:
        message_start = None
        message_end = None
        channel_count = 0
        message_count = 0

        with self._open_archive(source) as archive:
            for channel_json in self._channel_json_paths(archive):
                channel_count += 1
                with archive.open(channel_json, "r") as file_handle, io.TextIOWrapper(file_handle, encoding="utf8") as wrapper:
                    raw_messages = json.load(wrapper)

                if raw_messages is None:
                    continue

                for raw_message in raw_messages:
                    message_count += 1
                    timestamp = datetime.fromisoformat(raw_message["timestamp"])

                    if message_start is None or timestamp < message_start:
                        message_start = timestamp

                    if message_end is None or timestamp > message_end:
                        message_end = timestamp

        return TranscriptInfo(
            id=source.id,
            name=source.display_name,
            description=source.description,
            added=source.added,
            channel_count=channel_count,
            message_count=message_count,
            part_count=len(source.parts),
            message_start=message_start or DEFAULT_ARCHIVE_DATE,
            message_end=message_end or DEFAULT_ARCHIVE_DATE,
        )

    def _parse_source(self, source: ArchiveSource) -> Transcript:
        with tempfile.TemporaryDirectory(prefix="grimora-") as tmpdir:
            extraction_root = Path(tmpdir) / "extracted"
            extraction_root.mkdir(parents=True, exist_ok=True)

            with self._open_archive(source) as archive:
                self._safe_extract_archive(archive, extraction_root)

            transcript_root = self._resolve_transcript_root(extraction_root)
            return parse_transcript(
                str(transcript_root),
                name=source.display_name,
                description=source.description,
                transcript_id=source.id,
                added=source.added,
            )

    @contextmanager
    def _open_archive(self, source: ArchiveSource) -> Iterator[zipfile.ZipFile]:
        if len(source.parts) == 1 and source.parts[0].suffix == ".zip":
            with zipfile.ZipFile(source.parts[0]) as archive:
                yield archive
            return

        part_indexes = []
        for part in source.parts:
            match = SPLIT_ARCHIVE_PATTERN.fullmatch(part.name)
            if match is None:
                raise ValueError(f"{part.name} is not a valid split archive part")
            part_indexes.append(int(match.group("part")))

        expected_indexes = list(range(len(part_indexes)))
        if sorted(part_indexes) != expected_indexes:
            raise ValueError(
                f"Archive {source.archive_key} is missing split parts: expected {expected_indexes}, got {sorted(part_indexes)}"
            )

        with tempfile.TemporaryDirectory(prefix="grimora-zip-") as tmpdir:
            combined_zip = Path(tmpdir) / source.archive_key

            with open(combined_zip, "wb") as combined_file:
                for part in source.parts:
                    with open(part, "rb") as part_file:
                        shutil.copyfileobj(part_file, combined_file)

            with zipfile.ZipFile(combined_zip) as archive:
                yield archive

    def _channel_json_paths(self, archive: zipfile.ZipFile) -> list[str]:
        channel_paths: list[str] = []

        for archive_info in archive.infolist():
            if archive_info.is_dir():
                continue

            path = PurePosixPath(archive_info.filename)
            if len(path.parts) != 2:
                continue

            channel_directory, filename = path.parts
            if filename != f"{channel_directory}.json":
                continue

            channel_paths.append(archive_info.filename)

        channel_paths.sort()
        return channel_paths

    def _safe_extract_archive(self, archive: zipfile.ZipFile, destination: Path) -> None:
        destination_root = destination.resolve()

        for archive_info in archive.infolist():
            relative_path = PurePosixPath(archive_info.filename)
            target_path = destination.joinpath(*relative_path.parts)
            resolved_target = target_path.resolve()

            if os.path.commonpath([str(destination_root), str(resolved_target)]) != str(destination_root):
                raise ValueError(f"Archive member escapes extraction directory: {archive_info.filename}")

            if archive_info.is_dir():
                resolved_target.mkdir(parents=True, exist_ok=True)
                continue

            resolved_target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(archive_info, "r") as source_file, open(resolved_target, "wb") as destination_file:
                shutil.copyfileobj(source_file, destination_file)

    def _resolve_transcript_root(self, extraction_root: Path) -> Path:
        children = [path for path in extraction_root.iterdir()]
        if len(children) != 1 or not children[0].is_dir():
            return extraction_root

        nested_root = children[0]
        if any(path.is_dir() for path in nested_root.iterdir()):
            return nested_root

        return extraction_root


archive_store = ArchiveStore(config.TRANSCRIPTS_DIRECTORY)
