'use strict';

const API      = '/api';
const PER_PAGE = 12;

// ── Utilities ─────────────────────────────────────────────────────────────────

function formatDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric', month: 'long', day: 'numeric',
    timeZone: 'UTC',
  });
}

function escHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ════════════════════════════════════════
// BLOG LISTING
// ════════════════════════════════════════

const listingEl = document.getElementById('post-grid');

if (listingEl) {
  let currentPage     = 1;
  let activeCategory  = null;
  let searchQuery     = '';
  let searchTimer     = null;

  const prevBtn       = document.getElementById('prev-btn');
  const nextBtn       = document.getElementById('next-btn');
  const pageInfo      = document.getElementById('page-info');
  const pagination    = document.getElementById('pagination');
  const searchInput   = document.getElementById('search-input');
  const categoryPills = document.getElementById('category-pills');

  // ── Skeleton ──────────────────────────────────────────────────
  function skeletonCard() {
    return `
      <div class="post-card post-card--skeleton" aria-hidden="true">
        <div class="skel" style="width:60px;height:10px"></div>
        <div class="skel" style="width:85%;height:18px;margin-top:4px"></div>
        <div class="skel" style="width:70%;height:16px"></div>
        <div class="skel" style="width:100%;height:12px;margin-top:6px"></div>
        <div class="skel" style="width:95%;height:12px"></div>
        <div class="skel" style="width:80%;height:12px"></div>
      </div>`;
  }

  // ── Post card ─────────────────────────────────────────────────
  function postCard(post) {
    const date    = formatDate(post.published_at);
    const excerpt = post.excerpt || '';
    const href    = `/blog/${post.slug}`;
    const img     = post.image_url
      ? `<div class="post-card__img-wrap"><img class="post-card__img" src="${escHtml(post.image_url)}" alt="" loading="lazy" decoding="async" width="400" height="160"></div>`
      : '';
    return `
      <a class="post-card${post.image_url ? ' post-card--has-img' : ''}" href="${href}">
        ${img}
        <span class="post-card__date">${escHtml(date)}</span>
        <span class="post-card__title">${escHtml(post.title)}</span>
        ${excerpt ? `<span class="post-card__excerpt">${escHtml(excerpt)}</span>` : ''}
        <span class="post-card__cta">Read more →</span>
      </a>`;
  }

  // ── URL state helpers ─────────────────────────────────────────
  function getUrlState() {
    const p    = new URLSearchParams(location.search);
    const path = location.pathname;
    // /page/3  or  /category/aws/page/3
    const pageMatch = path.match(/\/page\/(\d+)\/?$/);
    // /category/aws  or  /category/aws/page/3
    const catMatch  = path.match(/^\/category\/([^/]+)/);
    return {
      page:     pageMatch ? parseInt(pageMatch[1], 10) : (parseInt(p.get('page'), 10) || 1),
      category: catMatch  ? catMatch[1]                : (p.get('category') || null),
      q:        p.get('q') || '',
    };
  }

  function pushUrlState(page, category, q) {
    if (q) {
      // Search results: keep as query param (ephemeral, not meant to be bookmarked)
      const p = new URLSearchParams({ q });
      if (page > 1) p.set('page', page);
      history.replaceState(null, '', `/?${p}`);
      return;
    }
    let path;
    if (category && page > 1) {
      path = `/category/${category}/page/${page}`;
    } else if (category) {
      path = `/category/${category}`;
    } else if (page > 1) {
      path = `/page/${page}`;
    } else {
      path = '/';
    }
    history.replaceState(null, '', path);
  }

  // ── Pagination helper ─────────────────────────────────────────
  function updatePagination(data) {
    if (data.pages > 1) {
      pagination.hidden = false;
      pageInfo.textContent = `${data.page} of ${data.pages}`;
      prevBtn.disabled = data.page <= 1;
      nextBtn.disabled = data.page >= data.pages;
    } else {
      pagination.hidden = true;
    }
    currentPage = data.page;
  }

  // ── Load (paginated, category-filtered) ──────────────────────
  async function loadPosts(page) {
    listingEl.innerHTML = Array(PER_PAGE).fill(0).map(skeletonCard).join('');

    let url = `${API}/posts?page=${page}&per_page=${PER_PAGE}`;
    if (activeCategory) url += `&category=${encodeURIComponent(activeCategory)}`;

    try {
      const res  = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      listingEl.innerHTML = '';
      if (!data.posts.length) {
        listingEl.innerHTML = '<p class="blog-empty">No posts found.</p>';
        pagination.hidden = true;
        return;
      }
      data.posts.forEach(p => listingEl.insertAdjacentHTML('beforeend', postCard(p)));
      updatePagination(data);
      pushUrlState(data.page, activeCategory, '');
      sessionStorage.setItem('blogListingPage', data.page);
    } catch (err) {
      listingEl.innerHTML = `<p class="blog-empty">Failed to load posts. Please try again.</p>`;
      console.error('loadPosts error:', err);
    }
  }

  // ── Search ────────────────────────────────────────────────────
  async function runSearch(q, page) {
    listingEl.innerHTML = Array(PER_PAGE).fill(0).map(skeletonCard).join('');
    pagination.hidden = true;

    try {
      const res  = await fetch(`${API}/search?q=${encodeURIComponent(q)}&page=${page}&per_page=${PER_PAGE}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      listingEl.innerHTML = '';
      if (!data.posts.length) {
        listingEl.innerHTML = `<p class="blog-empty">No results for <strong>${escHtml(q)}</strong>.</p>`;
        pushUrlState(1, null, q);
        return;
      }
      data.posts.forEach(p => listingEl.insertAdjacentHTML('beforeend', postCard(p)));
      updatePagination(data);
      pushUrlState(data.page, null, q);
    } catch (err) {
      listingEl.innerHTML = `<p class="blog-empty">Search failed. Please try again.</p>`;
      console.error('runSearch error:', err);
    }
  }

  // ── Dispatch: search takes priority over category filter ──────
  function refresh(page) {
    if (searchQuery.length >= 2) {
      runSearch(searchQuery, page);
    } else {
      loadPosts(page);
    }
  }

  // ── Category pills ────────────────────────────────────────────
  async function loadCategories() {
    try {
      const res  = await fetch(`${API}/categories`);
      if (!res.ok) return;
      const cats = await res.json();
      if (!cats.length) return;

      // "All" pill
      const allPill = document.createElement('button');
      allPill.className = 'cat-pill cat-pill--active';
      allPill.textContent = 'All';
      allPill.dataset.slug = '';
      allPill.addEventListener('click', () => setCategory(null, allPill));
      categoryPills.appendChild(allPill);

      cats.forEach(cat => {
        const pill = document.createElement('button');
        pill.className = 'cat-pill';
        pill.textContent = cat.name;
        pill.dataset.slug = cat.slug;
        pill.addEventListener('click', () => setCategory(cat.slug, pill));
        categoryPills.appendChild(pill);
      });

      // Activate the pill matching the current URL state
      if (activeCategory) {
        const match = categoryPills.querySelector(`[data-slug="${CSS.escape(activeCategory)}"]`);
        if (match) {
          categoryPills.querySelectorAll('.cat-pill').forEach(p => p.classList.remove('cat-pill--active'));
          match.classList.add('cat-pill--active');
        }
      }
    } catch { /* non-critical */ }
  }

  function setCategory(slug, activePill) {
    activeCategory = slug || null;
    searchQuery = '';
    if (searchInput) searchInput.value = '';
    categoryPills.querySelectorAll('.cat-pill').forEach(p => p.classList.remove('cat-pill--active'));
    activePill.classList.add('cat-pill--active');
    currentPage = 1;
    loadPosts(1);
  }

  // ── Search input (debounced) ───────────────────────────────────
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchQuery = searchInput.value.trim();

      if (searchQuery.length === 0) {
        // Clear search — restore category view
        currentPage = 1;
        loadPosts(1);
        return;
      }
      if (searchQuery.length < 2) return;

      // Clear active category pill highlight when searching
      categoryPills.querySelectorAll('.cat-pill').forEach(p => p.classList.remove('cat-pill--active'));
      categoryPills.querySelector('.cat-pill')?.classList.add('cat-pill--active');
      activeCategory = null;

      searchTimer = setTimeout(() => runSearch(searchQuery, 1), 300);
    });
  }

  // ── Pagination buttons ────────────────────────────────────────
  prevBtn.addEventListener('click', () => {
    if (currentPage > 1) refresh(currentPage - 1);
  });
  nextBtn.addEventListener('click', () => {
    refresh(currentPage + 1);
  });

  // ── Init: restore state from URL ─────────────────────────────
  const initState = getUrlState();
  currentPage    = initState.page;
  activeCategory = initState.category;
  searchQuery    = initState.q;
  if (searchInput && searchQuery) searchInput.value = searchQuery;

  loadCategories();
  refresh(currentPage);
}

// ════════════════════════════════════════
// BLOG POST
// ════════════════════════════════════════

const postContentEl = document.getElementById('post-content');

if (postContentEl) {
  // Pretty URL: /blog/my-post  — fall back to legacy /blog/post.html?slug=my-post
  const _last = location.pathname.replace(/\/$/, '').split('/').pop();
  const slug  = (_last && _last !== 'post.html')
    ? _last
    : new URLSearchParams(location.search).get('slug');

  async function loadPost() {
    if (!slug) { showPostError(); return; }

    try {
      const res = await fetch(`${API}/posts/${encodeURIComponent(slug)}`);
      if (res.status === 404) { showPostError(); return; }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const post = await res.json();
      renderPost(post);

    } catch (err) {
      showPostError();
      console.error('loadPost error:', err);
    }
  }

  function renderPost(post) {
    // Document metadata
    const title = post.title + ' — Cloudista';
    document.title = title;
    const desc    = post.excerpt || post.title;
    const postUrl = `https://cloudista.org/blog/${post.slug}`;

    const metaDesc      = document.getElementById('meta-description');
    const ogTitle       = document.getElementById('og-title');
    const ogDesc        = document.getElementById('og-description');
    const ogUrl         = document.getElementById('og-url');
    const twitterTitle  = document.getElementById('twitter-title');
    const twitterDesc   = document.getElementById('twitter-description');
    const canonical     = document.getElementById('canonical');

    const ogImage = document.querySelector('meta[property="og:image"]');
    const twImage = document.querySelector('meta[name="twitter:image"]');
    const heroImg = post.image_url
      ? (location.hostname === 'localhost' ? post.image_url : `https://cloudista.org${post.image_url}`)
      : null;

    if (metaDesc)     metaDesc.setAttribute('content', desc);
    if (ogTitle)      ogTitle.setAttribute('content', post.title);
    if (ogDesc)       ogDesc.setAttribute('content', desc);
    if (ogUrl)        ogUrl.setAttribute('content', postUrl);
    if (twitterTitle) twitterTitle.setAttribute('content', post.title);
    if (twitterDesc)  twitterDesc.setAttribute('content', desc);
    if (canonical)    canonical.setAttribute('href', postUrl);
    if (heroImg) {
      if (ogImage) ogImage.setAttribute('content', heroImg);
      if (twImage) twImage.setAttribute('content', heroImg);
    }

    // JSON-LD structured data (BlogPosting)
    const existingLd = document.getElementById('json-ld-blogposting');
    if (existingLd) existingLd.remove();
    const ldScript = document.createElement('script');
    ldScript.id   = 'json-ld-blogposting';
    ldScript.type = 'application/ld+json';
    const publishedDate = post.published_at
      ? new Date(post.published_at).toISOString().split('T')[0]
      : '';
    const modifiedDate = post.updated_at
      ? new Date(post.updated_at).toISOString().split('T')[0]
      : publishedDate;
    ldScript.textContent = JSON.stringify({
      '@context':      'https://schema.org',
      '@type':         'BlogPosting',
      'headline':      post.title,
      'description':   desc,
      'datePublished': publishedDate,
      'dateModified':  modifiedDate,
      'author':        {'@type': 'Person', 'name': post.author},
      'url':           postUrl,
      'publisher':     {'@type': 'Organization', 'name': 'Cloudista', 'url': 'https://cloudista.org'},
    });
    document.head.appendChild(ldScript);

    // Header
    document.getElementById('post-title').textContent = post.title;
    document.getElementById('post-meta').innerHTML = `
      <span>${escHtml(formatDate(post.published_at))}</span>
      <span aria-hidden="true">·</span>
      <span>${escHtml(post.author)}</span>
    `;

    // Hero image
    const heroEl     = document.getElementById('post-hero');
    const heroImgEl  = document.getElementById('post-hero-img');
    const heroCreditEl = document.getElementById('post-hero-credit');
    if (post.image_url && heroEl && heroImgEl) {
      heroImgEl.src = post.image_url;
      heroImgEl.alt = post.title;
      if (heroCreditEl && post.image_credit) {
        heroCreditEl.innerHTML = post.image_credit;
        heroCreditEl.hidden = false;
      }
      heroEl.hidden = false;
    }

    // Body — content_html already sanitized server-side via Python-Markdown
    const bodyEl = document.getElementById('post-body');
    bodyEl.innerHTML = post.content_html;

    // Open external links in a new tab
    bodyEl.querySelectorAll('a[href]').forEach(a => {
      if (a.hostname && a.hostname !== location.hostname) {
        a.setAttribute('target', '_blank');
        a.setAttribute('rel', 'noopener noreferrer');
      }
    });

    // Show content, hide loading skeleton
    document.getElementById('post-loading').style.display = 'none';
    postContentEl.style.display = '';

    // Related posts (non-blocking)
    loadRelatedPosts(post.slug);
  }

  function showPostError() {
    document.getElementById('post-loading').style.display = 'none';
    document.getElementById('post-error').style.display = '';
  }

  // ── Related posts ─────────────────────────────────────────────
  async function loadRelatedPosts(slug) {
    const section = document.getElementById('related-posts');
    if (!section) return;

    try {
      const res = await fetch(`${API}/posts/${encodeURIComponent(slug)}/related`);
      if (!res.ok) return;
      const posts = await res.json();
      if (!posts.length) return;

      section.innerHTML = `
        <h2 class="related-posts__heading">Related posts</h2>
        <div class="related-posts__grid">
          ${posts.map(p => `
            <a class="related-card" href="/blog/${p.slug}">
              <span class="related-card__date">${escHtml(formatDate(p.published_at))}</span>
              <span class="related-card__title">${escHtml(p.title)}</span>
            </a>`).join('')}
        </div>`;
      section.hidden = false;
    } catch { /* non-critical */ }
  }

  // Restore "Back to Blog" to the page the user came from
  const backEl = document.querySelector('.post-back');
  if (backEl) {
    const savedPage = parseInt(sessionStorage.getItem('blogListingPage'), 10);
    if (savedPage > 1) backEl.href = `/page/${savedPage}`;
  }

  if (postContentEl.dataset.prerendered) {
    // Content already rendered server-side — just load related posts progressively.
    if (slug) loadRelatedPosts(slug);
  } else {
    loadPost();
  }
}
