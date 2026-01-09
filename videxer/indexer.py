from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
import json
import os
from datetime import datetime

from .utils import collect_media_items, detect_media_structure, MediaStructure, generate_video_thumbnail, get_logger


# Extended media extensions
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".wmv", ".flv", ".m4a"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}
ALL_MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS


def _build_base_search_index(items: List[Dict]) -> Dict:
  """Build lightweight search index (names, descriptions only)."""
  search_index = {
    "name_terms": {},
    "description_terms": {},
    "item_map": []
  }

  for idx, item in enumerate(items):
    item_id = f"{item.get('type', 'unknown')}_{item.get('path', item.get('dir', str(idx)))}"
    search_index["item_map"].append(item_id)

    name = item.get("name", "").lower()
    if name:
      _add_to_search_index(search_index["name_terms"], name, idx)

    description = item.get("description") or ""
    if description:
      description = str(description).lower()
      _add_to_search_index(search_index["description_terms"], description, idx)

  return search_index


def _build_subtitle_index(items: List[Dict]) -> Dict:
  """Build subtitle-only inverted index as a separate artifact."""
  subtitle_index = {"subtitle_terms": {}}
  for idx, item in enumerate(items):
    if "subtitles" in item:
      for subtitle in item["subtitles"]:
        combined_text = subtitle.get("text_combined", "").lower()
        if combined_text:
          _add_to_search_index(subtitle_index["subtitle_terms"], combined_text, idx)
  return subtitle_index


def _add_to_search_index(index_dict: Dict, text: str, item_idx: int):
    """Add text to search index, splitting into words and handling duplicates."""
    import re

    # Split text into words, keeping only alphanumeric characters
    words = re.findall(r'\b\w+\b', text)

    for word in words:
        if len(word) >= 3:  # Only index words with 3+ characters
            if word not in index_dict:
                index_dict[word] = []
            if item_idx not in index_dict[word]:
                index_dict[word].append(item_idx)


def _flatten_items(items: List[Dict]) -> List[Dict]:
    """Flatten hierarchical structure to a list of all media items for indexing.
    
    Args:
        items: Hierarchical list of items (may contain directories with children)
        
    Returns:
        Flat list of all media items
    """
    flat_items = []
    
    for item in items:
        if item.get('type') == 'media':
            flat_items.append(item)
        elif item.get('type') == 'directory' and 'children' in item:
            # Recursively flatten children
            flat_items.extend(_flatten_items(item['children']))
    
    return flat_items


def build_index(root: Path, generate_thumbnails: bool = False, generate_motion_thumbnails: bool = False, generate_transcodes: bool = False) -> Dict:
  """Build index data for all media directories and files.

  Returns a base index; subtitle index is written separately.
  """
  log = get_logger()
  # Detect the structure type
  structure = detect_media_structure(root)
  log.debug(f"Building index for {root} (structure={structure.value}, thumbs={generate_thumbnails}, motion={generate_motion_thumbnails}, transcodes={generate_transcodes})")

  # Collect all media items using the hierarchical approach
  hierarchical_items = collect_media_items(root, generate_thumbnails, generate_motion_thumbnails, generate_transcodes)
  log.debug(f"Collected hierarchical items: {len(hierarchical_items)}")

  # Flatten the structure for search indexing
  flat_items = _flatten_items(hierarchical_items)
  log.debug(f"Flattened to {len(flat_items)} media items for search index")

  # Process items to add metadata and ensure consistent structure
  processed_items = []
  current_transcodes = set()
  for item in flat_items:
    processed_item = _process_media_item(item, root)
    if processed_item:
      processed_items.append(processed_item)
      # Collect transcoded file paths for cleanup
      if "transcoded" in processed_item:
        current_transcodes.add(processed_item["transcoded"])

  # Clean up old transcoded files if transcoding was requested
  if generate_transcodes:
    from .utils import cleanup_old_transcodes
    cleanup_old_transcodes(root, current_transcodes)
    log.debug("Cleaned up old transcodes (if any)")

  # Build both indexes, then strip bulky subtitle payloads from items
  base_search_index = _build_base_search_index(processed_items)
  subtitle_index = _build_subtitle_index(processed_items)

  for it in processed_items:
    if "subtitles" in it:
      has = bool(it.get("subtitles"))
      it.pop("subtitles", None)
      if has:
        it["has_subtitles"] = True
  log.info(f"Indexed items: {len(processed_items)} (with subtitles indexed separately)")

  return {
    "items": hierarchical_items,  # Keep hierarchical structure in output
    "structure": structure.value,
    "total_items": len(processed_items),
    "search_index": base_search_index,
    "_subtitle_index": subtitle_index,
  }


