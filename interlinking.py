import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET
import gzip
import io

# -------------------------
# Globals / Headers
# -------------------------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
}

def _norm_netloc(u: str) -> str:
    try:
        n = urlparse(u).netloc.lower()
        return n[4:] if n.startswith("www.") else n
    except Exception:
        return ""

def _same_host(a: str, b: str) -> bool:
    return _norm_netloc(a) == _norm_netloc(b)

def _is_http_url(href: str) -> bool:
    if not href:
        return False
    href = href.strip()
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return False
    return href.startswith(("http://", "https://", "/"))

# -------------------------
# Extract internal links from a given URL (used by both features)
# -------------------------
def get_internal_links(base_url):
    try:
        response = requests.get(base_url, headers=HEADERS, timeout=15, allow_redirects=True)
        if response.status_code != 200 or not response.text:
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        links = []

        for a in soup.find_all('a', href=True):
            if not _is_http_url(a['href']):
                continue
            href = urljoin(base_url, a['href']).split('#')[0]
            if _same_host(href, base_url):
                anchor = a.get_text(strip=True)
                links.append((href, anchor))
        return links
    except Exception:
        return []

# -------------------------
# Crawl pages only from the selected category (unchanged logic, but with headers)
# -------------------------
def crawl_filtered_pages(home_url, selected_category, max_pages=300):
    visited = set()
    queue = [home_url.rstrip('/')]
    results = []

    category_keywords = {
        "Blog Pages": "/blog",
        "Blog Categories": "/category",
        "Product Pages": ["/product", "/products"],
        "All Pages": None
    }
    match_keywords = category_keywords.get(selected_category)

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        links = get_internal_links(url)

        # record result if page itself matches the chosen category (or "All Pages")
        if selected_category == "All Pages" or (
            isinstance(match_keywords, list) and any(kw in url for kw in match_keywords)
        ) or (
            isinstance(match_keywords, str) and match_keywords in url
        ):
            results.append((url, links))

        # queue traversal policy
        for link, _ in links:
            if link in visited or link in queue:
                continue
            if selected_category == "All Pages":
                queue.append(link)
            elif isinstance(match_keywords, list):
                if any(kw in link for kw in match_keywords):
                    queue.append(link)
            elif isinstance(match_keywords, str):
                if match_keywords in link:
                    queue.append(link)

    return results

# -------------------------
# NEW: Robust sitemap discovery + parsing
#   - robots.txt discovery
#   - sitemap index support
#   - nested sitemaps
#   - .xml.gz support
#   - domain filtering
# -------------------------
def _fetch_text(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        if r.status_code == 200:
            return r
    except Exception:
        pass
    return None

def _read_xml_text(resp, url):
    """Return XML text; handle gzipped sitemaps."""
    if resp is None:
        return None
    try:
        ct = (resp.headers.get("Content-Type") or "").lower()
        if url.lower().endswith(".gz") or "gzip" in ct or "x-gzip" in ct:
            # Decompress .gz
            data = io.BytesIO(resp.content)
            with gzip.GzipFile(fileobj=data) as gz:
                return gz.read().decode("utf-8", errors="replace")
        # plain xml/text
        if resp.text:
            return resp.text
    except Exception:
        return None
    return None

def _parse_sitemap_xml(xml_text):
    """Return (root_tag, list_of_text_in_loc_tags)."""
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return None, []
    # namespace-agnostic tag name
    tag = root.tag.lower()
    if '}' in tag:
        tag = tag.split('}', 1)[1]
    locs = [el.text.strip() for el in root.findall(".//{*}loc") if el.text]
    return tag, locs

def _discover_sitemaps_from_robots(home_url):
    # robots.txt can list sitemaps
    robots_url = urljoin(home_url, "/robots.txt")
    resp = _fetch_text(robots_url)
    sitemaps = []
    if resp and resp.text:
        for line in resp.text.splitlines():
            if line.lower().startswith("sitemap:"):
                sm = line.split(":", 1)[1].strip()
                if sm:
                    sitemaps.append(sm)
    return sitemaps

def _candidate_sitemap_urls(home_url):
    # common locations + robots.txt discovery
    candidates = [
        urljoin(home_url, "/sitemap.xml"),
        urljoin(home_url, "/sitemap_index.xml"),
        urljoin(home_url, "/sitemap-index.xml"),
        urljoin(home_url, "/sitemap/sitemap.xml"),
    ]
    robots_listed = _discover_sitemaps_from_robots(home_url)
    for sm in robots_listed:
        if sm not in candidates:
            candidates.append(sm)
    return candidates

def _filter_same_site_urls(urls, home_url):
    base = _norm_netloc(home_url)
    filtered = []
    for u in urls:
        try:
            if _norm_netloc(u) == base:
                # normalize: drop fragment; keep path/query (often important)
                filtered.append(u.split("#")[0].strip())
        except Exception:
            continue
    # de-dup while keeping order
    seen = set()
    out = []
    for u in filtered:
        if u not in seen:
            out.append(u)
            seen.add(u)
    return out

def _collect_urls_from_sitemaps(home_url, visit_limit=30_000):
    """Follow sitemap index → nested sitemaps → URL sets. Returns list of URLs for same host."""
    to_visit = _candidate_sitemap_urls(home_url)
    seen_sitemaps = set()
    found_urls = []

    while to_visit and len(found_urls) < visit_limit:
        sm_url = to_visit.pop(0)
        if sm_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sm_url)

        resp = _fetch_text(sm_url)
        xml_text = _read_xml_text(resp, sm_url)
        if not xml_text:
            continue

        root_tag, locs = _parse_sitemap_xml(xml_text)
        if not locs:
            continue

        # If it's a sitemapindex, enqueue child sitemaps; else it's a urlset
        if root_tag == "sitemapindex":
            # child entries are sitemaps themselves
            for child_sm in locs:
                if child_sm not in seen_sitemaps:
                    to_visit.append(child_sm)
        else:
            # urlset (or anything with <loc> that are page URLs)
            urls = _filter_same_site_urls(locs, home_url)
            if urls:
                found_urls.extend(urls)

    # de-dup keep order
    seen = set()
    ordered = []
    for u in found_urls:
        if u not in seen:
            ordered.append(u)
            seen.add(u)
    return ordered

