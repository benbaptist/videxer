from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
import json
import os
from datetime import datetime


# Extended media extensions
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".wmv", ".flv", ".m4a"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}
ALL_MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS


def _find_media_files(dir_path: Path) -> List[str]:
    """Find all media files in a directory."""
    media_files = []
    for p in sorted(dir_path.iterdir()):
        if p.is_file() and p.suffix.lower() in ALL_MEDIA_EXTS:
            media_files.append(p.name)
    return media_files


def _find_video_file(dir_path: Path) -> Optional[str]:
    """Find the primary video file in a directory (for backwards compatibility)."""
    for p in sorted(dir_path.iterdir()):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS and p.name not in {"metadata.json", "analytics.json"}:
            return p.name
    return None


def _thumb_sort_key(name: str) -> int:
    """Sort key that extracts the numeric index from filenames like 'thumb_12.jpg'."""
    try:
        base = Path(name).stem  # thumb_12
        # Expect pattern thumb_<n>
        if "_" in base:
            return int(base.split("_")[-1])
    except Exception:
        pass
    return 0


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


def build_index(root: Path) -> Dict:
    """Build index data for all media directories."""
    items: List[Dict] = []

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue

        # Check for Vimeo-style metadata (backwards compatibility)
        metadata_path = entry / "metadata.json"
        analytics_path = entry / "analytics.json"
        thumbs = sorted([p.name for p in entry.glob("thumb_*.*") if p.is_file()], key=_thumb_sort_key)

        # Find all media files
        media_files = _find_media_files(entry)
        if not media_files:
            continue  # Skip directories with no media files

        # Primary video file (for backwards compatibility)
        video_file = _find_video_file(entry)

        # Extract metadata
        name: Optional[str] = None
        created_time: Optional[str] = None
        size: Optional[int] = None
        description: Optional[str] = None

        # Try Vimeo metadata first
        if metadata_path.exists():
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    md = json.load(f)
                    name = md.get("name")
                    created_time = md.get("created_time")
                    description = md.get("description")
            except Exception:
                pass

        # Fall back to file-based metadata if no Vimeo metadata
        if not name and media_files:
            primary_file = media_files[0]
            file_metadata = _extract_metadata_from_filename(primary_file)
            name = name or file_metadata["name"]
            created_time = created_time or file_metadata["created_time"]

        # Use directory name as fallback
        name = name or entry.name

        # Get file size from primary media file
        primary_media = media_files[0] if media_files else None
        if primary_media:
            try:
                size = (entry / primary_media).stat().st_size
            except Exception:
                size = None

        # Determine media type
        media_type = "unknown"
        if primary_media:
            ext = Path(primary_media).suffix.lower()
            if ext in VIDEO_EXTS:
                media_type = "video"
            elif ext in AUDIO_EXTS:
                media_type = "audio"
            elif ext in IMAGE_EXTS:
                media_type = "image"

        # Build item entry
        item = {
            "dir": entry.name,
            "name": name,
            "created_time": created_time,
            "size": size,
            "media_type": media_type,
            "media_files": media_files,
            "primary_media": primary_media,
            "description": description,
        }

        # Add Vimeo-specific fields if available
        if metadata_path.exists():
            item["metadata"] = f"{entry.name}/metadata.json"
        if analytics_path.exists():
            item["analytics"] = f"{entry.name}/analytics.json"

        # Add thumbnails
        if thumbs:
            item["thumbs"] = [f"{entry.name}/{t}" for t in thumbs]
            item["thumb_best"] = f"{entry.name}/{thumbs[-1]}"

        # Add video field for backwards compatibility
        if video_file:
            item["video"] = f"{entry.name}/{video_file}"

        items.append(item)

    return {"items": items}


def write_index_files(root: Path, html_path: Optional[Path] = None, json_path: Optional[Path] = None) -> None:
    """Generate index.html and index.json files."""
    root = Path(root)
    html_path = html_path or (root / "index.html")
    json_path = json_path or (root / "index.json")

    idx = build_index(root)

    # Write JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)

    # Write HTML (copy the template)
    html = _INDEX_HTML
    html_path.write_text(html, encoding="utf-8")


