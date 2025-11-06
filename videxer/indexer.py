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

  # Write HTML (use the template as-is)
  html_path.write_text(_INDEX_HTML, encoding="utf-8")
  log.debug(f"Wrote HTML index: {html_path}")


_INDEX_HTML = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Media Library Index</title>
  <style>
  :root { 
    color-scheme: dark;
    --bg: #0a0a0a;
    --bg-gradient: linear-gradient(135deg, #0a0a0a 0%, #111111 100%);
    --panel: rgba(20, 20, 20, 0.6);
    --nav: rgba(15, 15, 15, 0.7);
    --card: rgba(25, 25, 25, 0.5);
    --border: rgba(255, 255, 255, 0.06);
    --muted: #888888;
    --text: #e8e8e8;
    --accent: #60a5fa;
    --shadow: rgba(0, 0, 0, 0.5);
    --glass-blur: blur(20px);
  }

  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body { 
    font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; 
    margin: 0; 
    background: var(--bg);
    background-image: var(--bg-gradient);
    background-attachment: fixed;
    color: var(--text); 
  }

  .app { min-height: 100vh; display: grid; }
  /* Landscape: left sidebar */
  @media (orientation: landscape) {
    .app { grid-template-columns: 320px 1fr; }
    nav.nav { 
      position: sticky; 
      top: 0; 
      height: 100vh; 
      border-right: none;
      margin: 20px 0 20px 20px;
      border-radius: 24px;
    }
  }
  /* Portrait: top bar */
  @media (orientation: portrait) {
    .app { grid-template-rows: auto 1fr; }
    nav.nav { 
      position: sticky; 
      top: 0; 
      width: 100%; 
      border-bottom: none;
      margin: 20px 20px 0 20px;
      border-radius: 24px;
    }
  }

  nav.nav { 
    background: var(--nav); 
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    padding: 20px; 
    z-index: 10;
    box-shadow: 0 8px 32px var(--shadow);
  }
  .brand { display:flex; align-items:center; gap:10px; margin-bottom: 12px; }
  .brand-title { font-weight: 700; letter-spacing: .2px; font-size: 16px; }
  .controls { display: grid; gap: 10px; }
  .controls .row { display:flex; gap:8px; flex-wrap: wrap; }

  /* In portrait, align brand/controls horizontally when there's space */
  @media (orientation: portrait) {
    nav.nav { display: grid; grid-template-columns: 1fr; grid-auto-rows: min-content; gap: 8px; }
    .brand { margin: 0; }
  }

  .main { min-width: 0; padding: 20px; }
  .container { 
    padding: 0; 
    display: grid; 
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); 
    gap: 20px; 
    max-width: 1800px; 
    margin: 0 auto; 
  }
  .container.list { display:block; }

  .input, .select, .btn { 
    padding: 12px 16px; 
    font-size: 14px; 
    border: none;
    border-radius: 16px; 
    background: var(--panel);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    color: var(--text);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  }
  .select { background: var(--panel); }
  .btn { 
    cursor: pointer; 
    user-select: none; 
    text-decoration: none; 
    transition: all 0.3s ease;
  }
  .btn:hover { 
    background: rgba(40, 40, 40, 0.7);
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
    transform: translateY(-1px);
  }
  .hint { font-size: 12px; color: var(--muted); margin-left: 2px; }

  /* Breadcrumb navigation */
  .breadcrumb { 
    display: flex; 
    align-items: center; 
    flex-wrap: wrap; 
    gap: 8px; 
    padding: 0 0 16px 0; 
    margin-bottom: 0; 
  }
  .breadcrumb-item { 
    padding: 8px 14px; 
    font-size: 13px;
    border-radius: 12px;
  }
  .breadcrumb-sep { color: var(--muted); font-size: 12px; }

  /* Directory cards */
  .directory-media { 
    display: flex; 
    align-items: center; 
    justify-content: center; 
    min-height: 180px; 
    background: linear-gradient(135deg, rgba(30, 30, 30, 0.4) 0%, rgba(40, 40, 40, 0.4) 100%);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
  }
  .directory-icon { color: var(--accent); opacity: 0.6; transition: opacity 0.3s ease; }
  .directory-media:hover .directory-icon { opacity: 1; }

  .card { 
    background: var(--card);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: none;
    border-radius: 20px; 
    overflow: hidden; 
    display: flex; 
    flex-direction: column; 
    transition: all 0.3s ease;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  }
  .card:hover { 
    transform: translateY(-4px);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.6);
  }

  .media { position: relative; display:block; padding:0; border:0; background:transparent; cursor:pointer; overflow: hidden; border-radius: 20px 20px 0 0; }
  .thumb { width: 100%; aspect-ratio: 16/9; object-fit: cover; background: #0a0a0a; display:block; }
  .motion-thumb { width: 100%; height: 100%; object-fit: cover; background: #0a0a0a; position: absolute; top: 0; left: 0; opacity: 0; pointer-events: none; transition: opacity .2s ease; }
  .play { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; background: linear-gradient(180deg, rgba(0,0,0,0) 40%, rgba(0,0,0,0.5) 100%); opacity: 0; transition: opacity .3s; }
  .media:hover .play { opacity: 1; }
  .play-icon { 
    width: 64px; 
    height: 64px; 
    border-radius: 50%; 
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 2px solid rgba(255, 255, 255, 0.2); 
    display: grid; 
    place-items: center;
    transition: all 0.3s ease;
  }
  .media:hover .play-icon {
    transform: scale(1.1);
    background: rgba(0, 0, 0, 0.7);
  }
  .play-icon svg { width:24px; height:24px; fill: #fff; transform: translateX(2px); }
  .content { padding: 16px; display:flex; flex-direction: column; gap: 10px; }
  .title { font-size: 14px; font-weight: 600; margin: 0; }
  .title button { background: none; border: 0; color: var(--text); font: inherit; cursor: pointer; padding: 0; }
  .title button:hover { text-decoration: underline; }
  .meta { font-size: 12px; color: var(--muted); display:flex; gap:8px; flex-wrap: wrap; }
  .badge { 
    border: none;
    background: rgba(40, 40, 40, 0.6);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border-radius: 12px; 
    padding: 4px 10px;
  }
  .row .btn { background: transparent; }
  .container.list .card { display:flex; flex-direction: row; align-items: stretch; }
  .container.list .media { width: 260px; min-width:260px; border-radius: 20px 0 0 20px; }
  .container.list .thumb { width: 100%; height: 100%; aspect-ratio: unset; object-fit: cover; }
  .container.list .content { flex: 1; }

  /* Accessibility helpers */
  .visually-hidden { position: absolute !important; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
  .input:focus, .select:focus, .btn:focus { outline: 2px solid rgba(96, 165, 250, 0.5); outline-offset: 2px; }

  /* Modal media player */
  .modal { position: fixed; inset: 0; display:none; align-items:center; justify-content:center; background: rgba(0, 0, 0, 0.85); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); z-index: 50; }
  .modal.open { display:flex; }
  .modal-dialog { 
    width: min(90vw, 1200px); 
    background: var(--card);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: none;
    border-radius: 24px; 
    overflow: hidden; 
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.8);
  }
  .modal-header { 
    display: flex; 
    justify-content: space-between; 
    align-items: center; 
    padding: 16px 20px; 
    border-bottom: none;
    background: rgba(20, 20, 20, 0.6);
  }
  .modal-title { font-size: 15px; font-weight: 600; }
  .modal-close { 
    background: rgba(40, 40, 40, 0.6);
    border: none;
    border-radius: 12px;
    color: var(--text); 
    font-size: 24px; 
    cursor: pointer;
    padding: 4px 12px;
    line-height: 1;
    transition: all 0.3s ease;
  }
  .modal-close:hover {
    background: rgba(60, 60, 60, 0.8);
  }
  .modal-body { background: #000; }
  video, audio { display:block; width:100%; height:auto; background:#000; }
  img.modal-image { display:block; max-width:100%; max-height:80vh; margin:0 auto; }

  /* Immersive mobile player */
  :root { --immersive-header-h: 56px; }
  body.immersive-open { overflow: hidden; }
  .immersive { 
    position: fixed; 
    inset: 0; 
    z-index: 60; 
    display: none; 
    background: var(--bg); 
    color: var(--text); 
  }
  .immersive.open { display: flex; flex-direction: column; }
  .immersive-header { 
    position: relative; 
    height: var(--immersive-header-h); 
    display: flex; 
    align-items: center; 
    gap: 12px; 
    padding: 12px 16px; 
    background: var(--nav);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border-bottom: none;
    flex-shrink: 0;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
  }
  .immersive-title { 
    font-size: 15px; 
    font-weight: 600; 
    flex: 1; 
    overflow: hidden; 
    text-overflow: ellipsis; 
    white-space: nowrap; 
  }
  .immersive-close { 
    background: rgba(40, 40, 40, 0.6);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: none;
    border-radius: 14px; 
    color: var(--text); 
    padding: 8px 14px; 
    cursor: pointer;
    transition: all 0.3s ease;
  }
  .immersive-close:hover {
    background: rgba(60, 60, 60, 0.8);
  }
  .quality { display:flex; gap:8px; align-items:center; }
  .quality .btn { padding:8px 12px; }
  .quality .btn.active { 
    background: rgba(96, 165, 250, 0.2);
    box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.4);
  }
  .immersive-content { position: relative; flex: 1; overflow: hidden; }
  .immersive-media { position: relative; width: 100%; background: #000; height: min(56vh, calc(100vw * 9 / 16)); }
  .immersive-media > video, .immersive-media > img { width: 100%; height: 100%; object-fit: contain; display: block; background: #000; }
  .immersive-info { 
    position: absolute; 
    top: min(56vh, calc(100vw * 9 / 16)); 
    bottom: 0; 
    left: 0; 
    right: 0; 
    overflow: auto; 
    padding: 20px; 
    background: var(--bg);
  }
  .immersive .meta { margin-top: 8px; }
  .immersive .row { margin-top: 8px; }
  
  /* Mobile landscape: fullscreen video without info panel */
  @media (orientation: landscape) and (max-width: 1023px) {
    .immersive-header { 
      position: fixed; 
      top: 0; 
      left: 0; 
      right: 0; 
      z-index: 61; 
      background: linear-gradient(to bottom, rgba(0, 0, 0, 0.6), rgba(0, 0, 0, 0));
      backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px);
      color: #fff; 
      border-bottom: none; 
    }
    .immersive-close { 
      border: none;
      color: #fff; 
      background: rgba(0, 0, 0, 0.5);
    }
    .immersive-content { position: absolute; inset: 0; }
    .immersive-media { height: 100%; }
    .immersive-info { display: none; }
  }
  
  /* Desktop: side-by-side video and info panel */
  @media (min-width: 1024px) {
    .immersive-content { display: flex; }
    .immersive-media { flex: 1; height: 100%; }
    .immersive-info { 
      position: relative; 
      top: 0; 
      width: 400px; 
      flex-shrink: 0; 
      height: 100%; 
      padding: 24px; 
      border-left: none;
      background: var(--card);
      backdrop-filter: var(--glass-blur);
      -webkit-backdrop-filter: var(--glass-blur);
    }
  }
  </style>
  <script>
    async function fetchJSON(path) {
      const res = await fetch(path);
      if (!res.ok) throw new Error('Failed to load ' + path);
      return res.json();
    }

  function fmtDate(s) {
      if (!s) return '';
      try { return new Date(s).toLocaleString(); } catch { return s; }
    }

    function fmtSize(bytes) {
      if (bytes == null) return '';
      const units = ['B','KB','MB','GB','TB'];
      let n = Number(bytes);
      let i = 0;
      while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
      return n.toFixed(n >= 10 || i === 0 ? 0 : 1) + ' ' + units[i];
    }

    function pickThumb(it) {
      // Prefer explicit best thumbnail if present; else last in thumbs[]
      if (it.thumb_best) return it.thumb_best;
      if (it.thumbs && it.thumbs.length) return it.thumbs[it.thumbs.length - 1];
      return '';
    }

    function getMediaIcon(type) {
      switch(type) {
        case 'video': return '<svg viewBox=\"0 0 24 24\" width=\"22\" height=\"22\"><path d=\"M8 5v14l11-7z\" fill=\"#fff\"></path></svg>';
        case 'audio': return '<svg viewBox=\"0 0 24 24\" width=\"22\" height=\"22\"><path d=\"M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z\" fill=\"#fff\"></path></svg>';
        case 'image': return '<svg viewBox=\"0 0 24 24\" width=\"22\" height=\"22\"><path d=\"M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z\" fill=\"#fff\"></path></svg>';
        default: return '<svg viewBox=\"0 0 24 24\" width=\"22\" height=\"22\"><path d=\"M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z\" fill=\"#fff\"></path></svg>';
      }
    }

    async function load() {
      const data = await fetchJSON('index.json');
      const container = document.querySelector('.container');
      const search = document.getElementById('search');
      const sortSel = document.getElementById('sort');
      const dirBtn = document.getElementById('direction');
      const viewBtn = document.getElementById('view');
      const breadcrumbEl = document.getElementById('breadcrumb');
      
      let allItems = data.items || [];
      let currentPath = []; // Stack of directory names
      let currentItems = allItems; // Items in current view
      let searchIndex = data.search_index || { subtitle_terms: {}, name_terms: {}, description_terms: {}, item_map: [] };
      let sortKey = 'date'; // alpha | size | date | type
      let sortDir = 'desc'; // asc | desc
      let viewMode = 'grid'; // grid | list

      function updateBreadcrumb() {
        breadcrumbEl.innerHTML = '';
        
        // Root/home button
        const homeBtn = document.createElement('button');
        homeBtn.className = 'breadcrumb-item btn';
        homeBtn.textContent = '🏠 Library';
        homeBtn.addEventListener('click', () => navigateToRoot());
        breadcrumbEl.appendChild(homeBtn);
        
        // Path segments
        currentPath.forEach((dirName, idx) => {
          const sep = document.createElement('span');
          sep.className = 'breadcrumb-sep';
          sep.textContent = ' / ';
          breadcrumbEl.appendChild(sep);
          
          const btn = document.createElement('button');
          btn.className = 'breadcrumb-item btn';
          btn.textContent = dirName;
          btn.addEventListener('click', () => navigateToIndex(idx + 1));
          breadcrumbEl.appendChild(btn);
        });
      }
      
      function navigateToRoot() {
        currentPath = [];
        currentItems = allItems;
        search.value = '';
        apply();
      }
      
      function navigateToIndex(pathIndex) {
        // Navigate to a specific depth in the path
        currentPath = currentPath.slice(0, pathIndex);
        
        // Navigate through hierarchy to find current items
        currentItems = allItems;
        for (const dirName of currentPath) {
          const dir = currentItems.find(item => item.type === 'directory' && item.name === dirName);
          if (dir && dir.children) {
            currentItems = dir.children;
          } else {
            // Path not found, go to root
            currentPath = [];
            currentItems = allItems;
            break;
          }
        }
        
        search.value = '';
        apply();
      }
      
      function navigateInto(dirName) {
        const dir = currentItems.find(item => item.type === 'directory' && item.name === dirName);
        if (dir && dir.children) {
          currentPath.push(dirName);
          currentItems = dir.children;
          search.value = '';
          apply();
        }
      }

      function render(list) {
        container.innerHTML = '';
        container.classList.toggle('list', viewMode === 'list');
        updateBreadcrumb();
        
        for (const it of list) {
          const card = document.createElement('div');
          card.className = 'card';
          
          if (it.type === 'directory') {
            // Render directory card
            const dirBtn = document.createElement('button');
            dirBtn.className = 'media directory-media';
            dirBtn.type = 'button';
            
            const icon = document.createElement('div');
            icon.className = 'directory-icon';
            icon.innerHTML = '<svg viewBox="0 0 24 24" width="64" height="64"><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z" fill="currentColor"/></svg>';
            dirBtn.appendChild(icon);
            
            dirBtn.addEventListener('click', () => navigateInto(it.name));
            card.appendChild(dirBtn);
            
            const content = document.createElement('div');
            content.className = 'content';
            
            const title = document.createElement('div');
            title.className = 'title';
            const titleBtn = document.createElement('button');
            titleBtn.type = 'button';
            titleBtn.textContent = it.name;
            titleBtn.addEventListener('click', () => navigateInto(it.name));
            title.appendChild(titleBtn);
            
            const meta = document.createElement('div');
            meta.className = 'meta';
            const typeEl = document.createElement('span');
            typeEl.className = 'badge';
            typeEl.textContent = 'Folder';
            meta.appendChild(typeEl);
            
            content.appendChild(title);
            content.appendChild(meta);
            card.appendChild(content);
            container.appendChild(card);
          } else {
            // Render media card (existing logic)
            const media = document.createElement('button');
            media.className = 'media';
            media.type = 'button';
            const img = document.createElement('img');
            img.className = 'thumb';
            img.loading = 'lazy';
            const thumbSrc = pickThumb(it);
            const motionThumbSrc = it.motion_thumb;
            if (thumbSrc) {
              img.src = thumbSrc;
              img.alt = it.name || it.dir;
            } else {
              img.src = 'data:image/svg+xml;base64,' + btoa('<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"320\" height=\"180\" viewBox=\"0 0 320 180\"><rect width=\"320\" height=\"180\" fill=\"#1f2937\"/><text x=\"160\" y=\"90\" text-anchor=\"middle\" fill=\"#9ca3af\" font-family=\"system-ui\" font-size=\"14\">' + it.media_type + '</text></svg>');
              img.alt = it.name || it.dir;
            }
            media.appendChild(img);
            const overlay = document.createElement('div');
            overlay.className = 'play';
            overlay.innerHTML = '<div class=\"play-icon\">' + getMediaIcon(it.media_type) + '</div>';
            media.appendChild(overlay);

            if (motionThumbSrc && thumbSrc) {
              const motionVideo = document.createElement('video');
              motionVideo.className = 'motion-thumb';
              motionVideo.src = motionThumbSrc;
              motionVideo.muted = true;
              motionVideo.loop = true;
              motionVideo.preload = 'none';
              media.appendChild(motionVideo);

              media.addEventListener('mouseenter', () => {
                motionVideo.style.opacity = '1';
                motionVideo.play().catch(() => {});
              });

              media.addEventListener('mouseleave', () => {
                motionVideo.style.opacity = '0';
                motionVideo.pause();
                motionVideo.currentTime = 0;
              });
            }
            if (it.primary_media) {
              if (it.media_type === 'image') {
                media.addEventListener('click', () => openImageViewer(it.primary_media, it.name || it.dir));
              } else {
                media.addEventListener('click', () => openPlayer(it, it.name || it.dir, it.media_type));
              }
            }
            card.appendChild(media);

            const content = document.createElement('div');
            content.className = 'content';
            const title = document.createElement('div');
            title.className = 'title';
            if (it.primary_media) {
              const tbtn = document.createElement('button');
              tbtn.type = 'button';
              tbtn.textContent = it.name || it.dir;
              if (it.media_type === 'image') {
                tbtn.addEventListener('click', () => openImageViewer(it.primary_media, it.name || it.dir));
              } else {
                tbtn.addEventListener('click', () => openPlayer(it, it.name || it.dir, it.media_type));
              }
              title.appendChild(tbtn);
            } else {
              title.textContent = it.name || it.dir;
            }
            const meta = document.createElement('div');
            meta.className = 'meta';
            const typeEl = document.createElement('span');
            typeEl.className = 'badge';
            typeEl.textContent = it.media_type.charAt(0).toUpperCase() + it.media_type.slice(1);
            const dateEl = document.createElement('span');
            dateEl.className = 'badge';
            dateEl.textContent = fmtDate(it.created_time);
            const sizeEl = document.createElement('span');
            sizeEl.className = 'badge';
            sizeEl.textContent = fmtSize(it.size);
            const subtitleEl = document.createElement('span');
            subtitleEl.className = 'badge';
            subtitleEl.textContent = 'CC';
            subtitleEl.title = 'Has subtitles';
            if (typeEl.textContent) meta.appendChild(typeEl);
            if (dateEl.textContent) meta.appendChild(dateEl);
            if (sizeEl.textContent) meta.appendChild(sizeEl);
            if (it.has_subtitles) meta.appendChild(subtitleEl);
            const row = document.createElement('div');
            row.className = 'row';
            if (it.analytics) { const a = document.createElement('a'); a.href = it.analytics; a.className='btn'; a.textContent='Analytics JSON'; row.appendChild(a); }
            if (it.metadata) { const a = document.createElement('a'); a.href = it.metadata; a.className='btn'; a.textContent='Metadata JSON'; row.appendChild(a); }
            content.appendChild(title);
            content.appendChild(meta);
            if (row.children.length) content.appendChild(row);
            card.appendChild(content);
            container.appendChild(card);
          }
        }
      }

      function sortItems(list) {
        const arr = [...list];
        const dir = sortDir === 'asc' ? 1 : -1;
        
        // Sort directories first, then media items
        arr.sort((a, b) => {
          // Directories always come before media when not searching
          if (a.type === 'directory' && b.type !== 'directory') return -1;
          if (a.type !== 'directory' && b.type === 'directory') return 1;
          
          if (sortKey === 'alpha') {
            const an = (a.name || '').toLowerCase();
            const bn = (b.name || '').toLowerCase();
            if (an < bn) return -1 * dir; if (an > bn) return 1 * dir; return 0;
          } else if (sortKey === 'size') {
            const av = a.size || 0; const bv = b.size || 0; return (av - bv) * dir;
          } else if (sortKey === 'date') {
            const at = a.created_time ? Date.parse(a.created_time) : 0;
            const bt = b.created_time ? Date.parse(b.created_time) : 0;
            return (at - bt) * dir;
          } else if (sortKey === 'type') {
            const at = a.media_type || '';
            const bt = b.media_type || '';
            if (at < bt) return -1 * dir; if (at > bt) return 1 * dir; return 0;
          }
          return 0;
        });
        return arr;
      }

      function extractVideoId(dirName) {
        const match = dirName.match(/ - (\\d+)$/);
        return match ? match[1] : '';
      }

      // Flatten entire tree for search
      function flattenAllItems(items) {
        let flat = [];
        for (const item of items) {
          if (item.type === 'media') {
            flat.push(item);
          } else if (item.type === 'directory' && item.children) {
            flat = flat.concat(flattenAllItems(item.children));
          }
        }
        return flat;
      }

      function apply() {
        const q = search.value.toLowerCase().trim();
        let filtered;

        if (!q) {
          // No search query, show current directory items
          filtered = currentItems;
        } else {
          // When searching, flatten all items and search across entire library
          const allFlatItems = flattenAllItems(allItems);
          
          // If subtitle index isn't loaded, fetch it in the background
          if (!searchIndex.subtitle_terms) searchIndex.subtitle_terms = {};
          if (Object.keys(searchIndex.subtitle_terms).length === 0) {
            fetchJSON('index.subtitles.json')
              .then(subs => {
                searchIndex.subtitle_terms = subs.subtitle_terms || {};
                apply();
              })
              .catch(() => {});
          }
          
          // Use search index for efficient filtering
          if (searchIndex.item_map && searchIndex.item_map.length > 0) {
            const matchingIndices = new Set();

            for (const term in searchIndex.name_terms) {
              if (term.includes(q)) {
                searchIndex.name_terms[term].forEach(idx => matchingIndices.add(idx));
              }
            }

            for (const term in searchIndex.description_terms) {
              if (term.includes(q)) {
                searchIndex.description_terms[term].forEach(idx => matchingIndices.add(idx));
              }
            }

            if (searchIndex.subtitle_terms) {
              for (const term in searchIndex.subtitle_terms) {
                if (term.includes(q)) {
                  searchIndex.subtitle_terms[term].forEach(idx => matchingIndices.add(idx));
                }
              }
            }

            filtered = Array.from(matchingIndices).map(idx => allFlatItems[idx]).filter(Boolean);
          } else {
            // Fallback to direct search
            filtered = allFlatItems.filter(it => {
              const name = (it.name || '').toLowerCase();
              const path = (it.path || '').toLowerCase();
              const type = (it.media_type || '').toLowerCase();
              const description = (it.description || '').toLowerCase();

              return name.includes(q) ||
                     path.includes(q) ||
                     type.includes(q) ||
                     description.includes(q);
            });
          }
        }

        const sorted = sortItems(filtered);
        render(sorted);
      }

      // Initialize controls
      apply();
      search.addEventListener('input', () => {
        apply();
      });
      sortSel.addEventListener('change', () => { sortKey = sortSel.value; apply(); });
      dirBtn.addEventListener('click', () => {
        sortDir = (sortDir === 'asc') ? 'desc' : 'asc';
        dirBtn.textContent = (sortDir === 'asc') ? 'Ascending' : 'Descending';
        apply();
      });
      viewBtn.addEventListener('click', () => {
        viewMode = (viewMode === 'grid') ? 'list' : 'grid';
        viewBtn.textContent = viewMode === 'grid' ? 'Grid' : 'List';
        apply();
      });

      // Modal wiring
      const modal = document.getElementById('playerModal');
      const modalTitle = document.getElementById('playerTitle');
      const mediaEl = document.getElementById('playerMedia');
      const closeBtn = document.getElementById('playerClose');
      function close() {
        modal.classList.remove('open');
        // Stop playback and release resource
        if (mediaEl.tagName === 'VIDEO' || mediaEl.tagName === 'AUDIO') {
          mediaEl.pause();
          mediaEl.removeAttribute('src');
          mediaEl.load();
        }
      }
      closeBtn.addEventListener('click', close);
      modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
      window.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });

      // Immersive player elements
      const immersive = document.getElementById('immersive');
      const immTitle = document.getElementById('immersiveTitle');
      const immMedia = document.getElementById('immersiveMedia');
      const immInfo = document.getElementById('immersiveInfo');
  const immClose = document.getElementById('immersiveClose');
  const qWrap = document.getElementById('qualityControls');

      function isDesktop() {
        return window.matchMedia('(min-width: 1024px)').matches && window.matchMedia('(pointer: fine)').matches;
      }

      function updateImmersiveOrientation() {
        if (!immersive.classList.contains('open')) return;
        const isLand = window.matchMedia('(orientation: landscape)').matches;
        immersive.classList.toggle('landscape', isLand);
      }
      window.addEventListener('resize', updateImmersiveOrientation);

      function openImmersive(item, title, type) {
        document.body.classList.add('immersive-open');
        immTitle.textContent = title || 'Media';
        immMedia.innerHTML = '';
        immInfo.innerHTML = '';
        const hasOptimized = !!item.transcoded;
        const hasOriginal = !!item.primary_media;
        let currentQuality = hasOptimized ? 'optimized' : 'original';
        const pickSrc = () => (currentQuality === 'optimized' ? item.transcoded : item.primary_media) || item.primary_media || item.transcoded;
        const src = pickSrc();
        if (type === 'video') {
          const video = document.createElement('video');
          video.setAttribute('controls', '');
          video.setAttribute('preload', 'metadata');
          video.src = src;
          immMedia.appendChild(video);
          // Do not force autoplay on mobile; rely on user interaction
        } else if (type === 'audio') {
          const audio = document.createElement('audio');
          audio.setAttribute('controls', '');
          audio.setAttribute('preload', 'metadata');
          audio.style.width = '100%';
          audio.src = src;
          immMedia.appendChild(audio);
        } else if (type === 'image') {
          const img = document.createElement('img');
          img.alt = title || 'Image';
          img.src = src;
          immMedia.appendChild(img);
        }

        // Build quality controls (for video/audio)
        if (qWrap) {
          qWrap.innerHTML = '';
          if ((type === 'video' || type === 'audio') && (hasOptimized || hasOriginal)) {
            const makeBtn = (label, q) => {
              const b = document.createElement('button');
              b.type = 'button';
              b.className = 'btn';
              b.textContent = label;
              b.addEventListener('click', () => {
                if (currentQuality === q) return;
                const media = immMedia.querySelector(type);
                if (!media) return;
                const t = media.currentTime || 0;
                currentQuality = q;
                media.pause();
                media.src = pickSrc();
                try { media.currentTime = t; } catch {}
                media.play().catch(() => {});
                updateActive();
              });
              return b;
            };
            const updateActive = () => {
              [...qWrap.querySelectorAll('button')].forEach(btn => btn.classList.remove('active'));
              const target = currentQuality === 'optimized' ? btnOpt : btnOrig;
              if (target) target.classList.add('active');
            };
            let btnOpt = null, btnOrig = null;
            if (hasOptimized) btnOpt = makeBtn('Optimized', 'optimized');
            if (hasOriginal) btnOrig = makeBtn('Original', 'original');
            if (btnOpt) qWrap.appendChild(btnOpt);
            if (btnOrig) qWrap.appendChild(btnOrig);
            updateActive();
            qWrap.style.display = (hasOptimized && hasOriginal) ? 'flex' : 'none';
          } else {
            qWrap.style.display = 'none';
          }
        }

        // Build metadata/details
        const meta = document.createElement('div');
        meta.className = 'meta';
        const typeEl = document.createElement('span'); typeEl.className = 'badge'; typeEl.textContent = (item.media_type||'').replace(/^./, c=>c.toUpperCase());
        const dateEl = document.createElement('span'); dateEl.className = 'badge'; dateEl.textContent = fmtDate(item.created_time);
        const sizeEl = document.createElement('span'); sizeEl.className = 'badge'; sizeEl.textContent = fmtSize(item.size);
        const subtitleEl = document.createElement('span'); subtitleEl.className = 'badge'; subtitleEl.textContent = 'CC'; subtitleEl.title = 'Has subtitles';
  if (typeEl.textContent) meta.appendChild(typeEl);
  if (dateEl.textContent) meta.appendChild(dateEl);
  if (sizeEl.textContent) meta.appendChild(sizeEl);
  if (item.has_subtitles) meta.appendChild(subtitleEl);

        const links = document.createElement('div');
        links.className = 'row';
        if (item.analytics) { const a = document.createElement('a'); a.href = item.analytics; a.className='btn'; a.textContent='Analytics JSON'; links.appendChild(a); }
        if (item.metadata) { const a = document.createElement('a'); a.href = item.metadata; a.className='btn'; a.textContent='Metadata JSON'; links.appendChild(a); }

        const wrap = document.createElement('div');
        const heading = document.createElement('div'); heading.className='title'; heading.textContent = title || 'Media';
        wrap.appendChild(heading);
        wrap.appendChild(meta);
        
        // Add description if available
        if (item.description) {
          const descEl = document.createElement('p');
          descEl.style.marginTop = '12px';
          descEl.style.lineHeight = '1.5';
          descEl.textContent = item.description;
          wrap.appendChild(descEl);
        }
        
        // Add download button for original file
        if (item.primary_media || item.transcoded) {
          const downloadBtn = document.createElement('a');
          downloadBtn.href = item.primary_media || item.transcoded;
          downloadBtn.download = '';
          downloadBtn.className = 'btn';
          downloadBtn.style.marginTop = '12px';
          downloadBtn.style.display = 'inline-block';
          downloadBtn.textContent = '⬇ Download Original';
          downloadBtn.title = 'Download the original file';
          wrap.appendChild(downloadBtn);
        }
        
        if (links.children.length) wrap.appendChild(links);
        immInfo.appendChild(wrap);

        immersive.classList.add('open');
        updateImmersiveOrientation();
      }

      function closeImmersive() {
        document.body.classList.remove('immersive-open');
        // Stop playback and release resource
        const media = immMedia.querySelector('video, audio');
        if (media) { try { media.pause(); } catch(e){} media.removeAttribute('src'); media.load && media.load(); }
        immersive.classList.remove('open');
      }
      immClose.addEventListener('click', closeImmersive);

      window.openPlayer = (item, title, type) => {
        // Always use immersive view for consistent UI and quality control
        openImmersive(item, title, type);
      };

      window.openImageViewer = (src, title) => {
        if (isDesktop()) {
          modalTitle.textContent = title || 'Image';
          mediaEl.innerHTML = '<img class=\"modal-image\" alt=\"' + (title || 'Image') + '\">';
          const img = mediaEl.querySelector('img');
          img.setAttribute('src', src);
          modal.classList.add('open');
        } else {
          const item = { primary_media: src, media_type: 'image' };
          openImmersive(item, title || 'Image', 'image');
        }
      };
    }

    window.addEventListener('DOMContentLoaded', load);
  </script>
</head>
<body>
  <div class="app">
    <nav class="nav" aria-label="Library controls">
      <div class="brand">
        <span class="brand-title">Media Library</span>
      </div>
      <div class="controls">
        <label for="search" class="visually-hidden">Search</label>
  <input id="search" class="input" placeholder="Search media, subtitles, descriptions..." />
        <div class="row">
          <label for="sort" class="visually-hidden">Sort by</label>
          <select id="sort" class="select">
            <option value="date" selected>Date</option>
            <option value="alpha">Alphabetical</option>
            <option value="size">Size</option>
            <option value="type">Type</option>
          </select>
          <button id="direction" class="btn" aria-pressed="false">Descending</button>
          <button id="view" class="btn" aria-pressed="false">Grid</button>
        </div>
      </div>
    </nav>
    <main class="main" role="main">
      <div id="breadcrumb" class="breadcrumb" style="padding: 12px 18px 0 18px;"></div>
      <div class="container"></div>
    </main>
  </div>

  <!-- Modal media player/viewer -->
  <div id="playerModal" class="modal" role="dialog" aria-modal="true" aria-labelledby="playerTitle">
    <div class="modal-dialog">
      <div class="modal-header">
        <div id="playerTitle" class="modal-title">Media</div>
        <button id="playerClose" class="modal-close" aria-label="Close">×</button>
      </div>
      <div id="playerMedia" class="modal-body">
      </div>
    </div>
  </div>

    <!-- Immersive player for mobile/tablets -->
    <div id="immersive" class="immersive" aria-hidden="true">
      <div class="immersive-header">
        <button id="immersiveClose" class="immersive-close" aria-label="Close">Back</button>
        <div id="immersiveTitle" class="immersive-title">Media</div>
        <div id="qualityControls" class="quality" style="display:none"></div>
      </div>
      <div class="immersive-content">
        <div id="immersiveMedia" class="immersive-media"></div>
        <div id="immersiveInfo" class="immersive-info"></div>
      </div>
    </div>
</body>
</html>"""
