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

        # Save the page if it matches selected category (or is All Pages)
        if selected_category == "All Pages" or (
            isinstance(match_keywords, list) and any(kw in url for kw in match_keywords)
        ) or (
            isinstance(match_keywords, str) and match_keywords in url
        ):
            results.append((url, links))

        # Enqueue links that match the selected category
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

# --- Streamlit UI ---
st.set_page_config(page_title="Internal Link Checker", layout="wide")
st.title("🔗 Target URL Interlink Checker")

st.markdown("""
Use this tool to **find which internal pages link to a specific target URL**.

**Instructions:**
1. Enter your website's homepage (e.g. `https://www.reset.in`)
2. Choose which category of pages to crawl
3. Enter the **target URL** you want to check interlinking for
""")

home_url = st.text_input("🌐 Enter your homepage URL (e.g. https://www.reset.in):", "")

category_choice = st.selectbox(
    "📂 Choose the type of pages to crawl:",
    ["Blog Pages", "Blog Categories", "Product Pages", "All Pages"]
)

target_input = st.text_area("🎯 Enter the target URL (the one you want to see interlinking for):")
target_url = target_input.strip()

if st.button("Check Interlinking Pages"):
    if not home_url or not target_url:
        st.error("❗ Please enter both the homepage and target URL.")
    else:
        with st.spinner(f"🚀 Crawling up to 300 pages from {category_choice}..."):
            crawled = crawl_filtered_pages(home_url, category_choice)

        if not crawled:
            st.warning("😕 No matching pages found during crawl.")
        else:
            st.success(f"✅ Crawled {len(crawled)} pages. Now checking for links to your target...")

            matches = []
            for page, links in crawled:
                for link, anchor in links:
                    if target_url.rstrip('/') == link.rstrip('/'):
                        matches.append((page, anchor))

            st.markdown(f"---\n### 🔍 Interlinking Results for: `{target_url}`")
            if matches:
                st.success(f"🔗 Found {len(matches)} pages linking to your target.")
                for page, anchor in matches:
                    st.markdown(f"**From Page:** [{page}]({page})  \n**Anchor Text:** `{anchor or '(no text)'}`\n")
            else:
                st.info("🚫 No internal links found to the target URL in the selected category.")
