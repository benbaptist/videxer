from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from enum import Enum
import yaml
import ffmpeg


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


def collect_media_items(root: Path, generate_thumbnails: bool = False, generate_motion_thumbnails: bool = False, generate_transcodes: bool = False) -> List[Dict]:
    """Collect all media items from the directory structure.

    Handles flat, nested, and mixed structures uniformly.

    Args:
        root: Root directory to scan

    Returns:
        List of media item dictionaries with unified structure
    """
    items = []
    structure = detect_media_structure(root)

    # Handle flat files in root directory
    if structure in [MediaStructure.FLAT, MediaStructure.MIXED]:
        for entry in sorted(root.iterdir()):
            if entry.is_file() and entry.suffix.lower() in ALL_MEDIA_EXTS and not _is_thumbnail_file(entry.name):
                item = _create_file_item(entry, root, generate_thumbnails, generate_motion_thumbnails, generate_transcodes)
                if item:
                    items.append(item)

    # Handle nested directories
    if structure in [MediaStructure.NESTED, MediaStructure.MIXED]:
        for entry in sorted(root.iterdir()):
            if entry.is_dir():
                dir_items = _collect_directory_items(entry, root, generate_thumbnails, generate_motion_thumbnails, generate_transcodes)
                items.extend(dir_items)

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


def generate_video_transcode(input_path: Path, output_path: Path) -> bool:
    """Generate a web-optimized transcoded version of a video file.

    Args:
        input_path: Path to the input video file
        output_path: Path where the transcoded file should be saved

    Returns:
        True if transcoding was successful, False otherwise
    """
    try:
        # Web-optimized settings: low resolution, low bitrate, fast encoding
        stream = ffmpeg.input(str(input_path))
        stream = ffmpeg.output(
            stream,
            str(output_path),
            vcodec='libx264',  # H.264 for broad compatibility
            acodec='aac',      # AAC for audio
            preset='fast',     # Fast encoding
            crf=28,           # Higher CRF = lower quality, smaller file
            vf='scale=-2:720', # Scale to 720p height, maintain aspect ratio
            maxrate='2M',     # Maximum bitrate 2Mbps
            bufsize='4M',     # Buffer size
            audio_bitrate='128k',  # Low audio bitrate
            movflags='faststart'    # Enable fast start for web playback
        )
        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        return output_path.exists()
    except Exception:
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
            motion_thumb_filename = f"{file_path.stem}_motion.gif"
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
            if not transcode_path.exists():
                generate_video_transcode(file_path, transcode_path)
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
            motion_thumb_filename = f"{dir_path.name}_motion.gif"
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
            if not transcode_path.exists():
                generate_video_transcode(primary_file, transcode_path)
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
    return name.startswith("thumb_") or "_thumb" in name or name.endswith("_thumb.jpg") or name.endswith("_thumb.jpeg") or name.endswith("_thumb.png") or name.endswith("_thumb.webp")


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

        # Resize the frame to the desired thumbnail size
        resized_frame = cv2.resize(frame, size, interpolation=cv2.INTER_LANCZOS4)

        # Save the thumbnail
        cv2.imwrite(str(output_path), resized_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

        cap.release()
        return True

    except ImportError:
        # OpenCV not available
        return False
    except Exception:
        return False


def generate_motion_thumbnail(video_path: Path, output_path: Path, duration: float = 2.0, fps: int = 10, size: tuple = (320, 180)) -> bool:
    """Generate an animated GIF thumbnail from a video file showing short clips at different timestamps.

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
