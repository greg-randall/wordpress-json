# WordPress News Collector & Normalizer

This project contains two Python scripts for collecting and normalizing news articles from WordPress websites that have the REST API enabled.

## 1. `collect_news.py`

This script fetches recent posts from a list of WordPress domains.

### What it does
- Reads a list of domains from a text file.
- For each domain, it queries the `/wp-json/wp/v2/posts` endpoint to get posts published within a specified number of hours.
- Saves the raw JSON response for each domain into a timestamped directory.

### Usage
```bash
python collect_news.py [--domains-file domains.txt] [--hours 48]
```
- `--domains-file`: Path to a text file containing one domain per line. Defaults to `wordpress.txt`.
- `--hours`: How many hours back to fetch posts from. Defaults to 48.

### Output
The script creates a directory structure like this, containing the raw JSON from the API:
```
wordpress_posts/
└── YYYY-MM-DD/
    └── TIMESTAMP/
        ├── example_com.json
        ├── anothernews_org.json
        └── _collection_summary.json
```

## 2. `normalize_news.py`

This script processes the raw data collected by `collect_news.py` and transforms it into a standardized format.

### What it does
- Finds the most recent collection directory created by `collect_news.py`.
- Parses the raw JSON files.
- Converts each article into a standard JSON format, converting HTML content to Markdown.
- Saves each normalized article as a separate JSON file, named with an MD5 hash of the article's URL for deduplication.

### Usage
By default, the script finds the latest collection and processes it:
```bash
python normalize_news.py
```
You can also specify a source directory:
```bash
python normalize_news.py --source-directory wordpress_posts/YYYY-MM-DD/TIMESTAMP
```

### Output
Normalized articles are saved in the `../normalized_news/` directory (or the directory specified by `--output-dir`), organized by domain:
```
normalized_news/
├── example.com/
│   ├── a1b2c3d4e5f6g7h8i9j0.json
│   └── f9e8d7c6b5a4g3h2i1j0.json
└── anothernews.org/
    └── 1234567890abcdef1234.json
```

## Data Standard

The schema for the normalized JSON files is defined in `normalized_news_standard.md`. This standard ensures consistency across different news sources.
