import os
import json
import hashlib
import argparse
from datetime import datetime, timezone
from urllib.parse import urlparse
import html2text
import re
# Note: This script requires the 'markdownify' and 'python-dateutil' libraries.
# You can install them with: pip install markdownify python-dateutil
try:
    from markdownify import markdownify
except ImportError:
    print("Warning: 'markdownify' library not found. HTML content will not be converted to Markdown.")
    print("Please install it with: pip install markdownify")
    # Define a fallback function
    def markdownify(html, **options):
        # A very basic fallback: strip tags. This is not a substitute for markdownify.
        import re
        return re.sub('<[^<]+?>', '', html)

try:
    from dateutil.parser import parse as parse_date
except ImportError:
    print("Warning: 'python-dateutil' library not found. Date parsing will be less robust.")
    print("Please install it with: pip install python-dateutil")
    # Define a fallback function for ISO 8601 format
    def parse_date(date_string):
        return datetime.fromisoformat(date_string.replace('Z', '+00:00'))


def normalize_article(article, collection_timestamp):
    """
    Normalizes a single WordPress post object into the standard format.
    Returns a tuple: (normalized_data, error_message).
    """
    article_identifier = article.get('link', f"ID: {article.get('id', 'N/A')}")
    # Required Fields
    try:
        url = article['link']
        
        # Title can sometimes be a string instead of an object
        title_obj = article.get('title', {})
        title = title_obj['rendered'] if isinstance(title_obj, dict) else title_obj

        # Content can also be a string
        content_obj = article.get('content', {})
        html_content = content_obj['rendered'] if isinstance(content_obj, dict) else content_obj

        article_text = markdownify(html_content, heading_style="ATX")
        # Cleanup: replace multiple newlines/spaces with exactly two newlines for consistent paragraph separation
        article_text = re.sub(r'\s*\n{2,}\s*', '\n\n', article_text)
        # Cleanup: remove leading/trailing whitespace (spaces, newlines, tabs)
        article_text = article_text.strip()

        source_domain = urlparse(url).netloc
        
        # 'first_seen_timestamp_gmt' comes from the collection run
        first_seen_timestamp_gmt = int(collection_timestamp)

        # Basic validation
        if not all([url, title, article_text, source_domain, first_seen_timestamp_gmt]):
            error_msg = f"Missing required field for article: {article_identifier}"
            return None, error_msg

    except (KeyError, TypeError) as e:
        error_msg = f"Error processing required fields for article {article_identifier}: {type(e).__name__} - {e}"
        return None, error_msg

    # Recommended & Optional Fields
    publication_date = article.get('date_gmt', '') + 'Z' if article.get('date_gmt') else None
    publication_timestamp_gmt = None
    if publication_date:
        try:
            dt = parse_date(publication_date)
            publication_timestamp_gmt = int(dt.timestamp())
        except (ValueError, TypeError):
            pass # Keep as None if parsing fails

    # Author information is often just an ID without embedding.
    # The standard allows this to be null. 
    author = None 
    
    # Keywords (categories and tags) are also IDs without embedding.
    # We will leave this empty as we cannot resolve the names.
    keywords = []

    image_url = article.get('_links', {}).get('wp:featuredmedia', [{}])[0].get('href')

    # Process excerpt
    excerpt_obj = article.get('excerpt', {})
    raw_excerpt = excerpt_obj.get('rendered') if isinstance(excerpt_obj, dict) else excerpt_obj
    excerpt = ''
    if raw_excerpt:
        excerpt = markdownify(raw_excerpt, heading_style="ATX")
        excerpt = re.sub(r'\s*\n{2,}\s*', '\n\n', excerpt)
        excerpt = excerpt.strip()

    normalized_data = {
        "url": url,
        "title": title,
        "article_text": article_text,
        "source_domain": source_domain,
        "first_seen_timestamp_gmt": first_seen_timestamp_gmt,
        "publication_date": publication_date,
        "publication_timestamp_gmt": publication_timestamp_gmt,
        "author": author,
        "keywords": keywords,
        "image_url": image_url,
        "excerpt": excerpt,
        "metadata": {
            "wp_post_id": article.get('id'),
            "wp_post_type": article.get('type'),
        }
    }
    
    return normalized_data, None

