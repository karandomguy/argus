import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import re
from urllib.parse import urlparse

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

def web_search(query, max_results=2):
    """
    Returns a list of dictionaries with 'title', 'link', and 'snippet'.
    """
    url = "https://customsearch.googleapis.com/customsearch/v1"
    params = {
        'q': query,
        'cx': GOOGLE_CSE_ID,
        'key': GOOGLE_API_KEY,
        'num': max_results,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        
        # Add error handling for API-specific errors
        data = resp.json()
        if 'error' in data:
            print(f"API Error: {data['error']['message']}")
            return []
            
    except requests.exceptions.RequestException as e:
        print(f"Error during search request: {e}")
        return []
    except ValueError as e:
        print(f"Error parsing JSON response: {e}")
        return []

    results = []
    if "items" in data:
        for item in data["items"]:
            results.append({
                "title": item.get("title"),
                "link": item.get("link"),
                "snippet": item.get("snippet", ""),
                "domain": urlparse(item.get("link", "")).netloc
            })
    return results

def fetch_page_content(url, timeout=10):
    """
    Fetches and extracts meaningful content from a webpage.
    Returns a dictionary containing the cleaned text and metadata.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding  # Handle character encoding better
    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch content from {url}: {e}")
        return {"error": str(e), "content": "", "metadata": {}}

    soup = BeautifulSoup(resp.text, 'lxml')

    # Remove unwanted elements
    for element in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript']):
        element.decompose()

    # Try to find main content area
    main_content = (
        soup.find('article') or 
        soup.find('main') or 
        soup.find(class_=re.compile(r'(content|article|post)-?(body|text|container)?', re.I)) or 
        soup.find('body')
    )

    if main_content:
        # Extract text with better spacing
        text = ' '.join(p.get_text().strip() for p in main_content.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']))
        
        # Cleaning
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'cookie[s]? policy|privacy policy|terms of service', '', text, flags=re.IGNORECASE)
        
        # Extract metadata
        metadata = {
            "title": soup.title.string if soup.title else "",
            "length": len(text.split()),
            "url": url,
            "domain": urlparse(url).netloc
        }

        return {
            "content": text.strip(),
            "metadata": metadata,
            "error": None
        }
    
    return {"error": "No main content found", "content": "", "metadata": {}}

def search_and_extract(query, max_results=2):
    """
    Combines search and content extraction into a single function.
    """
    search_results = web_search(query, max_results)
    
    full_results = []
    for result in search_results:
        content_data = fetch_page_content(result["link"])
        result.update({
            "extracted_content": content_data["content"],
            "metadata": content_data["metadata"],
            "error": content_data["error"]
        })
        full_results.append(result)
    
    return full_results
