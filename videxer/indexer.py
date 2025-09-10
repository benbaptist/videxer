from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
import json
import os
from datetime import datetime

from .utils import collect_media_items, detect_media_structure, MediaStructure, generate_video_thumbnail


# Extended media extensions
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".wmv", ".flv", ".m4a"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}
ALL_MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS


def _build_search_index(items: List[Dict]) -> Dict:
    """Build a search index for efficient text and subtitle search.

    Args:
        items: List of processed media items

    Returns:
        Search index dictionary
    """
    search_index = {
        "subtitle_terms": {},  # term -> [item_indices]
        "name_terms": {},      # term -> [item_indices]
        "description_terms": {}, # term -> [item_indices]
        "item_map": []        # index -> item_id for reverse lookup
    }

    for idx, item in enumerate(items):
        item_id = f"{item.get('type', 'unknown')}_{item.get('path', item.get('dir', str(idx)))}"
        search_index["item_map"].append(item_id)

        # Index name
        name = item.get("name", "").lower()
        if name:
            _add_to_search_index(search_index["name_terms"], name, idx)

        # Index description
        description = item.get("description") or ""
        if description:
            description = str(description).lower()
            _add_to_search_index(search_index["description_terms"], description, idx)

        # Index subtitle text
        if "subtitles" in item:
            for subtitle in item["subtitles"]:
                combined_text = subtitle.get("text_combined", "").lower()
                if combined_text:
                    _add_to_search_index(search_index["subtitle_terms"], combined_text, idx)

    return search_index


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