def process_collection_directory(source_dir, output_dir):
    """
    Processes a directory of raw JSON files from collect_news.py.
    """
    if not os.path.isdir(source_dir):
        print(f"Error: Source directory '{source_dir}' not found.")
        return

    # Find the collection summary to get the timestamp
    collection_summary_path = os.path.join(source_dir, "_collection_summary.json")
    if not os.path.exists(collection_summary_path):
        print(f"Error: '_collection_summary.json' not found in '{source_dir}'.")
        return
        
    with open(collection_summary_path, 'r') as f:
        collection_summary = json.load(f)
    collection_timestamp = collection_summary['collection_timestamp']

    stats = {
        "files_processed": 0,
        "articles_new": 0,
        "articles_skipped": 0,
        "errors": 0,
        "errors_list": []
    }

    # Process each JSON file in the source directory
    for filename in os.listdir(source_dir):
        if not filename.endswith(".json") or filename in ["_collection_summary.json", "_normalization_summary.json"]:
            continue

        stats["files_processed"] += 1
        filepath = os.path.join(source_dir, filename)
        
        with open(filepath, 'r') as f:
            try:
                articles = json.load(f)
                if not isinstance(articles, list):
                    raise json.JSONDecodeError("JSON root is not a list", "N/A", 0)
            except json.JSONDecodeError:
                error_msg = f"Error decoding JSON or file is not a list of articles: {filename}"
                stats["errors"] += 1
                stats["errors_list"].append(error_msg)
                print(error_msg)
                continue

        for article in articles:
            if not isinstance(article, dict):
                error_msg = f"Skipping item in {filename} because it's not a dictionary. Item: {str(article)[:150]}"
                stats["errors"] += 1
                stats["errors_list"].append(error_msg)
                continue

            normalized_article, error = normalize_article(article, collection_timestamp)
            
            if error:
                stats["errors"] += 1
                stats["errors_list"].append(error)
                continue

            # File naming convention: MD5 hash of the URL
            url = normalized_article['url']
            url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
            
            domain_dir = os.path.join(output_dir, normalized_article['source_domain'])
            os.makedirs(domain_dir, exist_ok=True)
            
            output_filepath = os.path.join(domain_dir, f"{url_hash}.json")

            # Deduplication: skip if file already exists
            if os.path.exists(output_filepath):
                stats["articles_skipped"] += 1
                continue

            # Write the normalized article to its own file
            try:
                with open(output_filepath, 'w', encoding='utf-8') as f_out:
                    json.dump(normalized_article, f_out, indent=2, ensure_ascii=False)
                stats["articles_new"] += 1
            except Exception as e:
                error_msg = f"Error writing file for article {url}: {e}"
                stats["errors"] += 1
                stats["errors_list"].append(error_msg)

    # Write normalization summary file
    summary_data = {
      "timestamp": datetime.now(timezone.utc).isoformat(),
      "source": "wordpress",
      "statistics": stats
    }
    summary_filepath = os.path.join(source_dir, "_normalization_summary.json")
    with open(summary_filepath, 'w') as f:
        json.dump(summary_data, f, indent=2)

    print(f"\nNormalization complete.")
    print(f" - New articles: {stats['articles_new']}")
    print(f" - Skipped (already exist): {stats['articles_skipped']}")
    if stats['errors'] > 0:
        print(f" - Errors: {stats['errors']} (see summary file for details)")
    else:
        print(f" - Errors: 0")
    print(f"Summary written to {summary_filepath}")


def find_latest_collection_dir(base_dir="wordpress_posts"):
    """
    Finds the most recent collection directory.
    """
    try:
        # Find the latest date directory
        date_dirs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
        if not date_dirs:
            return None
        latest_date_dir = max(date_dirs)
        
        # Find the latest timestamp directory inside the date directory
        timestamp_base_path = os.path.join(base_dir, latest_date_dir)
        timestamp_dirs = [d for d in os.listdir(timestamp_base_path) if os.path.isdir(os.path.join(timestamp_base_path, d))]
        if not timestamp_dirs:
            return None
        latest_timestamp_dir = max(timestamp_dirs)
        
        return os.path.join(timestamp_base_path, latest_timestamp_dir)
    except FileNotFoundError:
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Normalize WordPress posts from a collection directory into the standard format.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "-s", "--source-directory",
        help="The timestamped directory from collect_news.py containing raw JSON files.\nIf not provided, the script will automatically find the most recent one."
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="../normalized_news",
        help="The base directory to save normalized article files. (default: normalized_news)"
    )
    
    args = parser.parse_args()
    
    source_dir = args.source_directory
    if not source_dir:
        print("Source directory not provided, attempting to find the latest one...")
        source_dir = find_latest_collection_dir()
        if not source_dir:
            print("Error: Could not automatically find a collection directory.")
            print("Please ensure 'wordpress_posts' contains collection subdirectories or specify one with -s.")
            exit(1)
        print(f"Found latest collection directory: {source_dir}")

    os.makedirs(args.output_dir, exist_ok=True)
    process_collection_directory(source_dir, args.output_dir)
