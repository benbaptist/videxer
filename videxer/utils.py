from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from enum import Enum
import yaml
import ffmpeg
import logging
import sys


def ensure_dir(path: Path) -> None:
    """Ensure a directory exists, creating it if necessary."""
    path.mkdir(parents=True, exist_ok=True)


# Media file extensions
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".wmv", ".flv", ".m4a"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}

# Subtitle file extensions
SUBTITLE_EXTS = {".srt", ".vtt", ".ass", ".ssa", ".sub", ".idx"}

# Extension sets without dots for easier matching
VIDEO_EXTS_NO_DOT = {"mp4", "mov", "mkv", "m4v", "webm", "avi", "wmv", "flv", "m4a"}
AUDIO_EXTS_NO_DOT = {"mp3", "wav", "flac", "aac", "ogg", "m4a", "wma"}
IMAGE_EXTS_NO_DOT = {"jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp"}
SUBTITLE_EXTS_NO_DOT = {"srt", "vtt", "ass", "ssa", "sub", "idx"}
ALL_MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS

# Indexer assets directory
INDEXER_ASSETS_DIR = ".videxer"
THUMBNAILS_DIR = "thumbnails"


class MediaStructure(Enum):
    """Enumeration of possible media directory structures."""
    FLAT = "flat"  # Media files directly in root directory
    NESTED = "nested"  # Media files organized in subdirectories
    MIXED = "mixed"  # Combination of both flat and nested structures


def detect_media_structure(root: Path) -> MediaStructure:
    """Detect the structure type of media files in the directory.

    Args:
        root: Root directory to analyze

    Returns:
        MediaStructure enum indicating the detected structure
    """
    has_flat_files = False
    has_nested_dirs = False

    for entry in root.iterdir():
        if entry.is_file() and entry.suffix.lower() in ALL_MEDIA_EXTS:
            has_flat_files = True
        elif entry.is_dir():
            # Check if directory contains media files
            if any(p.is_file() and p.suffix.lower() in ALL_MEDIA_EXTS for p in entry.iterdir()):
                has_nested_dirs = True

    if has_flat_files and has_nested_dirs:
        return MediaStructure.MIXED
    elif has_flat_files:
        return MediaStructure.FLAT
    elif has_nested_dirs:
        return MediaStructure.NESTED
    else:
        # Default to nested for empty directories
        return MediaStructure.NESTED


# -----------------------------
# Logging utilities
# -----------------------------

_LOGGER_NAME = "videxer"


def _parse_log_level(level: str) -> int:
    mapping = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARN": logging.WARNING,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "NOTSET": logging.NOTSET,
    }
    return mapping.get(str(level).upper(), logging.INFO)


def setup_logging(output_dir: Path, level: str = "INFO") -> logging.Logger:
    """Initialize videxer logger to stdout and a file in the target dir.

    - File logs go to <output_dir>/.videxer/videxer.log
    - Stream logs go to stdout
    - File handler captures DEBUG+; stream uses the configured level
    """
    ensure_dir(output_dir)
    log_dir = output_dir / INDEXER_ASSETS_DIR
    ensure_dir(log_dir)
    log_file = log_dir / "videxer.log"

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)  # capture all; handlers filter
    logger.propagate = False

    # Avoid duplicate handlers if setup is called multiple times
    if logger.handlers:
        for h in list(logger.handlers):
            logger.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(_parse_log_level(level))
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    logger.debug(f"Logging initialized. File: {log_file}, level: {level}")
    return logger


def get_logger() -> logging.Logger:
    """Get the shared videxer logger."""
    return logging.getLogger(_LOGGER_NAME)


def _group_related_files(directory: Path) -> Dict[str, Dict]:
    """Group media files with their related subtitle/thumbnail files.
    
    Args:
        directory: Directory to scan for related files
        
    Returns:
        Dictionary mapping base names to their related files
    """
    media_groups = {}
    
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
            
        # Skip hidden files, thumbnail files, and asset directories
        if entry.name.startswith('.') or _is_thumbnail_file(entry.name):
            continue
            
        suffix = entry.suffix.lower()
        stem = entry.stem
        
        # Handle media files
        if suffix in ALL_MEDIA_EXTS:
            if stem not in media_groups:
                media_groups[stem] = {
                    'media': entry,
                    'subtitles': [],
                    'thumbnails': []
                }
            else:
                # In case there are multiple media files with same stem, keep the first
                if 'media' not in media_groups[stem]:
                    media_groups[stem]['media'] = entry
                    
        # Handle subtitle files  
        elif suffix in SUBTITLE_EXTS:
            # Match subtitle to media by removing language codes
            base_stem = stem
            # Remove common language suffixes like .en, .eng, .english, etc.
            import re
            base_stem = re.sub(r'\.(en|eng|english|es|spa|spanish|fr|french|de|german)$', '', base_stem, flags=re.IGNORECASE)
            
            if base_stem not in media_groups:
                media_groups[base_stem] = {'subtitles': [], 'thumbnails': []}
            media_groups[base_stem]['subtitles'].append(entry)
            
        # Handle local thumbnail files (not in assets dir)
        elif suffix in IMAGE_EXTS and ('thumb' in entry.name.lower() or entry.name.startswith('poster')):
            # Try to match to a media file
            for key in media_groups:
                if key in entry.name:
                    media_groups[key]['thumbnails'].append(entry)
                    break
    
    return media_groups