# -------------------------
# New: Find ALL internal URLs (Sitemap-first + Robust) with fallback to your HTML crawl
# -------------------------
def find_all_internal_urls(home_url, max_pages=500):
    home_url = home_url.strip()
    if not home_url:
        return []

    # Prefer HTTPS if user passed naked domain with HTTP
    if home_url.startswith("http://"):
        https_variant = "https://" + home_url.split("://", 1)[1]
        # try https first silently; if it fails, we'll still try http via requests below

    # 1) Try robust sitemap path (robots.txt + sitemap index + .gz)
    try:
        sitemap_urls = _collect_urls_from_sitemaps(home_url)
        if sitemap_urls:
            return sitemap_urls
    except Exception:
        pass

    # 2) Fallback: lightweight crawl using your existing logic
    all_urls = set()
    visited = set()
    queue = [home_url.rstrip('/')]

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        links = get_internal_links(url)
        for link, _ in links:
            if link not in visited and link not in queue:
                queue.append(link)
        all_urls.add(url)

    # Keep only same host and return sorted
    keep = _filter_same_site_urls(sorted(all_urls), home_url)
    return keep

# -------------------------
# Streamlit UI (your original UI preserved)
# -------------------------
st.set_page_config(page_title="Internal Link Checker", layout="wide")
st.title("🔗 Target URL Interlink Checker")

st.markdown("""
Use this tool to **find which internal pages link to specific target URLs**.

**Instructions:**
1. Enter your website's homepage (e.g. `https://www.reset.in`)
2. Choose which category of pages to crawl
3. Enter one or more **target URLs** (separated by commas or new lines)
""")

home_url = st.text_input("🌐 Enter your homepage URL (e.g. https://www.reset.in):", "")

category_choice = st.selectbox(
    "📂 Choose the type of pages to crawl:",
    ["Blog Pages", "Blog Categories", "Product Pages", "All Pages"]
)

target_input = st.text_area("🎯 Enter target URLs (separate by commas or new lines):")
target_urls = [url.strip().rstrip('/') for url in target_input.replace(',', '\n').splitlines() if url.strip()]

if st.button("Check Interlinking Pages"):
    if not home_url or not target_urls:
        st.error("❗ Please enter both the homepage and at least one target URL.")
    else:
        with st.spinner(f"🚀 Crawling up to 300 pages from {category_choice}..."):
            crawled = crawl_filtered_pages(home_url, category_choice)

        if not crawled:
            st.warning("😕 No matching pages found during crawl.")
        else:
            st.success(f"✅ Crawled {len(crawled)} pages. Now checking for links to your targets...")

            # Slightly optimized matching
            targets_set = set(t.rstrip('/') for t in target_urls)
            matches_by_target = {target: [] for target in targets_set}

            for page, links in crawled:
                for link, anchor in links:
                    link_norm = link.rstrip('/')
                    if link_norm in targets_set:
                        matches_by_target[link_norm].append((page, anchor))

            st.markdown("---\n## 🔍 Interlinking Results")

            total_found = sum(len(v) for v in matches_by_target.values())
            if total_found == 0:
                st.info("🚫 No internal links found to the target URLs in the selected category.")
            else:
                st.success(f"🔗 Found {total_found} total links to your targets.\n")

                for target in target_urls:
                    key = target.rstrip('/')
                    matches = matches_by_target.get(key, [])
                    st.markdown(f"### 🎯 Target URL: `{target}`")
                    if matches:
                        for page, anchor in matches:
                            st.markdown(f"""
**From Page:** [{page}]({page})  
**Anchor Text:** `{anchor or '(no text)'}`  
---""")
                    else:
                        st.info("No pages link to this target.")

# --- NEW FEATURE (kept): Find all internal URLs ---
st.markdown("---")
with st.expander("🌐 Find All Internal URLs of a Website"):
    st.markdown("Use this tool to **extract and list all internal URLs** of a given website.")
    website_url = st.text_input("Enter website homepage URL:", "", key="find_all_box")
    if st.button("Find All URLs", key="find_all_btn"):
        if not website_url:
            st.error("❗ Please enter a valid website URL.")
        else:
            with st.spinner(f"🔍 Scanning {website_url} for internal URLs..."):
                all_urls = find_all_internal_urls(website_url)

            if not all_urls:
                st.warning("⚠️ No internal URLs found! (Site may block bots or hide links in JS; we tried sitemap + fallback crawl.)")
            else:
                st.success(f"✅ Found {len(all_urls)} internal URLs!")
                for link in all_urls:
                    st.markdown(f"- [{link}]({link})")