def _process_media_item(item: Dict, root: Path) -> Optional[Dict]:
    """Process a raw media item to add metadata and ensure consistent structure.

    Args:
        item: Raw item from collect_media_items
        root: Root directory

    Returns:
        Processed item dictionary or None if invalid
    """
    try:
        # Extract basic information
        name = item.get("name", "")
        created_time = item.get("created_time")
        description = None

        # Try to extract metadata from filename if no created_time
        if not created_time and "path" in item:
            file_metadata = _extract_metadata_from_filename(item["path"])
            if file_metadata["created_time"]:
                created_time = file_metadata["created_time"]

        # Try to load metadata.json if present in the same directory
        if "path" in item:
            item_path = root / item["path"]
            metadata_path = item_path.parent / "metadata.json"
            if metadata_path.exists():
                try:
                    with open(metadata_path, "r", encoding="utf-8") as f:
                        md = json.load(f)
                        name = md.get("name", name)
                        created_time = md.get("created_time", created_time)
                        description = md.get("description")
                except Exception:
                    pass

        # Use provided name as fallback
        if not name:
            name = Path(item.get("path", "unknown")).stem

        # Build the final item structure
        processed_item = {
            "name": name,
            "created_time": created_time,
            "size": item.get("size"),
            "media_type": item.get("media_type", "unknown"),
            "description": description,
            "path": item.get("path"),
            "primary_media": item.get("primary_media"),
        }

        # Add optional fields
        if "thumbs" in item:
            processed_item["thumbs"] = item["thumbs"]
        if "thumb_best" in item:
            processed_item["thumb_best"] = item["thumb_best"]
        if "motion_thumb" in item:
            processed_item["motion_thumb"] = item["motion_thumb"]
        if "transcoded" in item:
            processed_item["transcoded"] = item["transcoded"]
        if "subtitles" in item:
            processed_item["subtitles"] = item["subtitles"]

        return processed_item

    except Exception:
        return None


def _extract_metadata_from_filename(filename: str) -> Dict[str, Optional[str]]:
    """Extract basic metadata from filename for generic media files."""
    # Remove extension
    name_without_ext = Path(filename).stem

    # Try to extract date patterns like YYYY-MM-DD or YYYYMMDD
    date_patterns = [
        r'(\d{4}-\d{2}-\d{2})',  # 2023-12-25
        r'(\d{4}\d{2}\d{2})',    # 20231225
    ]

    created_time = None
    for pattern in date_patterns:
        import re
        match = re.search(pattern, name_without_ext)
        if match:
            date_str = match.group(1)
            try:
                if '-' in date_str:
                    created_time = datetime.strptime(date_str, '%Y-%m-%d').isoformat()
                else:
                    created_time = datetime.strptime(date_str, '%Y%m%d').isoformat()
                # Remove the date from the name
                name_without_ext = re.sub(pattern, '', name_without_ext).strip(' -_')
                break
            except ValueError:
                continue

    return {
        "name": name_without_ext or filename,
        "created_time": created_time,
    }


def write_index_files(root: Path, html_path: Optional[Path] = None, json_path: Optional[Path] = None, generate_thumbnails: bool = False, generate_motion_thumbnails: bool = False, generate_transcodes: bool = False) -> None:
  """Generate index.html and index.json files, plus index.subtitles.json for subtitle search."""
  root = Path(root)
  html_path = html_path or (root / "index.html")
  json_path = json_path or (root / "index.json")
  log = get_logger()

  idx = build_index(root, generate_thumbnails, generate_motion_thumbnails, generate_transcodes)

  # Write JSON (exclude the private subtitle index field)
  with open(json_path, "w", encoding="utf-8") as f:
    data = dict(idx)
    data.pop("_subtitle_index", None)
    json.dump(data, f, ensure_ascii=False, indent=2)
  log.debug(f"Wrote JSON index: {json_path}")

  # Also write a separate subtitles index for lazy loading on the client
  subs_path = json_path.with_name("index.subtitles.json")
  with open(subs_path, "w", encoding="utf-8") as f:
    json.dump(idx.get("_subtitle_index", {"subtitle_terms": {}}), f, ensure_ascii=False, indent=2)
  log.debug(f"Wrote subtitles index: {subs_path}")

  # Write HTML (load template from file)
  template_path = Path(__file__).parent / "template.html"
  html_content = template_path.read_text(encoding="utf-8")
  html_path.write_text(html_content, encoding="utf-8")
  log.debug(f"Wrote HTML index: {html_path}")

