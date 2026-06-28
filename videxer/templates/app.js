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

    // ---------------------------------------------------------------------------
    // Image format support detection (cached async probe)
    // ---------------------------------------------------------------------------
    const _fmtSupport = { detected: false, avif: false, webp: false };

    async function detectImageFormats() {
      if (_fmtSupport.detected) return;
      const probes = {
        avif: 'data:image/avif;base64,AAAAIGZ0eXBhdmlmAAAAAGF2aWZtaWYxbWlhZk1BMUIAAADybWV0YQAAAAAAAAAoaGRscgAAAAAAAAAAcGljdAAAAAAAAAAAAAAAAGxpYmF2aWYAAAAADnBpdG0AAAAAAAEAAAAeaWxvYwAAAABEAAABAAEAAAABAAABGgAAABcAAAAoaWluZgAAAAAAAQAAABppbmZlAgAAAAABAABhdjAxQ29sb3IAAAAAamlwcnAAAABLaXBjbwAAABRpc3BlAAAAAAAAAAEAAAABAAAAEHBpeGkAAAAAAwgICAAAAAxhdjFDgQAMAAAAABNjb2xybmNseAACAAIAAYAAAAAXaXBtYQAAAAAAAAABAAEEAQKDBAAAACVtZGF0EgAKCBgABogQEDQgMgkQAAAAB8dSLfI=',
        webp: 'data:image/webp;base64,UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoBAAEAAwA0JZACdAEO/gHOAAA=',
      };
      await Promise.all(Object.entries(probes).map(([fmt, src]) =>
        new Promise(resolve => {
          const img = new Image();
          img.onload = () => { _fmtSupport[fmt] = img.width > 0; resolve(); };
          img.onerror = () => resolve();
          img.src = src;
        })
      ));
      _fmtSupport.detected = true;
    }

    // Map UI thumb-size keys to index level names
    const THUMB_LEVEL_MAP = { s: 'small', m: 'medium', l: 'large', xl: 'large' };

    /**
     * Pick the best URL from a thumbs object for the given UI size key.
     * Handles both the new structured dict and legacy array/string formats.
     */
    function pickThumbUrl(thumbs, sizeKey) {
      if (!thumbs) return '';
      // Legacy: plain string
      if (typeof thumbs === 'string') return thumbs;
      // Legacy: array
      if (Array.isArray(thumbs)) return thumbs[thumbs.length - 1] || '';

      // New structured format
      const levelName = THUMB_LEVEL_MAP[sizeKey] || 'medium';
      const level = thumbs[levelName] || thumbs.medium || thumbs.small || thumbs.original;
      if (!level) return '';
      if (typeof level === 'string') return level;

      // Choose best format the browser supports
      if (_fmtSupport.avif && level.avif) return level.avif;
      if (_fmtSupport.webp && level.webp) return level.webp;
      return level.jpg || Object.values(level)[0] || '';
    }

    /**
     * Create an <img> element with LQIP progressive loading.
     * Shows placeholder (blurred) immediately, swaps to full quality once loaded.
     */
    function createProgressiveImg(thumbs, alt, currentSize) {
      const img = document.createElement('img');
      img.className = 'thumb';
      img.loading = 'lazy';
      img.alt = alt;

      const placeholder = thumbs && !Array.isArray(thumbs) && typeof thumbs === 'object'
        ? thumbs.placeholder : null;
      const fullSrc = pickThumbUrl(thumbs, currentSize);

      if (placeholder && fullSrc && fullSrc !== placeholder) {
        img.src = placeholder;
        img.classList.add('thumb-loading');
        const full = new Image();
        full.onload = () => {
          img.src = full.src;
          img.classList.remove('thumb-loading');
        };
        full.src = fullSrc;
      } else if (fullSrc) {
        img.src = fullSrc;
      }

      return img;
    }

    function getMediaIcon(type) {
      switch(type) {
        case 'video': return '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M8 5v14l11-7z" fill="#fff"></path></svg>';
        case 'audio': return '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z" fill="#fff"></path></svg>';
        case 'image': return '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z" fill="#fff"></path></svg>';
        default: return '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z" fill="#fff"></path></svg>';
      }
    }

    async function load() {
      // Probe format support before rendering anything
      await detectImageFormats();

      const data = await fetchJSON('index.json');
      const container = document.querySelector('.container');
      const search = document.getElementById('search');
      const sortSel = document.getElementById('sort');
      const dirBtn = document.getElementById('direction');
      const viewBtn = document.getElementById('view');
      const breadcrumbEl = document.getElementById('breadcrumb');

      // Apply branding
      const branding = data.branding || {};
      const libraryName = branding.name || 'Media Library';
      document.title = libraryName;
      document.querySelector('.brand-title').textContent = libraryName;
      if (branding.favicon) {
        document.getElementById('favicon').href = branding.favicon;
      }

      let allItems = data.items || [];
      let currentPath = []; // Stack of directory names
      let currentItems = allItems; // Items in current view
      let searchIndex = data.search_index || { subtitle_terms: {}, name_terms: {}, description_terms: {}, item_map: [] };
      let subtitlesLoading = false; // Track if we're already loading subtitles
      let sortKey = 'date'; // alpha | size | date | type
      let sortDir = 'desc'; // asc | desc
      let viewMode = 'grid'; // grid | list
      let thumbSize = 'm'; // s | m | l | xl
      const THUMB_SIZES = { s: 160, m: 260, l: 360, xl: 480 };

      // Image viewer state
      let imageList = [];
      let currentImageIndex = -1;
      let controlsHideTimer = null;

      // Preferences stored per-path in localStorage
      const prefKey = 'videxer:prefs:' + window.location.pathname;

      function loadPrefs() {
        try {
          const saved = JSON.parse(localStorage.getItem(prefKey) || '{}');
          if (saved.sortKey) sortKey = saved.sortKey;
          if (saved.sortDir) sortDir = saved.sortDir;
          if (saved.viewMode) viewMode = saved.viewMode;
          if (saved.thumbSize && THUMB_SIZES[saved.thumbSize]) thumbSize = saved.thumbSize;
        } catch {}
      }

      function savePrefs() {
        try {
          localStorage.setItem(prefKey, JSON.stringify({ sortKey, sortDir, viewMode, thumbSize }));
        } catch {}
      }

      function applyThumbSize() {
        document.documentElement.style.setProperty('--thumb-col-min', THUMB_SIZES[thumbSize] + 'px');
        document.querySelectorAll('.size-btn').forEach(btn => {
          btn.classList.toggle('active', btn.dataset.size === thumbSize);
        });
        container.dataset.size = thumbSize;
      }

      function updateBreadcrumb() {
        breadcrumbEl.innerHTML = '';
        
        // Root/home button
        const homeBtn = document.createElement('button');
        homeBtn.className = 'breadcrumb-item btn';
        homeBtn.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" style="vertical-align:-2px;margin-right:5px" fill="currentColor"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>Library';
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
        window.location.hash = '';
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
        updateHash();
        apply();
      }
      
      function navigateInto(dirName) {
        const dir = currentItems.find(item => item.type === 'directory' && item.name === dirName);
        if (dir && dir.children) {
          currentPath.push(dirName);
          currentItems = dir.children;
          search.value = '';
          updateHash();
          apply();
        }
      }
      
      function updateHash() {
        // Update URL hash with current path
        if (currentPath.length === 0) {
          window.location.hash = '';
        } else {
          window.location.hash = '#' + currentPath.map(encodeURIComponent).join('/');
        }
      }
      
      function navigateToPath(pathStr) {
        // Navigate to a specific path from hash
        if (!pathStr) {
          navigateToRoot();
          return;
        }
        
        const segments = pathStr.split('/').filter(s => s.length > 0).map(decodeURIComponent);
        currentPath = [];
        currentItems = allItems;
        
        for (const segment of segments) {
          const dir = currentItems.find(item => item.type === 'directory' && item.name === segment);
          if (dir && dir.children) {
            currentPath.push(segment);
            currentItems = dir.children;
          } else {
            // Path not found, stop here
            break;
          }
        }
        
        search.value = '';
        apply();
      }
      
      function findMediaByPath(pathStr) {
        // Find a media item by its full path
        const flatItems = flattenAllItems(allItems);
        return flatItems.find(item => item.path === pathStr);
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
            const motionThumbSrc = it.motion_thumb;
            const hasThumbs = !!it.thumbs;
            const img = hasThumbs
              ? createProgressiveImg(it.thumbs, it.name || it.dir, thumbSize)
              : (() => {
                  const el = document.createElement('img');
                  el.className = 'thumb';
                  el.loading = 'lazy';
                  el.alt = it.name || it.dir;
                  el.src = 'data:image/svg+xml;base64,' + btoa('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180"><rect width="320" height="180" fill="#1f2937"/><text x="160" y="90" text-anchor="middle" fill="#9ca3af" font-family="system-ui" font-size="14">' + it.media_type + '</text></svg>');
                  return el;
                })();
            media.appendChild(img);
            if (it.media_type !== 'image') {
              const overlay = document.createElement('div');
              overlay.className = 'play';
              overlay.innerHTML = '<div class="play-icon">' + getMediaIcon(it.media_type) + '</div>';
              media.appendChild(overlay);
            }

            if (motionThumbSrc && hasThumbs) {
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
                media.addEventListener('click', () => openImageViewer(it));
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
                tbtn.addEventListener('click', () => openImageViewer(it));
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
            if (it.description && viewMode === 'list') {
              const descEl = document.createElement('div');
              descEl.className = 'description';
              descEl.textContent = it.description;
              content.appendChild(descEl);
            }
            if (row.children.length) content.appendChild(row);
            card.appendChild(content);
            container.appendChild(card);
          }
        }

        // Track image-only items for prev/next navigation
        imageList = list.filter(it => it.type !== 'directory' && it.media_type === 'image' && it.primary_media);
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
        const match = dirName.match(/ - (\d+)$/);
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
          
          // If subtitle index isn't loaded, fetch it in the background (only once)
          if (!searchIndex.subtitle_terms) searchIndex.subtitle_terms = {};
          if (Object.keys(searchIndex.subtitle_terms).length === 0 && !subtitlesLoading) {
            subtitlesLoading = true;
            fetchJSON('index.subtitles.json')
              .then(subs => {
                searchIndex.subtitle_terms = subs.subtitle_terms || {};
                apply();
              })
              .catch(() => {
                // If subtitle index doesn't exist or fails to load, that's okay
                subtitlesLoading = false;
              });
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
      loadPrefs();
      sortSel.value = sortKey;
      dirBtn.textContent = sortDir === 'asc' ? 'Ascending' : 'Descending';
      viewBtn.textContent = viewMode === 'grid' ? 'Grid' : 'List';
      applyThumbSize();
      apply();
      search.addEventListener('input', () => {
        apply();
      });
      sortSel.addEventListener('change', () => { sortKey = sortSel.value; savePrefs(); apply(); });
      dirBtn.addEventListener('click', () => {
        sortDir = (sortDir === 'asc') ? 'desc' : 'asc';
        dirBtn.textContent = (sortDir === 'asc') ? 'Ascending' : 'Descending';
        savePrefs();
        apply();
      });
      viewBtn.addEventListener('click', () => {
        viewMode = (viewMode === 'grid') ? 'list' : 'grid';
        viewBtn.textContent = viewMode === 'grid' ? 'Grid' : 'List';
        savePrefs();
        apply();
      });
      document.querySelectorAll('.size-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          thumbSize = btn.dataset.size;
          applyThumbSize();
          savePrefs();
        });
      });

      // Modal wiring
      const modal = document.getElementById('playerModal');
      const modalTitle = document.getElementById('playerTitle');
      const mediaEl = document.getElementById('playerMedia');
      const closeBtn = document.getElementById('playerClose');
      const imgPrev = document.getElementById('imgPrev');
      const imgNext = document.getElementById('imgNext');

      function close() {
        modal.classList.remove('open', 'img-mode', 'show-controls');
        clearTimeout(controlsHideTimer);
        // Stop playback and release resource
        if (mediaEl.tagName === 'VIDEO' || mediaEl.tagName === 'AUDIO') {
          mediaEl.pause();
          mediaEl.removeAttribute('src');
          mediaEl.load();
        }
        
        // Restore hash to current directory
        suppressHashChange = true;
        updateHash();
        setTimeout(() => { suppressHashChange = false; }, 10);
      }

      function updateNavButtons() {
        imgPrev.disabled = currentImageIndex <= 0;
        imgNext.disabled = currentImageIndex >= imageList.length - 1;
      }

      function showControlsTemporarily() {
        modal.classList.add('show-controls');
        clearTimeout(controlsHideTimer);
        controlsHideTimer = setTimeout(() => modal.classList.remove('show-controls'), 3000);
      }

      function navigateImage(delta) {
        const newIndex = currentImageIndex + delta;
        if (newIndex < 0 || newIndex >= imageList.length) return;
        currentImageIndex = newIndex;
        const item = imageList[currentImageIndex];
        if (item.path) {
          suppressHashChange = true;
          window.location.hash = '#' + item.path;
          setTimeout(() => { suppressHashChange = false; }, 10);
        }
        modalTitle.textContent = item.name || item.dir || 'Image';
        const img = mediaEl.querySelector('img.modal-image');
        if (img) { img.alt = modalTitle.textContent; img.src = item.primary_media; }
        updateNavButtons();
        // Keep controls visible on touch after navigation
        if (window.matchMedia('(pointer: coarse)').matches) showControlsTemporarily();
      }

      imgPrev.addEventListener('click', (e) => { e.stopPropagation(); navigateImage(-1); });
      imgNext.addEventListener('click', (e) => { e.stopPropagation(); navigateImage(1); });

      // Toggle controls on tap (touch devices) — tap anywhere in modal-dialog that isn't a button
      modal.querySelector('.modal-dialog').addEventListener('click', (e) => {
        if (!modal.classList.contains('img-mode')) return;
        if (e.target.closest('.img-nav') || e.target.closest('.modal-header')) return;
        if (!window.matchMedia('(pointer: coarse)').matches) return;
        if (modal.classList.contains('show-controls')) {
          modal.classList.remove('show-controls');
          clearTimeout(controlsHideTimer);
        } else {
          showControlsTemporarily();
        }
      });

      closeBtn.addEventListener('click', close);
      modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
      window.addEventListener('keydown', (e) => { 
        if (e.key === 'Escape') {
          if (immersive.classList.contains('open')) {
            closeImmersive();
          } else if (modal.classList.contains('open')) {
            close();
          }
        }
        if (modal.classList.contains('img-mode') && modal.classList.contains('open')) {
          if (e.key === 'ArrowLeft') navigateImage(-1);
          if (e.key === 'ArrowRight') navigateImage(1);
        }
      });

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

      function openImmersive(item, title, type) {
        document.body.classList.add('immersive-open');
        immTitle.textContent = title || 'Media';
        immMedia.innerHTML = '';
        immInfo.innerHTML = '';
        immMedia.classList.toggle('audio-mode', type === 'audio');
        const hasOptimized = !!item.transcoded;
        const hasOriginal = !!item.primary_media;
        let currentQuality = hasOptimized ? 'optimized' : 'original';
        const pickSrc = () => (currentQuality === 'optimized' ? item.transcoded : item.primary_media) || item.primary_media || item.transcoded;
        const src = pickSrc();
        if (type === 'video') {
          const video = document.createElement('video');
          video.setAttribute('controls', '');
          video.setAttribute('preload', 'metadata');
          video.setAttribute('autoplay', '');
          video.src = src;
          immMedia.appendChild(video);
          // Enable loop for videos shorter than 1 minute
          video.addEventListener('loadedmetadata', () => {
            if (video.duration && video.duration < 60) {
              video.setAttribute('loop', '');
            }
          });
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
  if (item.subtitles && item.subtitles.length > 0) meta.appendChild(subtitleEl);

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
          downloadBtn.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" style="vertical-align:-2px;margin-right:5px" fill="currentColor"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>Download Original';
          downloadBtn.title = 'Download the original file';
          wrap.appendChild(downloadBtn);
        }
        
        if (links.children.length) wrap.appendChild(links);
        immInfo.appendChild(wrap);

        // Load and render transcript if subtitles are available (check for existing transcript to prevent duplicates)
        if (item.subtitles && item.subtitles.length > 0 && !immInfo.querySelector('.transcript-panel')) {
          console.log('Loading transcript for:', item);
          loadTranscript(item, immInfo, type);
        } else if (item.subtitles && immInfo.querySelector('.transcript-panel')) {
          console.log('Transcript already loaded for:', item.path);
        } else {
          console.log('No subtitles available for this item:', item);
        }

        immersive.classList.add('open');
      }

      async function loadTranscript(item, container, mediaType) {
        console.log('loadTranscript called with item:', item);
        try {
          // Get subtitle file from item
          if (!item.subtitles || item.subtitles.length === 0) {
            console.log('No subtitle files found for this item');
            return;
          }

          // For now, use the first subtitle track (could be extended to support multiple languages)
          const subtitleInfo = item.subtitles[0];
          const subtitlePath = subtitleInfo.file;
          
          console.log('Fetching subtitle file:', subtitlePath);
          
          // Fetch and parse the SRT file
          const subtitleEntries = await parseSRTFile(subtitlePath);
          
          if (!subtitleEntries || subtitleEntries.length === 0) {
            console.log('No subtitle entries found in file:', subtitlePath);
            return;
          }

          // Create transcript panel
          const panel = document.createElement('div');
          panel.className = 'transcript-panel';
          
          // Header
          const header = document.createElement('div');
          header.className = 'transcript-header';
          
          const titleDiv = document.createElement('div');
          titleDiv.className = 'transcript-title';
          titleDiv.textContent = 'Transcript (' + subtitleEntries.length + ')';
          
          header.appendChild(titleDiv);
          
          // Search box
          const searchBox = document.createElement('div');
          searchBox.className = 'transcript-search';
          const searchInput = document.createElement('input');
          searchInput.type = 'text';
          searchInput.placeholder = 'Filter...';
          searchBox.appendChild(searchInput);
          
          // Body with segments
          const body = document.createElement('div');
          body.className = 'transcript-body';
          
          const segments = document.createElement('div');
          segments.className = 'transcript-segments';
          
          // Render segments
          subtitleEntries.forEach((entry, index) => {
            const segmentDiv = document.createElement('div');
            segmentDiv.className = 'transcript-segment';
            segmentDiv.dataset.index = index;
            segmentDiv.dataset.text = entry.text.toLowerCase();
            
            const timestampDiv = document.createElement('div');
            timestampDiv.className = 'transcript-timestamp';
            timestampDiv.textContent = formatTranscriptTime(entry.start);
            
            const textDiv = document.createElement('div');
            textDiv.className = 'transcript-text';
            textDiv.textContent = entry.text;
            
            segmentDiv.appendChild(timestampDiv);
            segmentDiv.appendChild(textDiv);
            
            // Click to jump to timestamp
            segmentDiv.addEventListener('click', () => {
              const mediaElement = immMedia.querySelector('video, audio');
              if (mediaElement && entry.start) {
                const seconds = parseSubtitleTimestamp(entry.start);
                mediaElement.currentTime = seconds;
                mediaElement.play().catch(() => {});
                
                // Highlight active segment
                segments.querySelectorAll('.transcript-segment').forEach(s => s.classList.remove('active'));
                segmentDiv.classList.add('active');
              }
            });
            
            segments.appendChild(segmentDiv);
          });
          
          body.appendChild(segments);
          
          // Assemble panel
          panel.appendChild(header);
          panel.appendChild(searchBox);
          panel.appendChild(body);
          
          container.appendChild(panel);
          
          // Search functionality
          searchInput.addEventListener('input', () => {
            const query = searchInput.value.toLowerCase().trim();
            
            segments.querySelectorAll('.transcript-segment').forEach(segment => {
              const text = segment.dataset.text;
              
              if (!query || text.includes(query)) {
                segment.classList.remove('hidden');
                
                // Highlight matching text
                if (query) {
                  const textDiv = segment.querySelector('.transcript-text');
                  const originalText = subtitleEntries[segment.dataset.index].text;
                  const regex = new RegExp('(' + escapeRegex(query) + ')', 'gi');
                  textDiv.innerHTML = originalText.replace(regex, '<mark>$1</mark>');
                } else {
                  const textDiv = segment.querySelector('.transcript-text');
                  textDiv.textContent = subtitleEntries[segment.dataset.index].text;
                }
              } else {
                segment.classList.add('hidden');
              }
            });
          });
          
          // Auto-scroll and highlight transcript during playback
          const mediaElement = immMedia.querySelector('video, audio');
          if (mediaElement) {
            mediaElement.addEventListener('timeupdate', () => {
              const currentTime = mediaElement.currentTime;
              
              // Find the active segment based on current playback time
              let activeSegment = null;
              for (let i = 0; i < subtitleEntries.length; i++) {
                const entry = subtitleEntries[i];
                const startTime = parseSubtitleTimestamp(entry.start);
                const endTime = parseSubtitleTimestamp(entry.end);
                
                if (currentTime >= startTime && currentTime <= endTime) {
                  activeSegment = segments.children[i];
                  break;
                }
              }
              
              // Update active class
              segments.querySelectorAll('.transcript-segment').forEach(s => s.classList.remove('active'));
              
              if (activeSegment && !activeSegment.classList.contains('hidden')) {
                activeSegment.classList.add('active');
                
                // Auto-scroll to keep active segment visible
                const bodyRect = body.getBoundingClientRect();
                const segmentRect = activeSegment.getBoundingClientRect();
                
                // Check if segment is out of view
                if (segmentRect.top < bodyRect.top || segmentRect.bottom > bodyRect.bottom) {
                  activeSegment.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
              }
            });
          }
          
        } catch (error) {
          console.warn('Failed to load transcript:', error);
        }
      }

      function formatTranscriptTime(timestamp) {
        // Convert timestamp from SRT format (00:00:01,000) or VTT format (00:00:01.000) to display format (0:01)
        if (!timestamp) return '';
        
        // Handle both comma and period as decimal separator
        const normalized = timestamp.replace(',', '.');
        const parts = normalized.split(':');
        
        if (parts.length === 3) {
          const hours = parseInt(parts[0], 10);
          const minutes = parseInt(parts[1], 10);
          const seconds = parseInt(parts[2].split('.')[0], 10);
          
          if (hours > 0) {
            return hours + ':' + minutes.toString().padStart(2, '0') + ':' + seconds.toString().padStart(2, '0');
          } else {
            return minutes + ':' + seconds.toString().padStart(2, '0');
          }
        }
        
        return timestamp;
      }

      function parseSubtitleTimestamp(timestamp) {
        // Convert SRT/VTT timestamp to seconds
        if (!timestamp) return 0;
        
        // Handle both comma and period as decimal separator
        const normalized = timestamp.replace(',', '.');
        const parts = normalized.split(':');
        
        if (parts.length === 3) {
          const hours = parseInt(parts[0], 10);
          const minutes = parseInt(parts[1], 10);
          const secondsParts = parts[2].split('.');
          const seconds = parseInt(secondsParts[0], 10);
          const milliseconds = secondsParts[1] ? parseInt(secondsParts[1], 10) / 1000 : 0;
          
          return hours * 3600 + minutes * 60 + seconds + milliseconds;
        }
        
        return 0;
      }

      async function parseSRTFile(srtPath) {
        // Fetch and parse an SRT file
        try {
          const response = await fetch(srtPath);
          if (!response.ok) {
            console.error('Failed to fetch SRT file:', srtPath);
            return null;
          }
          
          const content = await response.text();
          const subtitles = [];
          
          // Split into blocks (entries separated by blank lines)
          const blocks = content.trim().split(/\n\s*\n/);
          
          for (const block of blocks) {
            const lines = block.trim().split('\n');
            if (lines.length < 3) continue; // Need at least: number, timestamp, text
            
            // First line is the sequence number (skip it)
            // Second line is the timestamp
            const timestampLine = lines[1];
            const timestampMatch = timestampLine.match(/(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})/);
            
            if (!timestampMatch) continue;
            
            const startTime = timestampMatch[1];
            const endTime = timestampMatch[2];
            
            // Rest of the lines are the subtitle text
            const text = lines.slice(2).join(' ').trim();
            
            if (text) {
              subtitles.push({
                start: startTime,
                end: endTime,
                text: text
              });
            }
          }
          
          return subtitles;
        } catch (error) {
          console.error('Error parsing SRT file:', error);
          return null;
        }
      }

      function escapeRegex(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      }

      function closeImmersive() {
        document.body.classList.remove('immersive-open');
        immMedia.classList.remove('audio-mode');
        // Stop playback and release resource
        const media = immMedia.querySelector('video, audio');
        if (media) { try { media.pause(); } catch(e){} media.removeAttribute('src'); media.load && media.load(); }
        immersive.classList.remove('open');
        
        // Restore hash to current directory
        suppressHashChange = true;
        updateHash();
        setTimeout(() => { suppressHashChange = false; }, 10);
      }
      immClose.addEventListener('click', closeImmersive);

      // Track if we're programmatically changing the hash to avoid double-opening
      let suppressHashChange = false;

      window.openPlayer = (item, title, type) => {
        // Update hash with media path
        if (item.path) {
          suppressHashChange = true;
          window.location.hash = '#' + item.path;
          // Reset flag after a small delay to allow hashchange to fire and be ignored
          setTimeout(() => { suppressHashChange = false; }, 10);
        }
        // Always use immersive view for consistent UI and quality control
        openImmersive(item, title, type);
      };

      window.openImageViewer = (item) => {
        const src = item.primary_media;
        const title = item.name || item.dir || 'Image';

        // Find index in current image list
        currentImageIndex = imageList.findIndex(it => it.primary_media === src);

        if (item.path) {
          suppressHashChange = true;
          window.location.hash = '#' + item.path;
          setTimeout(() => { suppressHashChange = false; }, 10);
        }

        modalTitle.textContent = title;

        const altText = title.replace(/"/g, '&quot;');
        const placeholder = item.thumbs && !Array.isArray(item.thumbs) && typeof item.thumbs === 'object'
          ? item.thumbs.placeholder : null;

        const img = document.createElement('img');
        img.className = 'modal-image';
        img.alt = altText;

        if (placeholder && src !== placeholder) {
          img.src = placeholder;
          img.classList.add('modal-img-loading');
          const full = new Image();
          full.onload = () => {
            img.src = full.src;
            img.classList.remove('modal-img-loading');
          };
          full.src = src;
        } else {
          img.src = src;
        }

        mediaEl.innerHTML = '';
        mediaEl.appendChild(img);
        modal.classList.add('open', 'img-mode');
        updateNavButtons();

        // Show controls initially on touch devices
        if (window.matchMedia('(pointer: coarse)').matches) showControlsTemporarily();
      };
      
      // Handle hash changes (browser back/forward)
      window.addEventListener('hashchange', () => {
        // Ignore hash changes that we triggered ourselves
        if (suppressHashChange) {
          return;
        }
        
        const hash = decodeURIComponent(window.location.hash.substring(1)); // Remove the '#' and decode
        
        // Check if it's a media file path
        const mediaItem = findMediaByPath(hash);
        if (mediaItem) {
          if (mediaItem.media_type === 'image') {
            openImageViewer(mediaItem);
          } else {
            openPlayer(mediaItem, mediaItem.name || mediaItem.dir, mediaItem.media_type);
          }
        } else {
          // It's a directory path
          navigateToPath(hash);
        }
      });
      
      // On initial load, check if there's a hash and navigate to it
      const initialHash = decodeURIComponent(window.location.hash.substring(1));
      if (initialHash) {
        const mediaItem = findMediaByPath(initialHash);
        if (mediaItem) {
          if (mediaItem.media_type === 'image') {
            openImageViewer(mediaItem);
          } else {
            openPlayer(mediaItem, mediaItem.name || mediaItem.dir, mediaItem.media_type);
          }
        } else {
          // It's a directory, navigate to it
          navigateToPath(initialHash);
        }
      }
    }

    window.addEventListener('DOMContentLoaded', load);