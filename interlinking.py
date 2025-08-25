import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

# --- Extract internal links from a given URL ---
def get_internal_links(base_url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(base_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        base_domain = urlparse(base_url).netloc
        links = []

        for a in soup.find_all('a', href=True):
            href = urljoin(base_url, a['href']).split('#')[0]
            if urlparse(href).netloc == base_domain:
                anchor = a.get_text(strip=True)
                links.append((href, anchor))
        return links
    except:
        return []

# --- Crawl pages only from the selected category ---
def crawl_filtered_pages(home_url, selected_category, max_pages=300):
    visited = set()
    queue = [home_url]
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

        if selected_category == "All Pages" or (
            isinstance(match_keywords, list) and any(kw in url for kw in match_keywords)
        ) or (
            isinstance(match_keywords, str) and match_keywords in url
        ):
            results.append((url, links))

        for link, _ in links:
            if link not in visited and link not in queue:
                if selected_category == "All Pages":
                    queue.append(link)
                elif isinstance(match_keywords, list):
                    if any(kw in link for kw in match_keywords):
                        queue.append(link)
                elif isinstance(match_keywords, str):
                    if match_keywords in link:
                        queue.append(link)

    return results

# --- New: Find ALL internal URLs of a website ---
def find_all_internal_urls(home_url, max_pages=500):
    visited = set()
    queue = [home_url]
    all_urls = []

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        links = get_internal_links(url)
        for link, _ in links:
            if link not in visited and link not in queue:
                queue.append(link)

        all_urls.append(url)

    return sorted(all_urls)

# --- Streamlit UI ---
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

            matches_by_target = {target: [] for target in target_urls}

            for page, links in crawled:
                for link, anchor in links:
                    for target in target_urls:
                        if target == link.rstrip('/'):
                            matches_by_target[target].append((page, anchor))

            st.markdown("---\n## 🔍 Interlinking Results")

            total_found = sum(len(v) for v in matches_by_target.values())
            if total_found == 0:
                st.info("🚫 No internal links found to the target URLs in the selected category.")
            else:
                st.success(f"🔗 Found {total_found} total links to your targets.\n")

                for target, matches in matches_by_target.items():
                    st.markdown(f"### 🎯 Target URL: `{target}`")
                    if matches:
                        for page, anchor in matches:
                            st.markdown(f"""
**From Page:** [{page}]({page})  
**Anchor Text:** `{anchor or '(no text)'}`  
---""")
                    else:
                        st.info("No pages link to this target.")

# --- NEW FEATURE: Find all internal URLs ---
st.markdown("---")
with st.expander("🌐 Find All Internal URLs of a Website"):
    st.markdown("Use this tool to **extract and list all internal URLs** of a given website.")

    website_url = st.text_input("Enter website homepage URL:", "")
    if st.button("Find All URLs"):
        if not website_url:
            st.error("❗ Please enter a valid website URL.")
        else:
            with st.spinner(f"🔍 Scanning {website_url} for internal URLs..."):
                all_urls = find_all_internal_urls(website_url)

            if not all_urls:
                st.warning("⚠️ No internal URLs found!")
            else:
                st.success(f"✅ Found {len(all_urls)} internal URLs!")
                for link in all_urls:
                    st.markdown(f"- [{link}]({link})")