def build_index(root: Path, generate_thumbnails: bool = False, generate_motion_thumbnails: bool = False, generate_transcodes: bool = False) -> Dict:
    """Build index data for all media directories and files."""
    # Detect the structure type
    structure = detect_media_structure(root)

    # Collect all media items using the unified approach
    raw_items = collect_media_items(root, generate_thumbnails, generate_motion_thumbnails, generate_transcodes)

    # Process items to add metadata and ensure consistent structure
    items = []
    current_transcodes = set()
    for item in raw_items:
        processed_item = _process_media_item(item, root)
        if processed_item:
            items.append(processed_item)
            # Collect transcoded file paths for cleanup
            if "transcoded" in processed_item:
                current_transcodes.add(processed_item["transcoded"])

    # Clean up old transcoded files if transcoding was requested
    if generate_transcodes:
        from .utils import cleanup_old_transcodes
        cleanup_old_transcodes(root, current_transcodes)

    # Build search index for efficient subtitle and text search
    search_index = _build_search_index(items)

    return {
        "items": items,
        "structure": structure.value,
        "total_items": len(items),
        "search_index": search_index
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
        created_time = None
        description = None

        # Handle metadata extraction based on item type
        if item["type"] == "file":
            # For flat files, extract metadata from filename
            file_metadata = _extract_metadata_from_filename(item["path"])
            name = file_metadata["name"] or name
            created_time = file_metadata["created_time"]
        else:
            # For directories, try to load metadata.json if present
            if "metadata" in item:
                try:
                    metadata_path = root / item["metadata"]
                    with open(metadata_path, "r", encoding="utf-8") as f:
                        md = json.load(f)
                        name = md.get("name", name)
                        created_time = md.get("created_time")
                        description = md.get("description")
                except Exception:
                    pass

        # Use directory/file name as fallback
        if not name:
            if item["type"] == "file":
                name = Path(item["path"]).stem
            else:
                name = item["dir"]

        # Build the final item structure
        processed_item = {
            "name": name,
            "created_time": created_time,
            "size": item.get("size"),
            "media_type": item.get("media_type", "unknown"),
            "description": description,
        }

        # Add type-specific fields
        if item["type"] == "file":
            processed_item.update({
                "path": item["path"],
                "primary_media": item["path"],
            })

            # Add optional fields for files
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
        else:
            processed_item.update({
                "dir": item["dir"],
                "media_files": item.get("media_files", []),
                "primary_media": item.get("primary_media"),
            })

            # Add optional fields for directories
            if "metadata" in item:
                processed_item["metadata"] = item["metadata"]
            if "analytics" in item:
                processed_item["analytics"] = item["analytics"]
            if "thumbs" in item:
                processed_item["thumbs"] = item["thumbs"]
            if "thumb_best" in item:
                processed_item["thumb_best"] = item["thumb_best"]
            if "motion_thumb" in item:
                processed_item["motion_thumb"] = item["motion_thumb"]
            if "transcoded" in item:
                processed_item["transcoded"] = item["transcoded"]
            if "video" in item:
                processed_item["video"] = item["video"]
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
    """Generate index.html and index.json files."""
    root = Path(root)
    html_path = html_path or (root / "index.html")
    json_path = json_path or (root / "index.json")

    idx = build_index(root, generate_thumbnails, generate_motion_thumbnails, generate_transcodes)

    # Write JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)

    # Write HTML (use the template as-is)
    html_path.write_text(_INDEX_HTML, encoding="utf-8")


_INDEX_HTML = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Media Library Index</title>
  <style>
  :root { color-scheme: light dark; }
  @media (prefers-color-scheme: light) {
    :root {
      --bg:#f6f7fb; --panel:#ffffff; --nav:#ffffff; --card:#ffffff; --border:#e5e7eb; --muted:#6b7280; --text:#0f172a; --accent:#2563eb; --shadow: rgba(0,0,0,0.06);
    }
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#0b0c10; --panel:#0f172a; --nav:#0f172a; --card:#111827; --border:#1f2937; --muted:#9aa3b2; --text:#e5e7eb; --accent:#60a5fa; --shadow: rgba(0,0,0,0.35);
    }
  }

  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; background: var(--bg); color: var(--text); }

  .app { min-height: 100vh; display: grid; }
  /* Landscape: left sidebar */
  @media (orientation: landscape) {
    .app { grid-template-columns: 290px 1fr; }
    nav.nav { position: sticky; top: 0; height: 100vh; border-right: 1px solid var(--border); }
  }
  /* Portrait: top bar */
  @media (orientation: portrait) {
    .app { grid-template-rows: auto 1fr; }
    nav.nav { position: sticky; top: 0; width: 100%; border-bottom: 1px solid var(--border); }
  }

  nav.nav { background: var(--nav); padding: 14px 16px; z-index: 10; }
  .brand { display:flex; align-items:center; gap:10px; margin-bottom: 12px; }
  .brand-title { font-weight: 700; letter-spacing: .2px; font-size: 16px; }
  .controls { display: grid; gap: 10px; }
  .controls .row { display:flex; gap:8px; flex-wrap: wrap; }

  /* In portrait, align brand/controls horizontally when there's space */
  @media (orientation: portrait) {
    nav.nav { display: grid; grid-template-columns: 1fr; grid-auto-rows: min-content; gap: 8px; }
    .brand { margin: 0; }
  }

  .main { min-width: 0; }
  .container { padding: 18px; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; max-width: 1600px; margin: 0 auto; }
  .container.list { display:block; }

  .input, .select, .btn { padding:10px 12px; font-size:14px; border:1px solid var(--border); border-radius:10px; background: var(--panel); color: var(--text); }
  .select { background: var(--panel); }
  .btn { cursor:pointer; user-select:none; text-decoration:none; transition: border-color .2s, background .2s; }
  .btn:hover { border-color: color-mix(in oklab, var(--border), var(--accent) 35%); background: color-mix(in oklab, var(--panel), var(--accent) 8%); }
  .hint { font-size: 12px; color: var(--muted); margin-left: 2px; }

  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; display: flex; flex-direction: column; transition: border-color .18s ease; box-shadow: 0 1px 4px var(--shadow); }
  /* Remove lift/translate hover animation */
  .card:hover { border-color: color-mix(in oklab, var(--border), var(--accent) 35%); }

  .media { position: relative; display:block; padding:0; border:0; background:transparent; cursor:pointer; overflow: hidden; }
  .thumb { width: 100%; aspect-ratio: 16/9; object-fit: cover; background: #0f172a; display:block; }
  .motion-thumb { width: 100%; height: 100%; object-fit: cover; background: #0f172a; position: absolute; top: 0; left: 0; opacity: 0; pointer-events: none; transition: opacity .2s ease; }
  .play { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; background: linear-gradient(180deg, rgba(0,0,0,0) 40%, rgba(0,0,0,0.35) 100%); opacity: 0; transition: opacity .2s; }
  .media:hover .play { opacity: 1; }
  .play-icon { width: 56px; height:56px; border-radius: 999px; background: rgba(0,0,0,0.55); border:1px solid rgba(255,255,255,0.15); display:grid; place-items:center; }
  .play-icon svg { width:22px; height:22px; fill: #fff; transform: translateX(2px); }
  .content { padding: 12px; display:flex; flex-direction: column; gap: 8px; }
  .title { font-size: 14px; font-weight: 700; margin: 0; }
  .title button { background: none; border: 0; color: var(--text); font: inherit; cursor: pointer; padding: 0; }
  .title button:hover { text-decoration: underline; }
  .meta { font-size: 12px; color: var(--muted); display:flex; gap:8px; flex-wrap: wrap; }
  .badge { border:1px solid var(--border); background: var(--panel); border-radius: 999px; padding: 2px 8px; }
  .row .btn { background: transparent; }
  .container.list .card { display:flex; flex-direction: row; align-items: stretch; }
  .container.list .media { width: 240px; min-width:240px; }
  .container.list .thumb { width: 100%; height: 100%; aspect-ratio: unset; object-fit: cover; }
  .container.list .content { flex: 1; }

  /* Accessibility helpers */
  .visually-hidden { position: absolute !important; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
  .input:focus, .select:focus, .btn:focus { outline: 2px solid color-mix(in oklab, var(--accent), transparent 40%); outline-offset: 2px; }

  /* Modal media player */
  .modal { position: fixed; inset: 0; display:none; align-items:center; justify-content:center; background: rgba(0,0,0,0.7); z-index: 50; }
  .modal.open { display:flex; }
  .modal-dialog { width: min(90vw, 1200px); background:var(--card); border:1px solid var(--border); border-radius:12px; overflow:hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
  .modal-header { display:flex; justify-content: space-between; align-items:center; padding:10px 12px; border-bottom:1px solid var(--border); }
  .modal-title { font-size:14px; font-weight:600; }
  .modal-close { background:transparent; border:0; color:var(--text); font-size:16px; cursor:pointer; }
  .modal-body { background:var(--bg); }
  video, audio { display:block; width:100%; height:auto; background:#000; }
  img.modal-image { display:block; max-width:100%; max-height:80vh; margin:0 auto; }

  /* Immersive mobile player */
  :root { --immersive-header-h: 48px; }
  body.immersive-open { overflow: hidden; }
  .immersive { position: fixed; inset: 0; z-index: 60; display: none; background: var(--bg); color: var(--text); }
  .immersive.open { display: block; }
  .immersive-header { position: fixed; top: 0; left: 0; right: 0; height: var(--immersive-header-h); display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: var(--nav); border-bottom: 1px solid var(--border); }
  .immersive-title { font-size: 14px; font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .immersive-close { background: transparent; border: 1px solid var(--border); border-radius: 8px; color: var(--text); padding: 6px 10px; cursor: pointer; }
  .immersive-media { position: relative; width: 100vw; margin-top: var(--immersive-header-h); background: #000; height: min(56vh, calc(100vw * 9 / 16)); }
  .immersive-media > video, .immersive-media > img { width: 100%; height: 100%; object-fit: contain; display: block; background: #000; }
  .immersive-info { position: absolute; top: calc(var(--immersive-header-h) + min(56vh, calc(100vw * 9 / 16))); bottom: 0; left: 0; right: 0; overflow: auto; padding: 12px; }
  .immersive .meta { margin-top: 6px; }
  .immersive .row { margin-top: 6px; }
  @media (orientation: landscape) {
    .immersive-media { height: 100vh; margin-top: 0; }
    .immersive-header { background: linear-gradient(to bottom, rgba(0,0,0,0.5), rgba(0,0,0,0)); color: #fff; border-bottom: none; }
    .immersive-close { border-color: rgba(255,255,255,0.35); color: #fff; background: rgba(0,0,0,0.35); }
    .immersive-info { display: none; }
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
  let items = data.items || [];
  let searchIndex = data.search_index || { subtitle_terms: {}, name_terms: {}, description_terms: {}, item_map: [] };
  let sortKey = 'date'; // alpha | size | date | type
  let sortDir = 'desc'; // asc | desc
  let viewMode = 'grid'; // grid | list

      function render(list) {
        container.innerHTML = '';
        container.classList.toggle('list', viewMode === 'list');
        for (const it of list) {
          const card = document.createElement('div');
          card.className = 'card';
          // Media with overlay and click-to-play/open
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
            // Placeholder for media without thumbnails
            img.src = 'data:image/svg+xml;base64,' + btoa('<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"320\" height=\"180\" viewBox=\"0 0 320 180\"><rect width=\"320\" height=\"180\" fill=\"#1f2937\"/><text x=\"160\" y=\"90\" text-anchor=\"middle\" fill=\"#9ca3af\" font-family=\"system-ui\" font-size=\"14\">' + it.media_type + '</text></svg>');
            img.alt = it.name || it.dir;
          }
          media.appendChild(img);
          const overlay = document.createElement('div');
          overlay.className = 'play';
          overlay.innerHTML = '<div class=\"play-icon\">' + getMediaIcon(it.media_type) + '</div>';
          media.appendChild(overlay);

          // Motion thumbnail preview on hover (no lift animation)
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
          if (it.subtitles && it.subtitles.length > 0) meta.appendChild(subtitleEl);
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

      function sortItems(list) {
        const arr = [...list];
        const dir = sortDir === 'asc' ? 1 : -1;
        arr.sort((a, b) => {
          if (sortKey === 'alpha') {
            const an = (a.name || a.dir || '').toLowerCase();
            const bn = (b.name || b.dir || '').toLowerCase();
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

    function searchInSubtitles(item, query) {
      if (!item.subtitles) return false;
      const q = query.toLowerCase();
      for (const subtitle of item.subtitles) {
        if (subtitle.text_combined && subtitle.text_combined.includes(q)) {
          return true;
        }
      }
      return false;
    }

    function apply() {
      const q = search.value.toLowerCase().trim();
      let filtered;

      if (!q) {
        // No search query, show all items
        filtered = items;
      } else {
        // Use search index for efficient filtering if available
        if (searchIndex.item_map && searchIndex.item_map.length > 0) {
          const matchingIndices = new Set();

          // Search in names
          for (const term in searchIndex.name_terms) {
            if (term.includes(q)) {
              searchIndex.name_terms[term].forEach(idx => matchingIndices.add(idx));
            }
          }

          // Search in descriptions
          for (const term in searchIndex.description_terms) {
            if (term.includes(q)) {
              searchIndex.description_terms[term].forEach(idx => matchingIndices.add(idx));
            }
          }

          // Search in subtitles
          for (const term in searchIndex.subtitle_terms) {
            if (term.includes(q)) {
              searchIndex.subtitle_terms[term].forEach(idx => matchingIndices.add(idx));
            }
          }

          filtered = Array.from(matchingIndices).map(idx => items[idx]).filter(Boolean);
        } else {
          // Fallback to direct search if no index available
          filtered = items.filter(it => {
            const name = (it.name || '').toLowerCase();
            const dir = (it.dir || '').toLowerCase();
            const videoId = extractVideoId(it.dir || '').toLowerCase();
            const type = (it.media_type || '').toLowerCase();
            const description = (it.description || '').toLowerCase();

            return name.includes(q) ||
                   dir.includes(q) ||
                   videoId.includes(q) ||
                   type.includes(q) ||
                   description.includes(q) ||
                   searchInSubtitles(it, q);
          });
        }
      }

      const sorted = sortItems(filtered);
      render(sorted);
    }

      // Initialize controls
      render(sortItems(items));
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

        const src = item.transcoded || item.primary_media;
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

        // Build metadata/details (portrait)
        const meta = document.createElement('div');
        meta.className = 'meta';
        const typeEl = document.createElement('span'); typeEl.className = 'badge'; typeEl.textContent = (item.media_type||'').replace(/^./, c=>c.toUpperCase());
        const dateEl = document.createElement('span'); dateEl.className = 'badge'; dateEl.textContent = fmtDate(item.created_time);
        const sizeEl = document.createElement('span'); sizeEl.className = 'badge'; sizeEl.textContent = fmtSize(item.size);
        const subtitleEl = document.createElement('span'); subtitleEl.className = 'badge'; subtitleEl.textContent = 'CC'; subtitleEl.title = 'Has subtitles';
        if (typeEl.textContent) meta.appendChild(typeEl);
        if (dateEl.textContent) meta.appendChild(dateEl);
        if (sizeEl.textContent) meta.appendChild(sizeEl);
        if (item.subtitles && item.subtitles.length > 0) meta.appendChild(subtitleEl);

        const links = document.createElement('div');
        links.className = 'row';
        if (item.analytics) { const a = document.createElement('a'); a.href = item.analytics; a.className='btn'; a.textContent='Analytics JSON'; links.appendChild(a); }
        if (item.metadata) { const a = document.createElement('a'); a.href = item.metadata; a.className='btn'; a.textContent='Metadata JSON'; links.appendChild(a); }

        const wrap = document.createElement('div');
        const heading = document.createElement('div'); heading.className='title'; heading.textContent = title || 'Media';
        wrap.appendChild(heading);
        wrap.appendChild(meta);
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
        if (isDesktop()) {
          modalTitle.textContent = title || 'Media';
          mediaEl.innerHTML = '';
          const src = item.transcoded || item.primary_media;
          if (type === 'video') {
            mediaEl.innerHTML = '<video controls preload=\"metadata\" style=\"width:100%; height:auto;\"></video>';
            const video = mediaEl.querySelector('video');
            video.setAttribute('src', src);
            video.play().catch(() => {});
          } else if (type === 'audio') {
            mediaEl.innerHTML = '<audio controls preload=\"metadata\" style=\"width:100%;\"></audio>';
            const audio = mediaEl.querySelector('audio');
            audio.setAttribute('src', src);
            audio.play().catch(() => {});
          }
          modal.classList.add('open');
        } else {
          openImmersive(item, title, type);
        }
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
        <div class="hint">Search includes video subtitles when available</div>
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
      </div>
      <div id="immersiveMedia" class="immersive-media"></div>
      <div id="immersiveInfo" class="immersive-info"></div>
    </div>
</body>
</html>"""