def _build_directory_structure(current_dir: Path, root: Path, generate_thumbnails: bool, generate_motion_thumbnails: bool, generate_transcodes: bool) -> List[Dict]:
    """Recursively build directory structure with media items.
    
    Args:
        current_dir: Current directory being processed
        root: Root directory for relative paths
        generate_thumbnails: Whether to generate thumbnails
        generate_motion_thumbnails: Whether to generate motion thumbnails  
        generate_transcodes: Whether to generate transcoded versions
        
    Returns:
        List of items (media items and directories) in current directory
    """
    log = get_logger()
    items = []
    
    # Group related files in this directory
    media_groups = _group_related_files(current_dir)
    
    # Collect subdirectories
    subdirs = []
    for entry in sorted(current_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith('.'):
            subdirs.append(entry)
    
    # Load metadata.json for the current directory if it exists
    current_metadata = None
    current_metadata_path = current_dir / "metadata.json"
    if current_metadata_path.exists():
        try:
            import json
            with open(current_metadata_path, "r", encoding="utf-8") as f:
                current_metadata = json.load(f)
        except Exception as e:
            log.error(f"Failed to load metadata from {current_metadata_path}: {e}")
    
    # Process each media group as a media item
    for base_name, files in sorted(media_groups.items()):
        if 'media' in files:
            media_file = files['media']
            media_item = _create_media_item(
                media_file, 
                root, 
                files.get('subtitles', []),
                files.get('thumbnails', []),
                generate_thumbnails,
                generate_motion_thumbnails,
                generate_transcodes
            )
            if media_item:
                # Apply metadata.json if available and this is the only media file in dir
                if current_metadata and len(media_groups) == 1:
                    if current_metadata.get('name'):
                        media_item['name'] = current_metadata['name']
                    if current_metadata.get('created_time'):
                        media_item['created_time'] = current_metadata['created_time']
                    if current_metadata.get('description'):
                        media_item['description'] = current_metadata['description']
                items.append(media_item)
    
    # Process subdirectories
    for subdir in subdirs:
        # Load metadata.json for this directory if it exists
        metadata = None
        metadata_path = subdir / "metadata.json"
        if metadata_path.exists():
            try:
                import json
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            except Exception as e:
                log.error(f"Failed to load metadata from {metadata_path}: {e}")
        
        # Recursively get contents of subdirectory
        subdir_contents = _build_directory_structure(subdir, root, generate_thumbnails, generate_motion_thumbnails, generate_transcodes)
        
        # Check if this is a single-media directory (flatten it)
        media_items_in_subdir = [item for item in subdir_contents if item.get('type') == 'media']
        dir_items_in_subdir = [item for item in subdir_contents if item.get('type') == 'directory']
        
        # Flatten if: exactly 1 media item and no subdirectories
        should_flatten = len(media_items_in_subdir) == 1 and len(dir_items_in_subdir) == 0
        
        if should_flatten:
            # Flatten: promote the media item to current level with directory name
            media_item = media_items_in_subdir[0]
            # Apply metadata.json if available, otherwise use directory name
            if metadata:
                media_item['name'] = metadata.get('name', subdir.name)
                if metadata.get('created_time'):
                    media_item['created_time'] = metadata['created_time']
                if metadata.get('description'):
                    media_item['description'] = metadata['description']
            else:
                # Update the name to use the directory name instead
                media_item['name'] = subdir.name
            items.append(media_item)
        elif subdir_contents:
            # Keep as directory with children
            dir_item = {
                'type': 'directory',
                'name': subdir.name,
                'path': str(subdir.relative_to(root)),
                'children': subdir_contents
            }
            # Apply metadata to directory item if available
            if metadata:
                if metadata.get('name'):
                    dir_item['name'] = metadata['name']
                if metadata.get('created_time'):
                    dir_item['created_time'] = metadata['created_time']
                if metadata.get('description'):
                    dir_item['description'] = metadata['description']
            items.append(dir_item)
        # else: empty directory, skip it
    
    return items


def _create_media_item(media_file: Path, root: Path, subtitle_files: List[Path], thumbnail_files: List[Path], generate_thumbnails: bool, generate_motion_thumbnails: bool, generate_transcodes: bool) -> Optional[Dict]:
    """Create a media item with all related files.
    
    Args:
        media_file: Primary media file
        root: Root directory for relative paths
        subtitle_files: List of associated subtitle files
        thumbnail_files: List of associated thumbnail files
        generate_thumbnails: Whether to generate thumbnails
        generate_motion_thumbnails: Whether to generate motion thumbnails
        generate_transcodes: Whether to generate transcoded versions
        
    Returns:
        Media item dictionary or None if invalid
    """
    try:
        stat = media_file.stat()
        relative_path = media_file.relative_to(root)
        
        item = {
            'type': 'media',
            'name': media_file.stem,
            'path': str(relative_path),
            'primary_media': str(relative_path),
            'size': stat.st_size,
            'modified_time': stat.st_mtime,
            'media_type': _determine_media_type(media_file.suffix),
        }
        
        # Process thumbnails
        thumb_paths = []
        log = get_logger()
        
        # First, check for existing thumbnails (user-provided or previously found)
        existing_thumbnails = _find_existing_thumbnails(media_file, root)
        if existing_thumbnails:
            thumb_paths = [str(t.relative_to(root)) for t in existing_thumbnails]
            log.debug(f"Found {len(existing_thumbnails)} existing thumbnail(s) for {media_file.name}")
        
        # Also include any thumbnails passed from the grouping function
        if thumbnail_files:
            for t in thumbnail_files:
                thumb_rel = str(t.relative_to(root))
                if thumb_rel not in thumb_paths:
                    thumb_paths.append(thumb_rel)
        
        # Generate thumbnail for video files if requested AND no existing thumbnails found
        if generate_thumbnails and media_file.suffix.lower() in VIDEO_EXTS and not thumb_paths:
            log.debug(f"Generating thumbnail for {media_file.name}")
            thumb_filename = f"{media_file.stem}_thumb.jpg"
            assets_dir = root / INDEXER_ASSETS_DIR / THUMBNAILS_DIR
            ensure_dir(assets_dir)
            thumb_path = assets_dir / thumb_filename
            
            if thumb_path.exists() or generate_video_thumbnail(media_file, thumb_path):
                thumb_rel = str(thumb_path.relative_to(root))
                if thumb_rel not in thumb_paths:
                    thumb_paths.append(thumb_rel)
        
        if thumb_paths:
            item['thumbs'] = thumb_paths
            item['thumb_best'] = thumb_paths[0]  # Use first (highest quality) thumbnail
        
        # Generate motion thumbnail
        if generate_motion_thumbnails and media_file.suffix.lower() in VIDEO_EXTS:
            motion_thumb_filename = f"{media_file.stem}_motion.mp4"
            assets_dir = root / INDEXER_ASSETS_DIR / THUMBNAILS_DIR
            ensure_dir(assets_dir)
            motion_thumb_path = assets_dir / motion_thumb_filename
            
            if not motion_thumb_path.exists():
                generate_motion_thumbnail(media_file, motion_thumb_path)
            if motion_thumb_path.exists():
                item['motion_thumb'] = str(motion_thumb_path.relative_to(root))
        
        # Generate transcode
        if generate_transcodes and media_file.suffix.lower() in VIDEO_EXTS:
            transcode_filename = f"{media_file.stem}_web.mp4"
            assets_dir = root / INDEXER_ASSETS_DIR / "transcodes"
            ensure_dir(assets_dir)
            transcode_path = assets_dir / transcode_filename
            log = get_logger()
            
            if transcode_path.exists():
                if not validate_transcode_file(transcode_path):
                    log.warning(f"Invalid transcode detected, will regenerate: {transcode_path}")
                    try:
                        transcode_path.unlink()
                    except Exception:
                        log.error(f"Failed to delete invalid transcode: {transcode_path}")
                else:
                    log.debug(f"Using existing valid transcode: {transcode_path}")
                    
            if not transcode_path.exists():
                ok = generate_video_transcode(media_file, transcode_path)
                if not ok:
                    log.error(f"Transcoding failed for: {media_file}")
                    
            if transcode_path.exists():
                item['transcoded'] = str(transcode_path.relative_to(root))
        
        # Process subtitles
        if subtitle_files:
            subtitles = []
            for subtitle_file in subtitle_files:
                try:
                    parsed_data = parse_subtitle_file(subtitle_file)
                    if parsed_data["text"]:
                        subtitles.append({
                            "file": str(subtitle_file.relative_to(root)),
                            "language": _detect_subtitle_language(subtitle_file.name),
                            "text": parsed_data["text"],
                            "timestamps": parsed_data["timestamps"],
                            "text_combined": " ".join(parsed_data["text"]).lower()
                        })
                except Exception:
                    continue
            if subtitles:
                item['subtitles'] = subtitles
        
        return item
        
    except Exception as e:
        log = get_logger()
        log.error(f"Failed to create media item for {media_file}: {e}")
        return None


def collect_media_items(root: Path, generate_thumbnails: bool = False, generate_motion_thumbnails: bool = False, generate_transcodes: bool = False) -> List[Dict]:
    """Collect all media items from the directory structure.

    Handles flat, nested, and mixed structures uniformly with hierarchical navigation support.

    Args:
        root: Root directory to scan
        generate_thumbnails: Whether to generate thumbnails
        generate_motion_thumbnails: Whether to generate motion thumbnails
        generate_transcodes: Whether to generate transcoded versions

    Returns:
        List of media item dictionaries with hierarchical structure
    """
    log = get_logger()

    # Preflight validation of existing transcodes to detect corruption
    if generate_transcodes:
        removed = validate_and_purge_bad_transcodes(root)
        if removed:
            log.info(f"Preflight: removed {removed} invalid transcode(s)")

    # Build hierarchical structure from root
    items = _build_directory_structure(root, root, generate_thumbnails, generate_motion_thumbnails, generate_transcodes)
    
    return items


def _find_and_parse_subtitles(media_path: Path, root: Path) -> List[Dict]:
    """Find and parse subtitle files associated with a media file.

    Args:
        media_path: Path to the media file
        root: Root directory for relative path calculation

    Returns:
        List of subtitle dictionaries with file info and parsed text
    """
    subtitles = []
    media_stem = media_path.stem
    media_dir = media_path.parent

    # Common subtitle filename patterns
    patterns = [
        f"{media_stem}.srt",
        f"{media_stem}.vtt",
        f"{media_stem}.ass",
        f"{media_stem}.ssa",
        f"{media_stem}.sub",
        f"{media_stem}.en.srt",
        f"{media_stem}.en.vtt",
        f"{media_stem}.eng.srt",
        f"{media_stem}.eng.vtt",
        f"{media_stem}.english.srt",
        f"{media_stem}.english.vtt",
    ]

    for pattern in patterns:
        subtitle_path = media_dir / pattern
        if subtitle_path.exists() and subtitle_path.is_file():
            try:
                parsed_data = parse_subtitle_file(subtitle_path)
                if parsed_data["text"]:  # Only include if we successfully parsed text
                    subtitles.append({
                        "file": str(subtitle_path.relative_to(root)),
                        "language": _detect_subtitle_language(pattern),
                        "text": parsed_data["text"],
                        "timestamps": parsed_data["timestamps"],
                        "text_combined": " ".join(parsed_data["text"]).lower()  # For efficient searching
                    })
            except Exception:
                continue

    return subtitles


def _detect_subtitle_language(filename: str) -> str:
    """Detect subtitle language from filename patterns."""
    name_lower = filename.lower()

    # Look for language codes separated by dots or underscores
    import re
    parts = re.split(r'[._]', name_lower)

    for part in parts:
        if part in ['english', 'eng', 'en']:
            return 'english'
        elif part in ['spanish', 'spa', 'es']:
            return 'spanish'
        elif part in ['french', 'fre', 'fr']:
            return 'french'
        elif part in ['german', 'ger', 'de']:
            return 'german'
        elif part in ['italian', 'ita', 'it']:
            return 'italian'
        elif part in ['portuguese', 'por', 'pt']:
            return 'portuguese'
        elif part in ['russian', 'rus', 'ru']:
            return 'russian'
        elif part in ['japanese', 'jpn', 'ja']:
            return 'japanese'
        elif part in ['chinese', 'chi', 'zh']:
            return 'chinese'

    return 'unknown'


def _check_videotoolbox_available() -> bool:
    """Check if h264_videotoolbox encoder is available.
    
    Returns:
        True if h264_videotoolbox is available, False otherwise
    """
    try:
        import subprocess
        result = subprocess.run(
            ['ffmpeg', '-hide_banner', '-encoders'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return 'h264_videotoolbox' in result.stdout
    except Exception:
        return False


def generate_video_transcode(input_path: Path, output_path: Path) -> bool:
    """Generate a web-optimized transcoded version of a video file.

    Args:
        input_path: Path to the input video file
        output_path: Path where the transcoded file should be saved

    Returns:
        True if transcoding was successful, False otherwise
    """
    log = get_logger()
    try:
        # Check if hardware encoder is available
        use_videotoolbox = _check_videotoolbox_available()
        encoder = 'h264_videotoolbox' if use_videotoolbox else 'libx264'
        
        log.info(f"Transcoding start: {input_path} -> {output_path} (encoder: {encoder})")
        # Web-optimized settings: low resolution, low bitrate, fast encoding
        stream = ffmpeg.input(str(input_path))
        
        output_params = {
            'vcodec': encoder,
            'acodec': 'aac',
            'vf': 'scale=-2:720',  # Scale to 720p height, maintain aspect ratio
            'maxrate': '2M',       # Maximum bitrate 2Mbps
            'bufsize': '4M',       # Buffer size
            'audio_bitrate': '128k',  # Low audio bitrate
            'movflags': 'faststart'   # Enable fast start for web playback
        }
        
        # Add encoder-specific settings
        if use_videotoolbox:
            output_params['b:v'] = '2M'  # Target video bitrate for videotoolbox
        else:
            output_params['preset'] = 'fast'  # Fast encoding preset for libx264
            output_params['crf'] = 28  # Higher CRF = lower quality, smaller file
        
        stream = ffmpeg.output(stream, str(output_path), **output_params)
        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        ok = output_path.exists()
        if ok:
            log.info(f"Transcoding success: {output_path}")
        else:
            log.error(f"Transcoding failed to produce file: {output_path}")
        return ok
    except Exception as e:
        log.error(f"Transcoding error for {input_path}: {e}")
        return False


def cleanup_old_transcodes(root: Path, current_transcodes: Set[str]) -> None:
    """Clean up transcoded files that are no longer referenced.

    Args:
        root: Root directory
        current_transcodes: Set of current transcoded file paths (relative to root)
    """
    transcode_dir = root / INDEXER_ASSETS_DIR / "transcodes"
    if not transcode_dir.exists():
        return

    for transcode_file in transcode_dir.iterdir():
        if transcode_file.is_file():
            relative_path = str(transcode_file.relative_to(root))
            if relative_path not in current_transcodes:
                try:
                    transcode_file.unlink()
                except Exception:
                    pass  # Ignore cleanup errors


def validate_transcode_file(path: Path) -> bool:
    """Validate a transcode file by probing with ffprobe.

    Returns True if file is valid (has video stream and is readable), else False.
    """
    try:
        info = ffmpeg.probe(str(path))
        streams = info.get('streams', [])
        has_video = any(s.get('codec_type') == 'video' for s in streams)
        return bool(has_video)
    except Exception:
        return False


def validate_and_purge_bad_transcodes(root: Path) -> int:
    """Validate all existing transcodes and delete any that are invalid.

    Returns the number of removed (invalid) transcodes.
    """
    log = get_logger()
    transcode_dir = root / INDEXER_ASSETS_DIR / "transcodes"
    if not transcode_dir.exists():
        return 0
    removed = 0
    for f in sorted(transcode_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() != ".mp4":
            continue
        if not validate_transcode_file(f):
            try:
                f.unlink()
                removed += 1
                log.warning(f"Removed invalid/corrupted transcode: {f}")
            except Exception:
                log.error(f"Failed to remove invalid transcode: {f}")
    if removed:
        log.info(f"Purged {removed} invalid transcode(s) before processing")
    else:
        log.debug("All existing transcodes validated OK")
    return removed


def _create_file_item(file_path: Path, root: Path, generate_thumbnails: bool = False, generate_motion_thumbnails: bool = False, generate_transcodes: bool = False) -> Dict:
    """Create a media item dictionary for a single file.

    Args:
        file_path: Path to the media file
        root: Root directory for relative path calculation

    Returns:
        Media item dictionary or None if invalid
    """
    try:
        stat = file_path.stat()
        relative_path = file_path.relative_to(root)

        item = {
            "type": "file",
            "path": str(relative_path),
            "name": file_path.stem,
            "size": stat.st_size,
            "modified_time": stat.st_mtime,
            "media_type": _determine_media_type(file_path.suffix),
            "full_path": file_path
        }

        # Generate thumbnail for video files if requested
        if generate_thumbnails and file_path.suffix.lower() in VIDEO_EXTS:
            thumb_filename = f"{file_path.stem}_thumb.jpg"
            assets_dir = root / INDEXER_ASSETS_DIR / THUMBNAILS_DIR
            ensure_dir(assets_dir)
            thumb_path = assets_dir / thumb_filename
            # Check for existing thumbnail in old location
            old_thumb_path = file_path.parent / thumb_filename
            if old_thumb_path.exists():
                # Copy old thumbnail to new location if it doesn't exist
                if not thumb_path.exists():
                    import shutil
                    shutil.copy2(old_thumb_path, thumb_path)
            if thumb_path.exists() or generate_video_thumbnail(file_path, thumb_path):
                item["thumbs"] = [str(thumb_path.relative_to(root))]
                item["thumb_best"] = str(thumb_path.relative_to(root))

        # Generate motion thumbnail for video files if requested
        if generate_motion_thumbnails and file_path.suffix.lower() in VIDEO_EXTS:
            motion_thumb_filename = f"{file_path.stem}_motion.mp4"
            assets_dir = root / INDEXER_ASSETS_DIR / THUMBNAILS_DIR
            ensure_dir(assets_dir)
            motion_thumb_path = assets_dir / motion_thumb_filename
            if not motion_thumb_path.exists():
                generate_motion_thumbnail(file_path, motion_thumb_path)
            if motion_thumb_path.exists():
                item["motion_thumb"] = str(motion_thumb_path.relative_to(root))

        # Generate transcoded version for video files if requested
        if generate_transcodes and file_path.suffix.lower() in VIDEO_EXTS:
            transcode_filename = f"{file_path.stem}_web.mp4"
            assets_dir = root / INDEXER_ASSETS_DIR / "transcodes"
            ensure_dir(assets_dir)
            transcode_path = assets_dir / transcode_filename
            log = get_logger()
            if transcode_path.exists():
                # Validate existing transcode; if bad, remove so it gets regenerated
                if not validate_transcode_file(transcode_path):
                    log.warning(f"Invalid transcode detected, will regenerate: {transcode_path}")
                    try:
                        transcode_path.unlink()
                    except Exception:
                        log.error(f"Failed to delete invalid transcode: {transcode_path}")
                else:
                    log.debug(f"Using existing valid transcode: {transcode_path}")
            if not transcode_path.exists():
                ok = generate_video_transcode(file_path, transcode_path)
                if not ok:
                    log.error(f"Transcoding failed for: {file_path}")
            if transcode_path.exists():
                item["transcoded"] = str(transcode_path.relative_to(root))

        # Look for associated subtitle files
        subtitle_data = _find_and_parse_subtitles(file_path, root)
        if subtitle_data:
            item["subtitles"] = subtitle_data

        return item
    except Exception:
        return None


def _collect_directory_items(dir_path: Path, root: Path, generate_thumbnails: bool = False, generate_motion_thumbnails: bool = False, generate_transcodes: bool = False) -> List[Dict]:
    """Collect media items from a directory.

    Args:
        dir_path: Directory to scan
        root: Root directory for relative path calculation

    Returns:
        List of media item dictionaries
    """
    media_files = []
    metadata_files = {}
    thumbnail_files = []
    subtitle_files = []

    for entry in sorted(dir_path.iterdir()):
        if entry.is_file():
            if entry.suffix.lower() in ALL_MEDIA_EXTS and not _is_thumbnail_file(entry.name):
                media_files.append(entry)
            elif entry.name in ["metadata.json", "analytics.json"]:
                metadata_files[entry.name] = entry
            elif entry.name.startswith("thumb_") and entry.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                thumbnail_files.append(entry)
            elif _is_subtitle_file(entry.name):
                subtitle_files.append(entry)

    # Also check for thumbnails in the assets directory
    assets_thumb_dir = root / INDEXER_ASSETS_DIR / THUMBNAILS_DIR
    assets_thumbnails = []
    if assets_thumb_dir.exists():
        for entry in assets_thumb_dir.iterdir():
            if entry.is_file() and entry.name.startswith(f"{dir_path.name}_thumb_") and entry.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                assets_thumbnails.append(entry)

    # Use assets thumbnails if available, otherwise use directory thumbnails
    if assets_thumbnails:
        thumbnail_files = assets_thumbnails
    # If no assets thumbnails and generate_thumbnails is true, we'll generate new ones below

    if not media_files:
        return []

    # Use the first media file as primary
    primary_file = media_files[0]

    try:
        stat = primary_file.stat()
        relative_dir = dir_path.relative_to(root)

        item = {
            "type": "directory",
            "dir": str(relative_dir),
            "name": dir_path.name,
            "size": stat.st_size,
            "modified_time": stat.st_mtime,
            "media_type": _determine_media_type(primary_file.suffix),
            "media_files": [str(p.relative_to(root)) for p in media_files],
            "primary_media": str(primary_file.relative_to(root)),
            "full_path": dir_path
        }

        # Add metadata files if present
        if "metadata.json" in metadata_files:
            item["metadata"] = str(metadata_files["metadata.json"].relative_to(root))
        if "analytics.json" in metadata_files:
            item["analytics"] = str(metadata_files["analytics.json"].relative_to(root))

        # Add thumbnails
        if thumbnail_files:
            sorted_thumbs = sorted(thumbnail_files, key=lambda x: _thumb_sort_key(x.name))
            item["thumbs"] = [str(p.relative_to(root)) for p in sorted_thumbs]
            item["thumb_best"] = str(sorted_thumbs[-1].relative_to(root))
        elif generate_thumbnails and primary_file.suffix.lower() in VIDEO_EXTS:
            # Generate thumbnail if none exist and it's a video file
            thumb_filename = f"{dir_path.name}_thumb_01.jpg"
            assets_dir = root / INDEXER_ASSETS_DIR / THUMBNAILS_DIR
            ensure_dir(assets_dir)
            thumb_path = assets_dir / thumb_filename
            # Check for existing thumbnail in old location
            old_thumb_path = dir_path / "thumb_01.jpg"
            if old_thumb_path.exists():
                # Copy old thumbnail to new location if it doesn't exist
                if not thumb_path.exists():
                    import shutil
                    shutil.copy2(old_thumb_path, thumb_path)
            if thumb_path.exists() or generate_video_thumbnail(primary_file, thumb_path):
                thumb_rel = str(thumb_path.relative_to(root))
                item["thumbs"] = [thumb_rel]
                item["thumb_best"] = thumb_rel

        # Generate motion thumbnail if requested
        if generate_motion_thumbnails and primary_file.suffix.lower() in VIDEO_EXTS:
            motion_thumb_filename = f"{dir_path.name}_motion.mp4"
            assets_dir = root / INDEXER_ASSETS_DIR / THUMBNAILS_DIR
            ensure_dir(assets_dir)
            motion_thumb_path = assets_dir / motion_thumb_filename
            if not motion_thumb_path.exists():
                generate_motion_thumbnail(primary_file, motion_thumb_path)
            if motion_thumb_path.exists():
                item["motion_thumb"] = str(motion_thumb_path.relative_to(root))

        # Generate transcoded version if requested
        if generate_transcodes and primary_file.suffix.lower() in VIDEO_EXTS:
            transcode_filename = f"{dir_path.name}_web.mp4"
            assets_dir = root / INDEXER_ASSETS_DIR / "transcodes"
            ensure_dir(assets_dir)
            transcode_path = assets_dir / transcode_filename
            log = get_logger()
            if transcode_path.exists():
                if not validate_transcode_file(transcode_path):
                    log.warning(f"Invalid transcode detected, will regenerate: {transcode_path}")
                    try:
                        transcode_path.unlink()
                    except Exception:
                        log.error(f"Failed to delete invalid transcode: {transcode_path}")
                else:
                    log.debug(f"Using existing valid transcode: {transcode_path}")
            if not transcode_path.exists():
                ok = generate_video_transcode(primary_file, transcode_path)
                if not ok:
                    log.error(f"Transcoding failed for: {primary_file}")
            if transcode_path.exists():
                item["transcoded"] = str(transcode_path.relative_to(root))

        # Add video field for backwards compatibility
        if primary_file.suffix.lower() in {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".wmv", ".flv"}:
            item["video"] = str(primary_file.relative_to(root))

        # Add subtitle data
        if subtitle_files:
            subtitles = []
            for subtitle_file in subtitle_files:
                try:
                    parsed_data = parse_subtitle_file(subtitle_file)
                    if parsed_data["text"]:
                        subtitles.append({
                            "file": str(subtitle_file.relative_to(root)),
                            "language": _detect_subtitle_language(subtitle_file.name),
                            "text": parsed_data["text"],
                            "timestamps": parsed_data["timestamps"],
                            "text_combined": " ".join(parsed_data["text"]).lower()
                        })
                except Exception:
                    continue
            if subtitles:
                item["subtitles"] = subtitles

        return [item]
    except Exception:
        return []


def _determine_media_type(extension: str) -> str:
    """Determine media type from file extension.

    Args:
        extension: File extension (with or without dot)

    Returns:
        Media type string
    """
    ext = extension.lower().lstrip('.')

    if ext in VIDEO_EXTS_NO_DOT:
        return "video"
    elif ext in AUDIO_EXTS_NO_DOT:
        return "audio"
    elif ext in IMAGE_EXTS_NO_DOT:
        return "image"
    else:
        return "unknown"


def _is_thumbnail_file(filename: str) -> bool:
    """Check if a file is a thumbnail based on its name."""
    name = filename.lower()
    stem = Path(filename).stem.lower()
    
    # Check for various thumbnail naming patterns
    thumbnail_indicators = [
        'thumb', 'thumbnail', 'cover', 'poster', 
        'preview', 'artwork', 'folder'
    ]
    
    # Check if the stem (filename without extension) contains or is exactly one of the indicators
    for indicator in thumbnail_indicators:
        if stem == indicator or f'_{indicator}' in stem or f'{indicator}_' in stem or f'-{indicator}' in stem or f'{indicator}-' in stem:
            return True
    
    return False


def _find_existing_thumbnails(media_file: Path, root: Path) -> List[Path]:
    """Find existing thumbnail files for a media file.
    
    Supports both nested and flat directory structures:
    - Nested: video_dir/video.mp4 and video_dir/thumb.jpg
    - Flat: video.mp4 and video_thumb.jpg or video-thumbnail.png
    
    Args:
        media_file: Path to the media file
        root: Root directory for scanning
        
    Returns:
        List of thumbnail file paths, sorted by quality preference
    """
    thumbnails = []
    media_stem = media_file.stem
    media_dir = media_file.parent
    
    # Define thumbnail patterns to search for
    # Patterns are ordered by preference (higher resolution indicators first)
    thumbnail_patterns = [
        # High-resolution indicators
        f"{media_stem}_thumb_*",
        f"{media_stem}-thumb_*",
        # Standard patterns for flat structure
        f"{media_stem}_thumbnail.*",
        f"{media_stem}-thumbnail.*",
        f"{media_stem}_thumb.*",
        f"{media_stem}-thumb.*",
        f"{media_stem}_cover.*",
        f"{media_stem}-cover.*",
        f"{media_stem}_poster.*",
        f"{media_stem}-poster.*",
        # Nested directory patterns (generic names)
        "thumb_*.*",
        "thumbnail_*.*",
        "thumb.*",
        "thumbnail.*",
        "cover.*",
        "poster.*",
        "folder.*",
        "artwork.*",
        "preview.*",
    ]
    
    # Search in the same directory as the media file
    for pattern in thumbnail_patterns:
        for match in media_dir.glob(pattern):
            if match.is_file() and match.suffix.lower() in IMAGE_EXTS and match != media_file:
                thumbnails.append(match)
    
    # Remove duplicates and sort by preference
    # Prefer files with resolution indicators (e.g., thumb_500x.jpg)
    unique_thumbnails = list(dict.fromkeys(thumbnails))
    
    def thumbnail_sort_key(thumb_path: Path) -> tuple:
        """Sort thumbnails by quality indicators."""
        name = thumb_path.stem.lower()
        
        # Extract resolution if present (e.g., thumb_500x, thumb_1920x1080)
        import re
        resolution_match = re.search(r'(\d+)x(\d*)', name)
        if resolution_match:
            width = int(resolution_match.group(1))
            height = int(resolution_match.group(2)) if resolution_match.group(2) else width
            return (1, width * height)  # Higher resolution = better
        
        # Prefer specific names over generic ones
        if media_stem in name:
            return (0, 1000)  # Media-specific thumbnails
        
        return (0, 0)  # Generic thumbnails
    
    unique_thumbnails.sort(key=thumbnail_sort_key, reverse=True)
    
    return unique_thumbnails


def _is_subtitle_file(filename: str) -> bool:
    """Check if a file is a subtitle file based on its extension."""
    return Path(filename).suffix.lower() in SUBTITLE_EXTS


def parse_subtitle_file(file_path: Path) -> Dict[str, List[str]]:
    """Parse a subtitle file and extract text content organized by timestamps.

    Args:
        file_path: Path to the subtitle file

    Returns:
        Dictionary with 'text' (list of subtitle texts) and 'timestamps' (list of timestamps)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        ext = file_path.suffix.lower()

        if ext == '.srt':
            return _parse_srt(content)
        elif ext == '.vtt':
            return _parse_vtt(content)
        elif ext in {'.ass', '.ssa'}:
            return _parse_ass(content)
        elif ext == '.sub':
            return _parse_sub(content)
        else:
            # Fallback: try to extract text lines
            return _parse_generic_subtitle(content)

    except Exception:
        return {"text": [], "timestamps": []}


def _parse_srt(content: str) -> Dict[str, List[str]]:
    """Parse SRT subtitle format."""
    import re

    text_lines = []
    timestamps = []

    # Split into subtitle blocks
    blocks = re.split(r'\n\s*\n', content.strip())

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            # Extract timestamp line (format: 00:00:01,000 --> 00:00:04,000)
            timestamp_match = re.search(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', lines[1])
            if timestamp_match:
                start_time = timestamp_match.group(1)
                timestamps.append(start_time)

                # Extract text (everything after timestamp line)
                text = '\n'.join(lines[2:]).strip()
                # Remove HTML tags if present
                text = re.sub(r'<[^>]+>', '', text)
                if text:
                    text_lines.append(text)

    return {"text": text_lines, "timestamps": timestamps}


def _parse_vtt(content: str) -> Dict[str, List[str]]:
    """Parse WebVTT subtitle format."""
    import re

    text_lines = []
    timestamps = []

    lines = content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Skip WEBVTT header and empty lines
        if line in ['WEBVTT', ''] or line.startswith('NOTE'):
            i += 1
            continue

        # Check for timestamp line (format: 00:00:01.000 --> 00:00:04.000)
        timestamp_match = re.search(r'(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})', line)
        if timestamp_match:
            start_time = timestamp_match.group(1)
            timestamps.append(start_time)

            # Collect text until next timestamp or end
            i += 1
            text_parts = []
            while i < len(lines) and not re.search(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}', lines[i].strip()) and lines[i].strip():
                text_parts.append(lines[i].strip())
                i += 1

            text = ' '.join(text_parts).strip()
            if text:
                text_lines.append(text)
        else:
            i += 1

    return {"text": text_lines, "timestamps": timestamps}


def _parse_ass(content: str) -> Dict[str, List[str]]:
    """Parse ASS/SSA subtitle format."""
    import re

    text_lines = []
    timestamps = []

    lines = content.split('\n')

    for line in lines:
        line = line.strip()
        if line.startswith('Dialogue:'):
            # Format: Dialogue: 0,0:00:01.00,0:00:04.00,...
            parts = line.split(',', 9)
            if len(parts) >= 10:
                start_time = parts[1]
                timestamps.append(start_time)

                text = parts[9].strip()
                # Remove ASS formatting tags
                text = re.sub(r'\{[^}]+\}', '', text)
                if text:
                    text_lines.append(text)

    return {"text": text_lines, "timestamps": timestamps}


def _parse_sub(content: str) -> Dict[str, List[str]]:
    """Parse basic SUB subtitle format."""
    text_lines = []
    timestamps = []

    lines = content.split('\n')

    for line in lines:
        line = line.strip()
        if line and not line.replace(':', '').replace('.', '').replace(' ', '').isdigit():
            # Assume non-numeric lines are text
            text_lines.append(line)
            timestamps.append("")  # No timestamps in basic SUB format

    return {"text": text_lines, "timestamps": timestamps}


def _parse_generic_subtitle(content: str) -> Dict[str, List[str]]:
    """Fallback parser for unknown subtitle formats."""
    import re

    lines = content.split('\n')
    text_lines = []
    timestamps = []

    for line in lines:
        line = line.strip()
        if line and not re.match(r'^\d+$', line):  # Skip pure numbers (likely indices)
            text_lines.append(line)
            timestamps.append("")

    return {"text": text_lines, "timestamps": timestamps}


def _thumb_sort_key(filename: str) -> int:
    """Sort key that extracts the numeric index from thumbnail filenames like 'thumb_12.jpg'."""
    try:
        base = Path(filename).stem  # thumb_12
        # Expect pattern thumb_<n>
        if "_" in base:
            return int(base.split("_")[-1])
    except Exception:
        pass
    return 0


def generate_video_thumbnail(video_path: Path, output_path: Path, timestamp: float = 1.0, size: tuple = (320, 180)) -> bool:
    """Generate a thumbnail image from a video file at the specified timestamp.
    
    Maintains the original aspect ratio with letterboxing/pillarboxing to fit within
    the target size without stretching.

    Args:
        video_path: Path to the video file
        output_path: Path where the thumbnail should be saved
        timestamp: Time in seconds to extract the frame from (default: 1.0)
        size: Tuple of (width, height) for the thumbnail size (default: 320x180)

    Returns:
        True if thumbnail was generated successfully, False otherwise
    """
    try:
        import cv2
        import numpy as np

        # Open the video file
        cap = cv2.VideoCapture(str(video_path))

        if not cap.isOpened():
            return False

        # Get video properties
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0

        # Adjust timestamp if it's beyond video duration
        if timestamp >= duration and duration > 0:
            timestamp = duration * 0.1  # Use 10% into the video

        # Set the position to the desired timestamp
        frame_number = int(timestamp * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

        # Read the frame
        ret, frame = cap.read()

        if not ret:
            cap.release()
            return False

        # Get original frame dimensions
        original_height, original_width = frame.shape[:2]
        target_width, target_height = size

        # Calculate scaling factor to fit within target size while maintaining aspect ratio
        scale = min(target_width / original_width, target_height / original_height)
        
        # Calculate new dimensions
        new_width = int(original_width * scale)
        new_height = int(original_height * scale)
        
        # Resize frame maintaining aspect ratio
        resized_frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
        
        # Create black canvas of target size
        canvas = np.zeros((target_height, target_width, 3), dtype=np.uint8)
        
        # Calculate position to center the resized frame
        x_offset = (target_width - new_width) // 2
        y_offset = (target_height - new_height) // 2
        
        # Place resized frame on canvas
        canvas[y_offset:y_offset + new_height, x_offset:x_offset + new_width] = resized_frame

        # Save the thumbnail
        cv2.imwrite(str(output_path), canvas, [cv2.IMWRITE_JPEG_QUALITY, 85])

        cap.release()
        return True

    except ImportError:
        # OpenCV not available
        return False
    except Exception:
        return False


def generate_motion_thumbnail(video_path: Path, output_path: Path, duration: float = 2.0, fps: int = 10, size: tuple = (320, 180)) -> bool:
    """Generate an efficient video thumbnail from a video file showing short clips at different timestamps.

    Args:
        video_path: Path to the video file
        output_path: Path where the motion thumbnail should be saved
        duration: Total duration of the motion thumbnail in seconds (default: 2.0)
        fps: Frames per second for the animation (default: 10)
        size: Tuple of (width, height) for the thumbnail size (default: 320x180)

    Returns:
        True if motion thumbnail was generated successfully, False otherwise
    """
    try:
        import tempfile
        import os

        # Get video duration using ffprobe
        probe = ffmpeg.probe(str(video_path))
        video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        video_duration = float(probe['format']['duration'])

        if video_duration < 1.0:
            # For very short videos, just create a static video thumbnail
            return generate_video_thumbnail(video_path, output_path, 0.1, size)

        # Calculate timestamps for motion thumbnail segments
        # Sample 4-6 points throughout the video
        num_samples = min(6, max(4, int(video_duration / 10)))  # More samples for longer videos
        segment_duration = duration / num_samples  # Duration per segment

        # Create temporary directory for segment files
        with tempfile.TemporaryDirectory() as temp_dir:
            segment_files = []

            for i in range(num_samples):
                # Distribute timestamps evenly, avoiding the very beginning and end
                progress = (i + 1) / (num_samples + 1)
                timestamp = video_duration * progress

                # Extract a short segment at this timestamp
                segment_path = Path(temp_dir) / f"segment_{i:02d}.mp4"

                # Extract segment with ffmpeg
                use_videotoolbox = _check_videotoolbox_available()
                encoder = 'h264_videotoolbox' if use_videotoolbox else 'libx264'
                
                stream = ffmpeg.input(str(video_path), ss=timestamp, t=segment_duration)
                
                output_params = {
                    'vcodec': encoder,
                    'acodec': 'aac',
                    'vf': f'scale={size[0]}:{size[1]}:force_original_aspect_ratio=decrease,pad={size[0]}:{size[1]}:(ow-iw)/2:(oh-ih)/2',
                    'r': fps,
                    'audio_bitrate': '64k',
                    'maxrate': '500k',
                    'bufsize': '1M',
                    'movflags': 'faststart'
                }
                
                if use_videotoolbox:
                    output_params['b:v'] = '500k'
                else:
                    output_params['preset'] = 'ultrafast'
                    output_params['crf'] = 32
                
                stream = ffmpeg.output(stream, str(segment_path), **output_params)
                ffmpeg.run(stream, overwrite_output=True, quiet=True)
                segment_files.append(segment_path)

            if len(segment_files) < 2:
                return False

            # Create a concat file for ffmpeg
            concat_file = Path(temp_dir) / "concat.txt"
            with open(concat_file, 'w') as f:
                for segment in segment_files:
                    f.write(f"file '{segment}'\n")

            # Concatenate all segments into final motion thumbnail
            use_videotoolbox = _check_videotoolbox_available()
            encoder = 'h264_videotoolbox' if use_videotoolbox else 'libx264'
            
            stream = ffmpeg.input(str(concat_file), format='concat', safe=0)
            
            output_params = {
                'vcodec': encoder,
                'acodec': 'aac',
                'r': fps,
                'audio_bitrate': '64k',
                'maxrate': '800k',
                'bufsize': '1.6M',
                'movflags': 'faststart',
                'pix_fmt': 'yuv420p'
            }
            
            if use_videotoolbox:
                output_params['b:v'] = '800k'
            else:
                output_params['preset'] = 'fast'
                output_params['crf'] = 28
            
            stream = ffmpeg.output(stream, str(output_path), **output_params)
            ffmpeg.run(stream, overwrite_output=True, quiet=True)

        return output_path.exists()

    except ImportError:
        # FFmpeg not available, fall back to old method
        return _generate_motion_thumbnail_gif(video_path, output_path, duration, fps, size)
    except Exception:
        return False


def _generate_motion_thumbnail_gif(video_path: Path, output_path: Path, duration: float = 2.0, fps: int = 10, size: tuple = (320, 180)) -> bool:
    """Legacy GIF-based motion thumbnail generation (fallback)."""
    try:
        import cv2
        from PIL import Image

        # Open the video file
        cap = cv2.VideoCapture(str(video_path))

        if not cap.isOpened():
            return False

        # Get video properties
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_duration = total_frames / video_fps if video_fps > 0 else 0

        if video_duration < 1.0:
            # For very short videos, just use the static thumbnail approach
            return generate_video_thumbnail(video_path, output_path, 0.1, size)

        # Calculate timestamps for motion thumbnail
        # Sample 4-6 points throughout the video
        num_samples = min(6, max(4, int(video_duration / 10)))  # More samples for longer videos
        timestamps = []

        for i in range(num_samples):
            # Distribute timestamps evenly, avoiding the very beginning and end
            progress = (i + 1) / (num_samples + 1)
            timestamp = video_duration * progress
            timestamps.append(timestamp)

        frames = []

        for timestamp in timestamps:
            # Set the position to the desired timestamp
            frame_number = int(timestamp * video_fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

            # Read the frame
            ret, frame = cap.read()

            if ret:
                # Resize the frame
                resized_frame = cv2.resize(frame, size, interpolation=cv2.INTER_LANCZOS4)
                # Convert BGR to RGB for PIL
                rgb_frame = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)
                frames.append(Image.fromarray(rgb_frame))

        cap.release()

        if len(frames) < 2:
            return False

        # Calculate duration per frame in milliseconds
        frame_duration = int((duration * 1000) / len(frames))

        # Save as animated GIF
        frames[0].save(
            str(output_path),
            save_all=True,
            append_images=frames[1:],
            duration=frame_duration,
            loop=0,  # Infinite loop
            optimize=True,
            quality=85
        )

        return True

    except ImportError:
        # PIL or OpenCV not available
        return False
    except Exception:
        return False


def load_config(input_dir: Path) -> Dict[str, Any]:
    """Load configuration from .videxer/config.yaml if it exists.

    Args:
        input_dir: The input directory to look for config in

    Returns:
        Dictionary containing config values, empty dict if no config found
    """
    config_path = input_dir / INDEXER_ASSETS_DIR / "config.yaml"

    if not config_path.exists():
        return {}

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            return config if config is not None else {}
    except Exception:
        # If config file is corrupted, return empty config
        return {}


def save_config(input_dir: Path, config: Dict[str, Any]) -> None:
    """Save configuration to .videxer/config.yaml.

    Args:
        input_dir: The input directory to save config in
        config: Configuration dictionary to save
    """
    config_dir = input_dir / INDEXER_ASSETS_DIR
    config_path = config_dir / "config.yaml"

    # Ensure the .videxer directory exists
    ensure_dir(config_dir)

    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
    except Exception:
        # Silently fail if we can't save config
        pass


def merge_config_with_args(config: Dict[str, Any], cli_args: Dict[str, Any]) -> Dict[str, Any]:
    """Merge config values with CLI arguments, with CLI taking precedence.

    Args:
        config: Configuration from config.yaml
        cli_args: Arguments passed via CLI

    Returns:
        Merged configuration with CLI args taking precedence
    """
    merged = config.copy()

    # CLI args override config values
    for key, value in cli_args.items():
        if value is not None:  # Only override if CLI arg was actually provided
            merged[key] = value

    return merged
