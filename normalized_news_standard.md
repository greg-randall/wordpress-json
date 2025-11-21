# Normalized News Data Standard

This document defines the standardized format for normalized news articles across all scrapers.

## Purpose

All news scrapers should normalize their output to this standard format to enable:
- Consistent data processing across different news sources
- Easy aggregation and analysis of articles from multiple sources
- Interoperability between different parts of the system

## Standard Fields

Each normalized article MUST be a JSON object containing the following fields:

### Required Fields

These fields MUST be present in every normalized article:

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Full URL to the original article |
| `title` | string | Article headline/title |
| `article_text` | string | Full article text in **Markdown format** |
| `source_domain` | string | Source website domain (e.g., "example.com") |
| `first_seen_timestamp_gmt` | integer | Unix timestamp (GMT/UTC) when this article was first scraped/discovered |

### Strongly Recommended Fields

These fields should be included whenever possible:

| Field | Type | Description |
|-------|------|-------------|
| `publication_date` | string or null | Original publication date in source format (ISO8601 or RFC2822 preferred) |
| `publication_timestamp_gmt` | integer or null | Unix timestamp (seconds since epoch) in GMT/UTC |
| `author` | string or null | Article author(s) - comma-separated if multiple |
| `keywords` | array of strings | Article keywords, tags, categories, or sections - map all available taxonomy to this field |

### Optional Fields

These fields MAY be included if available from the source:

| Field | Type | Description |
|-------|------|-------------|
| `image_url` | string | URL to featured/header image |
| `excerpt` | string | Short excerpt or summary |
| `word_count` | integer | Article word count |
| `metadata` | object | Any source-specific fields that don't fit the standard schema |

## Field Requirements

### URL
- Must be a valid, absolute URL
- Should point directly to the article page

### Title
- Must be non-empty
- Should be the main headline, not subheadings

### Publication Date & Timestamp
- `publication_date`: Keep original format from source for reference
- `publication_timestamp_gmt`: Convert to Unix timestamp (seconds, not milliseconds)
- If conversion fails, `publication_timestamp_gmt` should be `null`
- Timestamps MUST be in GMT/UTC (not local time)

### Author
- Can be `null` if author is unknown or not specified
- If multiple authors, use comma-separated string: "Author One, Author Two"

### Article Text
- **MUST be in Markdown format**
- HTML entities MUST be decoded (e.g., `&lt;` → `<`)
- HTML tags MUST be converted to Markdown equivalents:
  - `<h1>` → `# `
  - `<h2>` → `## `
  - `<a href="">` → `[text](url)`
  - `<p>` → paragraphs separated by blank lines
  - `<strong>` or `<b>` → `**bold**`
  - `<em>` or `<i>` → `*italic*`
- Should include full article content, not truncated
- May include multiple paragraphs separated by blank lines

### Source Domain
- Should be the bare domain without protocol
- Example: "nytimes.com" not "https://www.nytimes.com"

### Keywords
- Map ALL available taxonomy to this single field:
  - WordPress: categories + tags
  - TownNews: keywords + sections
  - Custom CMS: any category/tag/topic fields
- Helps with aggregation and analysis across different sources
- Better to have duplicate/overlapping terms than to miss taxonomy

### First Seen Timestamp
- **MUST be in GMT/UTC** (not local time)
- Records when the scraper first discovered this article
- Use the timestamp at the start of the scrape run, not per-article
- Useful for:
  - Detecting publication date changes or back-filling
  - Deduplication across multiple scrape runs
  - Understanding data freshness and collection timing
- Should remain constant if article is re-scraped (use existing value if updating)

## Data Format

### File Structure
Normalized data should be stored as **individual JSON files, one per article**, organized in domain subdirectories:

```
normalized_news/
  example.com/
    a1b2c3d4e5f6g7h8i9j0.json  (MD5 hash of article URL)
    f9e8d7c6b5a4g3h2i1j0.json
    ...
  anothernews.org/
    1234567890abcdef1234.json
    ...
```

Each article file contains a single JSON object:

```json
{
  "url": "https://example.com/article1",
  "title": "Article Title",
  "article_text": "## Breaking News\n\nThis is the article content in **Markdown** format.\n\nSecond paragraph with a [link](https://example.com).",
  "source_domain": "example.com",
  "publication_date": "2025-11-20T14:30:00-06:00",
  "publication_timestamp_gmt": 1732132200,
  "first_seen_timestamp_gmt": 1732140000,
  "author": "Jane Doe",
  "keywords": ["politics", "local news", "breaking news", "national"]
}
```

### File Naming Convention
Each article file should be named using the **MD5 hash of its URL**:
```
{md5_hash_of_url}.json
```

