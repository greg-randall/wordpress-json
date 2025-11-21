import os
import sys
import json
import argparse
import asyncio
import time
import urllib.parse
import random
from datetime import datetime, timedelta, timezone
from nodriver_helper import NodriverBrowser, fetch_json_from_urls, sanitize_filename
from tqdm.asyncio import tqdm

def build_domain_urls(domains, hours_ago):
    """
    Build all URLs that need to be fetched for all domains.
    Returns a list of tuples: (url, domain, page_number)
    """
    after_date = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    after_date_iso = after_date.isoformat(timespec='seconds').replace('+00:00', 'Z')

    url_metadata = []

    for domain in domains:
        base_url = f"https://{domain.strip()}"
        posts_url = f"{base_url}/wp-json/wp/v2/posts"

        # Start with page 1 for each domain
        params = {
            'after': after_date_iso,
            'page': 1,
            'per_page': 100,
            'orderby': 'date',
            'order': 'asc'
        }

        query_string = urllib.parse.urlencode(params)
        url = f"{posts_url}?{query_string}"

        url_metadata.append((url, domain, 1))

    return url_metadata


async def collect_wordpress_posts(domains_file, hours_ago, debug_mode=False):
    """
    Collects recent WordPress posts from a list of domains.

    Args:
        domains_file: Path to file containing list of domains
        hours_ago: How many hours back to fetch posts
        debug_mode: If True, saves all page content for debugging
    """
    # Create directory structure
    if not os.path.exists("wordpress_posts"):
        os.makedirs("wordpress_posts")
    date_str = datetime.now().strftime("%Y-%m-%d")
    date_dir = os.path.join("wordpress_posts", date_str)
    if not os.path.exists(date_dir):
        os.makedirs(date_dir)
    timestamp_str = str(int(time.time()))
    timestamp_dir = os.path.join(date_dir, timestamp_str)
    os.makedirs(timestamp_dir)

    summary = {
        "collection_timestamp": timestamp_str,
        "collection_date": date_str,
        "hours_ago": hours_ago,
        "results": []
    }

    try:
        with open(domains_file, 'r') as f:
            domains = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"Error: '{domains_file}' not found.")
        return

    # Build initial URLs (first page for each domain)
    url_metadata = build_domain_urls(domains, hours_ago)
    urls = [item[0] for item in url_metadata]

    if debug_mode:
        print("🐛 DEBUG MODE ENABLED: All page content will be saved to debug_pages/")
        print("   - Success pages: *_success.html")
        print("   - Error pages: *_error.html\n")

    # Track domain data
    domain_data = {domain: {"posts": [], "pages_fetched": 0, "status": "pending", "post_ids": set()} for domain in domains}

    # Maximum pages to fetch per domain (safety limit)
    MAX_PAGES_PER_DOMAIN = 20

    def on_success(url, data, index):
        """Callback for successful fetch - handle pagination and save results"""
        domain = url_metadata[index][1]
        page_num = url_metadata[index][2]

        # Check for duplicate posts (indicates we've hit the end or a loop)
        new_posts = []
        duplicate_count = 0
        for post in data:
            post_id = post.get('id')
            if post_id and post_id not in domain_data[domain]["post_ids"]:
                domain_data[domain]["post_ids"].add(post_id)
                new_posts.append(post)
            elif post_id:
                duplicate_count += 1

        # Store only new posts
        domain_data[domain]["posts"].extend(new_posts)
        domain_data[domain]["pages_fetched"] = page_num

        if duplicate_count > 0:
            print(f"✓ {domain} page {page_num}: {len(new_posts)} new posts ({duplicate_count} duplicates - stopping pagination)")
        else:
            print(f"✓ {domain} page {page_num}: {len(new_posts)} posts")

        # Save to file immediately in realtime
        if domain_data[domain]["posts"]:
            sanitized_domain = sanitize_filename(domain) + ".json"
            filepath = os.path.join(timestamp_dir, sanitized_domain)
            with open(filepath, 'w') as f:
                json.dump(domain_data[domain]["posts"], f, indent=2)
            print(f"  → Saved to {filepath}")

        # Check if we need to fetch next page
        # Stop if: no new posts, hit max pages, or got less than full page
        should_paginate = (
            len(new_posts) == 100 and
            duplicate_count == 0 and
            page_num < MAX_PAGES_PER_DOMAIN
        )

        if should_paginate:
            # Build next page URL
            after_date = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
            after_date_iso = after_date.isoformat(timespec='seconds').replace('+00:00', 'Z')
            base_url = f"https://{domain.strip()}"
            posts_url = f"{base_url}/wp-json/wp/v2/posts"

            next_page = page_num + 1
            params = {
                'after': after_date_iso,
                'page': next_page,
                'per_page': 100,
                'orderby': 'date',
                'order': 'asc'
            }

            query_string = urllib.parse.urlencode(params)
            next_url = f"{posts_url}?{query_string}"

            # Add to fetch list
            urls.append(next_url)
            url_metadata.append((next_url, domain, next_page))

    def on_error(url, error, content, index):
        """Callback for failed fetch"""
        domain = url_metadata[index][1]
        page_num = url_metadata[index][2]

        print(f"✗ {domain} page {page_num}: {error}")
        domain_data[domain]["status"] = "error"
        domain_data[domain]["error"] = error

    # Use context manager for browser lifecycle
    async with NodriverBrowser() as browser:
        # Fetch all URLs sequentially using single browser instance with callbacks
        await fetch_json_from_urls(
            browser,
            urls,
            wait_time=3.0,
            selector='body',
            selector_timeout=10.0,
            delay_range=(0, 1),
            debug_dir="debug_pages",
            on_success=on_success,
            on_error=on_error,
            progress_desc="Collecting WordPress posts",
            debug_mode=debug_mode
        )

    # Save results and build summary
    for domain in domains:
        data = domain_data[domain]
        result = {
            "domain": domain,
            "status": "success" if data["posts"] else data.get("status", "failed"),
            "article_count": len(data["posts"]),
            "pages_fetched": data["pages_fetched"],
            "error_message": data.get("error"),
            "file_path": None
        }

        # Save posts if we have any
        if data["posts"]:
            sanitized_domain = sanitize_filename(domain) + ".json"
            filepath = os.path.join(timestamp_dir, sanitized_domain)
            with open(filepath, 'w') as f:
                json.dump(data["posts"], f, indent=2)

            result["file_path"] = filepath
            result["status"] = "success"
        elif not result.get("error_message"):
            result["error_message"] = "No articles found in timeframe"

        summary["results"].append(result)

    # Write summary file
    summary_filepath = os.path.join(timestamp_dir, "_collection_summary.json")
    with open(summary_filepath, 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"\nCollection complete. Summary written to {summary_filepath}")
    print(f"Total articles collected: {sum(r['article_count'] for r in summary['results'])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch recent posts from multiple WordPress sites using nodriver.")
    parser.add_argument("--domains-file", default="wordpress.txt", help="A text file with a list of domains to fetch from.")
    parser.add_argument("--hours", type=int, default=48, help="Number of hours ago to fetch posts from. (default: 48)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode to save all page content (success and errors) to debug_pages/")

    args = parser.parse_args()

    asyncio.run(collect_wordpress_posts(args.domains_file, args.hours, args.debug))