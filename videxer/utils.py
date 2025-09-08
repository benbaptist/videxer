from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set
from enum import Enum


def ensure_dir(path: Path) -> None:
    """Ensure a directory exists, creating it if necessary."""
    path.mkdir(parents=True, exist_ok=True)


# Media file extensions
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".wmv", ".flv", ".m4a"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}

# Extension sets without dots for easier matching
VIDEO_EXTS_NO_DOT = {"mp4", "mov", "mkv", "m4v", "webm", "avi", "wmv", "flv", "m4a"}
AUDIO_EXTS_NO_DOT = {"mp3", "wav", "flac", "aac", "ogg", "m4a", "wma"}
IMAGE_EXTS_NO_DOT = {"jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp"}
ALL_MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS


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


def collect_media_items(root: Path, generate_thumbnails: bool = False) -> List[Dict]:
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
                item = _create_file_item(entry, root, generate_thumbnails)
                if item:
                    items.append(item)

    # Handle nested directories
    if structure in [MediaStructure.NESTED, MediaStructure.MIXED]:
        for entry in sorted(root.iterdir()):
            if entry.is_dir():
                dir_items = _collect_directory_items(entry, root, generate_thumbnails)
                items.extend(dir_items)

    return items


def _create_file_item(file_path: Path, root: Path, generate_thumbnails: bool = False) -> Dict:
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
            thumb_path = file_path.parent / thumb_filename
            if thumb_path.exists() or generate_video_thumbnail(file_path, thumb_path):
                item["thumbs"] = [thumb_filename]
                item["thumb_best"] = thumb_filename

        return item
    except Exception:
        return None


def _collect_directory_items(dir_path: Path, root: Path, generate_thumbnails: bool = False) -> List[Dict]:
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

    for entry in sorted(dir_path.iterdir()):
        if entry.is_file():
            if entry.suffix.lower() in ALL_MEDIA_EXTS and not _is_thumbnail_file(entry.name):
                media_files.append(entry)
            elif entry.name in ["metadata.json", "analytics.json"]:
                metadata_files[entry.name] = entry
            elif entry.name.startswith("thumb_") and entry.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                thumbnail_files.append(entry)

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
            thumb_path = dir_path / "thumb_01.jpg"
            if generate_video_thumbnail(primary_file, thumb_path):
                thumb_rel = str(thumb_path.relative_to(root))
                item["thumbs"] = [thumb_rel]
                item["thumb_best"] = thumb_rel

        # Add video field for backwards compatibility
        if primary_file.suffix.lower() in {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".wmv", ".flv"}:
            item["video"] = str(primary_file.relative_to(root))

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