**Rationale:**
- URL-based naming ensures natural deduplication (same URL = same file)
- MD5 hashing creates valid, collision-resistant filenames
- Portable across different news sources (not dependent on source-specific IDs)
- Enables efficient skip-if-exists checking for incremental scraping

**Example:**
```python
import hashlib
url = "https://example.com/article1"
filename = hashlib.md5(url.encode('utf-8')).hexdigest() + ".json"
# Result: "a1b2c3d4e5f6g7h8i9j0.json"
```

### Directory Structure
- **One directory per source domain** (e.g., `example.com/`, `news.org/`)
- Domain names should match the `source_domain` field
- Directories created automatically as needed during normalization

## Summary File

Each normalization run should produce a summary file named `_normalization_summary.json` in the **raw data timestamp directory** (not in the normalized_news directory):

```
raw_news_data/
  2025-11-20/
    1763657957/
      example_com.json
      _collection_summary.json
      _normalization_summary.json  ← Summary goes here
```

Summary format:

```json
{
  "timestamp": "2025-11-20T14:30:00.123456",
  "source": "townnews",
  "statistics": {
    "files_processed": 35,
    "articles_new": 1525,
    "articles_skipped": 0,
    "articles_skipped_image_type": 1975,
    "errors": 0
  }
}
```

**Statistics fields:**
- `files_processed`: Number of raw data files processed
- `articles_new`: New articles normalized and written
- `articles_skipped`: Articles already normalized (file exists)
- `articles_skipped_image_type`: Items filtered out (e.g., image-only posts)
- `errors`: Number of errors encountered

## Implementation Notes

### HTML to Markdown Conversion
- Use a library like `markdownify` for Python or similar for other languages
- Ensure fallback handling if library is unavailable
- Test with various HTML structures to ensure proper conversion

### Date/Time Handling
- Always store Unix timestamps as integers (seconds, not milliseconds)
- Calculate timestamps in GMT/UTC timezone
- Preserve original date string for debugging/reference
- Handle timezone conversions properly (source may be in local time)

### Deduplication & Incremental Processing
- **Check if article file exists** before normalizing (by MD5 hash of URL)
- If file exists, skip normalization (don't re-process)
- Track skipped count in statistics
- This enables efficient daily scraping without re-processing existing articles

### Content Filtering
- **Filter out non-article content types** before normalization
- Example filters:
  - TownNews: Skip items with `"type": "image"` (photo galleries, standalone images)
  - WordPress: Skip items with `post_type` other than `"post"`
- Track filtered items separately in statistics
- Reduces storage and focuses dataset on actual news content

### Error Handling
- If a required field cannot be populated, use `null` for nullable fields
- Log errors but continue processing remaining articles
- Track error counts in summary file

### Character Encoding
- Use UTF-8 encoding for all JSON files
- Set `ensure_ascii=False` when writing JSON to preserve Unicode characters
- Properly handle special characters and emoji

## Validation

Scrapers should validate each normalized article has:
1. **Required fields present and non-empty**:
   - `url` (valid URL string)
   - `title` (non-empty string)
   - `article_text` (non-empty string in Markdown format)
   - `source_domain` (non-empty string)
   - `first_seen_timestamp_gmt` (positive integer)

2. **Type validation for optional fields**:
   - If `publication_timestamp_gmt` is not null, it must be a positive integer
   - If `keywords` is present, it must be an array
   - If `author` is present, it must be a string or null

## Version History

- **v3.0** (2025-11-20): Per-article file structure
  - **Changed from array-of-articles to one-file-per-article structure**
  - Files named using MD5 hash of URL for natural deduplication
  - Organized in domain subdirectories (`example.com/`, `news.org/`)
  - Added skip-if-exists logic for efficient incremental scraping
  - Added content type filtering (e.g., skip image-only posts)
  - Normalization summary moved to raw data timestamp directory
  - Statistics now track: `articles_new`, `articles_skipped`, `articles_skipped_image_type`, `errors`

- **v2.1** (2025-11-20): Added first_seen tracking
  - Added `first_seen_timestamp_gmt` as a **required field**
  - Tracks when article was first discovered by scraper
  - Helps with deduplication and detecting publication date changes
  - Required because scraper always knows collection time

- **v2.0** (2025-11-20): Minimalist revision
  - **Required fields reduced to**: url, title, article_text, source_domain (later added first_seen_timestamp_gmt in v2.1)
  - **Strongly recommended**: publication_date, publication_timestamp_gmt, author, keywords
  - Removed `article_type` (too source-specific)
  - Removed `sections` (merged into keywords)
  - Keywords now maps ALL taxonomy (categories, tags, sections, topics)
  - Added `metadata` field for source-specific extras

- **v1.0** (2025-11-20): Initial standard definition
  - Required fields: url, title, publication_date, publication_timestamp_gmt, author, article_text, source_domain, article_type
  - Markdown format for article_text
  - GMT Unix timestamps
