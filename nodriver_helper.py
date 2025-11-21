"""
Nodriver Helper - Browser automation utilities for fetching JSON from URLs

USAGE BEST PRACTICES:

This module is designed to process URLs sequentially in a single browser instance,
which is more efficient and stable than opening multiple tabs concurrently.

RECOMMENDED APPROACH:
    1. Create a single list of all URLs you need to fetch
    2. Use NodriverBrowser context manager to create one browser instance
    3. Call fetch_json_from_urls once with all URLs and callbacks
    4. Handle results in callbacks (on_success, on_error) as they arrive
    5. Dynamic pagination: Add new URLs to the list inside callbacks if needed

Example:
    urls = ["https://example.com/api/page1", "https://example.com/api/page2"]

    def on_success(url, data, index):
        # Save data immediately
        save_to_file(data)

        # If pagination needed, add next page URL
        if len(data) == 100:  # Full page, might have more
            urls.append(f"https://example.com/api/page{index + 2}")

    def on_error(url, error, content, index):
        print(f"Failed to fetch {url}: {error}")

    async with NodriverBrowser() as browser:
        await fetch_json_from_urls(
            browser,
            urls,
            on_success=on_success,
            on_error=on_error
        )

AVOID THIS ANTI-PATTERN:
    # DON'T create concurrent tasks that all use the browser at once
    # This opens too many tabs simultaneously and can crash the browser

    async with NodriverBrowser() as browser:
        tasks = [fetch_domain(browser, domain) for domain in domains]
        results = await asyncio.gather(*tasks)  # BAD: Opens all tabs at once!

WHY SEQUENTIAL IS BETTER:
    - Only one tab open at a time (lower memory usage)
    - Built-in delays between requests (polite to servers)
    - Better error handling and recovery
    - Dynamic pagination support
    - Progress tracking with tqdm
    - Proper resource cleanup
"""

import nodriver as uc
import asyncio
import json
import random
import os
import re
from typing import List, Dict, Optional, Tuple, Callable, Any
from tqdm import tqdm


class NodriverBrowser:
    """
    Context manager for nodriver browser lifecycle management.
    Ensures proper cleanup even if errors occur.

    Usage:
        async with NodriverBrowser() as browser:
            results = await fetch_json_from_urls(browser, urls)
    """

    def __init__(self):
        self.browser = None

    async def __aenter__(self):
        self.browser = await uc.start()
        return self.browser

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            try:
                await self.browser.stop()
            except Exception:
                pass  # Ignore errors when stopping browser
        return False


def sanitize_filename(text: str) -> str:
    """
    Sanitize text for use in filenames by replacing problematic characters.

    Args:
        text: Text to sanitize (e.g., domain name)

    Returns:
        Sanitized string safe for use in filenames
    """
    return text.replace(".", "_").replace("/", "_").replace(":", "_")


def extract_json_from_content(content: str) -> dict:
    """
    Extract JSON from page content. Tries pure JSON first, then falls back
    to extracting JSON embedded in HTML content.

    Args:
        content: Raw page content (JSON or HTML with embedded JSON)

    Returns:
        Parsed JSON as dictionary or list

    Raises:
        ValueError: If JSON cannot be extracted or parsed
        json.JSONDecodeError: If JSON is malformed
    """
    try:
        # First, assume content is pure JSON
        return json.loads(content)
    except json.JSONDecodeError:
        # Check if content is wrapped in HTML tags
        if content.strip().startswith('<html') or content.strip().startswith('<!DOCTYPE'):
            # Strip HTML tags from start and end using regex
            # Remove opening tags from the beginning
            cleaned = re.sub(r'^(<[^>]+>)+', '', content, flags=re.MULTILINE | re.DOTALL)
            # Remove closing tags from the end
            cleaned = re.sub(r'(</[^>]+>)+\s*$', '', cleaned, flags=re.MULTILINE | re.DOTALL)
            cleaned = cleaned.strip()

            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass  # Fall through to manual extraction

        # Final fallback: manually find first { or [ to last } or ]
        # Check for JSON array first
        array_start = content.find('[')
        array_end = content.rfind(']') + 1

        # Check for JSON object
        obj_start = content.find('{')
        obj_end = content.rfind('}') + 1

        # Determine which comes first and use that
        if array_start != -1 and (obj_start == -1 or array_start < obj_start):
            if array_end > array_start:
                json_str = content[array_start:array_end]
                return json.loads(json_str)
        elif obj_start != -1 and obj_end > obj_start:
            json_str = content[obj_start:obj_end]
            return json.loads(json_str)

        raise ValueError("Could not extract JSON from page content.")