_INDEX_HTML = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Media Library Index</title>
  <style>
  :root { color-scheme: dark; --bg:#0b0c10; --panel:#0f172a; --card:#111827; --border:#1f2937; --muted:#9ca3af; --text:#e5e7eb; --accent:#60a5fa; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 0; background: linear-gradient(180deg, var(--bg) 0%, #0a0f1f 100%); color: var(--text); }
  header { padding: 14px 20px; background: rgba(17,24,39,0.85); position: sticky; top: 0; z-index: 2; border-bottom: 1px solid var(--border); backdrop-filter: blur(6px); }
  main { max-width: 1400px; margin: 0 auto; }
  h1 { margin: 0; font-size: 16px; font-weight: 700; letter-spacing: 0.2px; }
  .toolbar { display:flex; gap:10px; align-items:center; margin-top:10px; flex-wrap: wrap; }
  .input, .select, .btn { padding:9px 12px; font-size:12px; border:1px solid var(--border); border-radius:8px; background: var(--panel); color: var(--text); }
  .select { background: var(--panel); }
  .btn { cursor:pointer; user-select:none; text-decoration:none; transition: border-color .2s, background .2s; }
  .btn:hover { border-color:#334155; background:#0b1222; }
  .container { padding: 20px; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 18px; }
    .container.list { display:block; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; display: flex; flex-direction: column; transition: transform .18s ease, box-shadow .18s ease, border-color .2s; box-shadow: 0 2px 10px rgba(0,0,0,0.25); }
  .card:hover { transform: translateY(-2px); border-color:#334155; box-shadow: 0 10px 30px rgba(0,0,0,0.35); }
  .media { position: relative; display:block; padding:0; border:0; background:transparent; cursor:pointer; }
  .thumb { width: 100%; aspect-ratio: 16/9; object-fit: cover; background: #0f172a; display:block; }
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
  .row { display:flex; gap:8px; flex-wrap: wrap; }
  .row .btn { background: transparent; }
  .container.list .card { display:flex; flex-direction: row; align-items: stretch; }
  .container.list .media { width: 240px; min-width:240px; }
  .container.list .thumb { width: 100%; height: 100%; aspect-ratio: unset; object-fit: cover; }
  .container.list .content { flex: 1; }

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
          if (it.primary_media) {
            if (it.media_type === 'image') {
              media.addEventListener('click', () => openImageViewer(it.primary_media, it.name || it.dir));
            } else {
              media.addEventListener('click', () => openPlayer(it.primary_media, it.name || it.dir, it.media_type));
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
              tbtn.addEventListener('click', () => openPlayer(it.primary_media, it.name || it.dir, it.media_type));
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
          if (typeEl.textContent) meta.appendChild(typeEl);
          if (dateEl.textContent) meta.appendChild(dateEl);
          if (sizeEl.textContent) meta.appendChild(sizeEl);
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
      const match = dirName.match(/ - (\d+)$/);
      return match ? match[1] : '';
    }

    function apply() {
      const q = search.value.toLowerCase();
      const filtered = items.filter(it => {
        const name = (it.name || '').toLowerCase();
        const dir = (it.dir || '').toLowerCase();
        const videoId = extractVideoId(it.dir || '').toLowerCase();
        const type = (it.media_type || '').toLowerCase();
        return name.includes(q) || dir.includes(q) || videoId.includes(q) || type.includes(q);
      });
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

      window.openPlayer = (src, title, type) => {
        modalTitle.textContent = title || 'Media';
        // Clear previous content
        mediaEl.innerHTML = '';
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
      };

      window.openImageViewer = (src, title) => {
        modalTitle.textContent = title || 'Image';
        mediaEl.innerHTML = '<img class=\"modal-image\" alt=\"' + (title || 'Image') + '\">';
        const img = mediaEl.querySelector('img');
        img.setAttribute('src', src);
        modal.classList.add('open');
      };
    }

    window.addEventListener('DOMContentLoaded', load);
  </script>
</head>
<body>
  <header>
    <h1>Media Library Index</h1>
    <div class="toolbar">
      <input id="search" class="input" placeholder="Search media..." />
      <select id="sort" class="select">
        <option value="date" selected>Date</option>
        <option value="alpha">Alphabetical</option>
        <option value="size">Size</option>
        <option value="type">Type</option>
      </select>
      <button id="direction" class="btn">Descending</button>
      <button id="view" class="btn">Grid</button>
    </div>
  </header>
  <div class="container"></div>

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
</body>
</html>"""