async def fetch_json_from_urls(
    browser,
    urls: List[str],
    wait_time: float = 3.0,
    selector: str = 'body',
    selector_timeout: float = 10.0,
    delay_range: Tuple[float, float] = (3.0, 15.0),
    debug_dir: Optional[str] = "debug_pages",
    on_success: Optional[Callable[[str, dict, int], Any]] = None,
    on_error: Optional[Callable[[str, str, Optional[str], int], Any]] = None,
    progress_desc: str = "Fetching URLs",
    debug_mode: bool = False
) -> List[Dict]:
    """
    Fetch and parse JSON content from multiple URLs using a single browser instance.
    Each URL is opened in a new tab for isolation, then closed after processing.
    Results are saved immediately via callbacks as they are fetched.

    Args:
        browser: Active nodriver browser instance
        urls: List of URLs to fetch
        wait_time: Seconds to wait after page load (default: 3.0)
        selector: CSS selector to wait for (default: 'body')
        selector_timeout: Timeout for selector wait in seconds (default: 10.0)
        delay_range: Tuple of (min, max) seconds for random delay between requests (default: 3-15)
        debug_dir: Directory to save failed page content for debugging (default: 'debug_pages', None to disable)
        on_success: Callback function(url, data, index) called immediately when URL is successfully fetched
        on_error: Callback function(url, error, content, index) called immediately when URL fetch fails
        progress_desc: Description for the progress bar (default: 'Fetching URLs')
        debug_mode: If True, saves ALL page content (success and error) for inspection (default: False)

    Returns:
        List of result dictionaries, one per URL:
        - Success: {"url": str, "status": "success", "data": dict}
        - Error: {"url": str, "status": "error", "error": str, "content": str (optional)}
    """
    results = []

    for i, url in tqdm(enumerate(urls), total=len(urls), desc=progress_desc, unit="url"):
        page = None
        content = None

        try:
            # Open URL in new tab for isolation
            page = await browser.get(url, new_tab=True)

            # Wait for page to load
            await page.sleep(wait_time)

            # Try to wait for selector (continue even if it times out)
            try:
                await page.select(selector, timeout=selector_timeout)
            except Exception:
                pass  # Continue even if selector times out

            # Get page content
            content = await page.get_content()

            # Parse JSON from content
            data = extract_json_from_content(content)

            # Save debug content in debug mode (even on success)
            if debug_mode and debug_dir and content:
                if not os.path.exists(debug_dir):
                    os.makedirs(debug_dir)

                safe_name = sanitize_filename(url)
                debug_path = os.path.join(debug_dir, f"{safe_name}_success.html")

                with open(debug_path, "w") as f:
                    f.write(content)

            # Call success callback immediately if provided
            if on_success:
                on_success(url, data, i)

            results.append({
                "url": url,
                "status": "success",
                "data": data
            })

        except Exception as e:
            # Save debug content if enabled and content was captured
            if debug_dir and content:
                if not os.path.exists(debug_dir):
                    os.makedirs(debug_dir)

                # Create safe filename from URL
                safe_name = sanitize_filename(url)
                debug_path = os.path.join(debug_dir, f"{safe_name}_error.html")

                with open(debug_path, "w") as f:
                    f.write(content)

            # Call error callback immediately if provided
            if on_error:
                on_error(url, str(e), content, i)

            results.append({
                "url": url,
                "status": "error",
                "error": str(e),
                "content": content if content else None
            })

        finally:
            # Close the tab
            if page:
                try:
                    await page.close()
                except Exception:
                    pass  # Ignore errors when closing page

            # Apply random delay between requests (but not after the last one)
            if i < len(urls) - 1:
                delay = random.uniform(delay_range[0], delay_range[1])
                await asyncio.sleep(delay)

    return results
