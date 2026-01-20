#!/usr/bin/env python3
"""
Convert Sarah's book lists to Goodreads-compatible CSV (V2).

Improvements over V1:
- Smart local title/author parsing
- Separate title+author API search
- Match validation with confidence scoring
- Distributed dates throughout each year
- Preserves original data
- Separate output for low-confidence matches
"""

import os
import re
import csv
import json
import time
import urllib.request
import urllib.parse
from datetime import date, timedelta
from pathlib import Path
from docx import Document
from difflib import SequenceMatcher

# Paths
SCRIPT_DIR = Path(__file__).parent
KNOWN_AUTHORS_FILE = SCRIPT_DIR / 'known_authors.json'
CACHE_FILE = SCRIPT_DIR / 'book_cache_v2.json'
OUTPUT_CSV = SCRIPT_DIR / 'goodreads_import.csv'
REVIEW_CSV = SCRIPT_DIR / 'needs_review.csv'

# Bad patterns to reject
BAD_TITLE_PATTERNS = ['study guide', 'summary', 'sparknotes', 'cliffsnotes', 'bookcaps']
BAD_AUTHORS = {'SuperSummary', 'BookCaps', 'SparkNotes', 'CliffsNotes', ''}


def load_known_authors():
    """Load known good author names from previous successful matches."""
    if KNOWN_AUTHORS_FILE.exists():
        with open(KNOWN_AUTHORS_FILE) as f:
            return set(json.load(f))
    return set()


def load_cache():
    """Load the API cache."""
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    """Save the API cache."""
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)


def similarity(a, b):
    """Calculate string similarity ratio (0-1)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def parse_title_author(raw, known_authors):
    """
    Parse a combined 'Title Author' string into separate components.
    Uses known authors list for better accuracy.
    """
    text = raw.strip()

    # Normalize dashes
    text = text.replace('—', '-').replace('–', '-')

    # Pattern 1: "Title-Author" (dash with no spaces around it, at word boundary)
    # e.g., "No one will find you-Rachel woods"
    if re.search(r'\w-[A-Z]', text):
        parts = re.split(r'-(?=[A-Z])', text, maxsplit=1)
        if len(parts) == 2:
            potential_author = parts[1].strip()
            if len(potential_author.split()) <= 4:
                return parts[0].strip(), potential_author

    # Pattern 2: "Title by Author"
    if ' by ' in text.lower():
        idx = text.lower().rfind(' by ')
        return text[:idx].strip(), text[idx+4:].strip()

    # Pattern 3: Check if any known author appears at the end
    text_lower = text.lower()
    for author in known_authors:
        if text_lower.endswith(author.lower()):
            title = text[:-(len(author))].strip()
            if title:  # Make sure we have a title left
                return title, author

    # Pattern 4: Heuristic - author is last N capitalized words
    words = text.split()

    # Try 3-word author, then 2-word
    for author_len in [3, 2]:
        if len(words) <= author_len:
            continue

        potential_author_words = words[-author_len:]
        potential_title_words = words[:-author_len]

        # Check if author words look like names (capitalized or known pattern)
        looks_like_author = all(
            w[0].isupper() or w.lower() in ['de', 'van', 'von', 'la', 'le']
            for w in potential_author_words if w
        )

        if looks_like_author:
            return ' '.join(potential_title_words), ' '.join(potential_author_words)

    # Fallback: assume last 2 words are author
    if len(words) > 2:
        return ' '.join(words[:-2]), ' '.join(words[-2:])

    # Can't parse - return whole thing as title
    return text, ""


def _do_openlibrary_search(params):
    """Execute a single Open Library search."""
    query_string = urllib.parse.urlencode(params)
    url = f"https://openlibrary.org/search.json?{query_string}&fields=title,author_name,isbn,first_publish_year"

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'BookListConverter/2.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())

            if not data.get('docs'):
                return {'found': False}

            doc = data['docs'][0]
            isbns = doc.get('isbn', [])
            isbn13, isbn10 = '', ''
            for isbn in isbns:
                if len(isbn) == 13 and isbn.startswith(('978', '979')):
                    isbn13 = isbn
                    break
                elif len(isbn) == 10 and not isbn10:
                    isbn10 = isbn

            return {
                'found': True,
                'title': doc.get('title', ''),
                'author': doc.get('author_name', [''])[0] if doc.get('author_name') else '',
                'isbn13': isbn13,
                'isbn': isbn10,
                'year': doc.get('first_publish_year', ''),
            }
    except Exception as e:
        return {'found': False, 'error': str(e)}


def search_openlibrary(title, author, original_raw, cache):
    """
    Search Open Library with multiple fallback strategies:
    1. Separate title + author fields
    2. Title only
    3. Combined query string (like V1)
    """
    cache_key = f"v2|{title.lower()}|{author.lower()}"
    if cache_key in cache:
        return cache[cache_key]

    # Strategy 1: Separate fields (most precise)
    params = {'limit': '3'}
    if title:
        params['title'] = title
    if author:
        params['author'] = author

    result = _do_openlibrary_search(params)
    time.sleep(0.05)

    if result.get('found'):
        cache[cache_key] = result
        return result

    # Strategy 2: Title only (if author might be wrong)
    if author and title:
        result = _do_openlibrary_search({'title': title, 'limit': '3'})
        time.sleep(0.05)
        if result.get('found'):
            cache[cache_key] = result
            return result

    # Strategy 3: Combined query (like V1, catches typos better)
    result = _do_openlibrary_search({'q': original_raw, 'limit': '3'})
    time.sleep(0.05)
    cache[cache_key] = result
    return result


def validate_match(parsed_title, parsed_author, api_result, original_raw):
    """
    Validate an API match and return a confidence score.
    Returns: (is_valid, confidence, reason)
    """
    if not api_result.get('found'):
        return False, 'none', 'API returned no results'

    api_title = api_result.get('title', '').lower()
    api_author = api_result.get('author', '')

    # Reject bad patterns
    for bad in BAD_TITLE_PATTERNS:
        if bad in api_title:
            return False, 'rejected', f'Bad title pattern: {bad}'

    if api_author in BAD_AUTHORS:
        return False, 'rejected', f'Bad author: {api_author}'

    # Calculate confidence score
    score = 0
    reasons = []

    # Title similarity (max 40 points)
    title_sim = similarity(parsed_title, api_result.get('title', ''))
    if title_sim > 0.8:
        score += 40
        reasons.append(f'title_match:{title_sim:.0%}')
    elif title_sim > 0.5:
        score += 20
        reasons.append(f'title_partial:{title_sim:.0%}')

    # Author match (max 40 points)
    if parsed_author and api_author:
        author_sim = similarity(parsed_author, api_author)
        if author_sim > 0.8:
            score += 40
            reasons.append(f'author_match:{author_sim:.0%}')
        elif author_sim > 0.5:
            score += 20
            reasons.append(f'author_partial:{author_sim:.0%}')
        # Also check if API author appears in original
        elif api_author.lower() in original_raw.lower():
            score += 30
            reasons.append('author_in_original')

    # Has ISBN (max 20 points)
    if api_result.get('isbn13') or api_result.get('isbn'):
        score += 20
        reasons.append('has_isbn')

    # Determine confidence level
    if score >= 80:
        confidence = 'high'
    elif score >= 50:
        confidence = 'medium'
    else:
        confidence = 'low'

    return True, confidence, f"score:{score} ({', '.join(reasons)})"


def calculate_read_date(book_number, total_books, year):
    """
    Distribute books evenly throughout the year.
    Book 1 -> early January, Last book -> late December
    """
    if total_books <= 1:
        return date(int(year), 6, 15)  # Middle of year

    # Spread across days 1-365
    day_of_year = int(((book_number - 1) / (total_books - 1)) * 364) + 1
    return date(int(year), 1, 1) + timedelta(days=day_of_year - 1)


def parse_books_from_docx():
    """Parse all numbered book entries from docx files."""
    books = []

    for fname in sorted(os.listdir(SCRIPT_DIR)):
        if not fname.endswith('.docx'):
            continue

        year_match = re.search(r'20\d{2}', fname)
        year = year_match.group() if year_match else 'unknown'

        doc = Document(SCRIPT_DIR / fname)

        year_books = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            # Match: "1-Title Author" or "Jan1-Title Author" or "May41-Title"
            match = re.match(r'^(?:[A-Za-z]*)?(\d+)[-.]\s*(.+)$', text)
            if match:
                year_books.append({
                    'num': int(match.group(1)),
                    'raw': match.group(2).strip()
                })

        # Sort by number and add year info
        year_books.sort(key=lambda x: x['num'])
        total = len(year_books)

        for i, book in enumerate(year_books):
            book['year'] = year
            book['total_in_year'] = total
            book['position'] = i + 1
            books.append(book)

    return books


def main():
    print("=" * 60)
    print("Book List to Goodreads CSV Converter (V2)")
    print("=" * 60)

    # Load resources
    print("\nLoading resources...")
    known_authors = load_known_authors()
    print(f"  Known authors: {len(known_authors)}")

    cache = load_cache()
    print(f"  Cache entries: {len(cache)}")

    # Parse books
    print("\nParsing docx files...")
    books = parse_books_from_docx()
    print(f"  Found {len(books)} books")

    # Process each book
    print("\nProcessing books...")
    results = []
    stats = {'high': 0, 'medium': 0, 'low': 0, 'rejected': 0, 'none': 0}

    for i, book in enumerate(books):
        if i % 100 == 0:
            print(f"  {i}/{len(books)}...")
            save_cache(cache)

        # Parse title/author locally
        parsed_title, parsed_author = parse_title_author(book['raw'], known_authors)

        # Search API (with fallback strategies)
        api_result = search_openlibrary(parsed_title, parsed_author, book['raw'], cache)

        # Validate match
        is_valid, confidence, reason = validate_match(
            parsed_title, parsed_author, api_result, book['raw']
        )

        stats[confidence] += 1

        # Calculate read date
        read_date = calculate_read_date(
            book['position'],
            book['total_in_year'],
            book['year']
        )

        # Build result
        result = {
            'original': book['raw'],
            'year': book['year'],
            'read_date': read_date.strftime('%Y/%m/%d'),
            'parsed_title': parsed_title,
            'parsed_author': parsed_author,
            'confidence': confidence,
            'reason': reason,
        }

        # Use API data if valid, otherwise use parsed
        if is_valid and confidence in ('high', 'medium'):
            result['title'] = api_result.get('title', parsed_title)
            result['author'] = api_result.get('author', parsed_author)
            result['isbn13'] = api_result.get('isbn13', '')
            result['isbn'] = api_result.get('isbn', '')
            result['year_published'] = api_result.get('year', '')
        else:
            result['title'] = parsed_title
            result['author'] = parsed_author
            result['isbn13'] = ''
            result['isbn'] = ''
            result['year_published'] = ''

        results.append(result)

    save_cache(cache)

    # Print stats
    print(f"\n{'=' * 60}")
    print("RESULTS SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total books: {len(results)}")
    print(f"High confidence: {stats['high']} ({stats['high']*100//len(results)}%)")
    print(f"Medium confidence: {stats['medium']} ({stats['medium']*100//len(results)}%)")
    print(f"Low confidence: {stats['low']} ({stats['low']*100//len(results)}%)")
    print(f"Rejected (bad match): {stats['rejected']}")
    print(f"No results: {stats['none']}")

    # Separate high/medium from low
    ready = [r for r in results if r['confidence'] in ('high', 'medium')]
    needs_review = [r for r in results if r['confidence'] not in ('high', 'medium')]

    # Write main CSV (Goodreads format)
    print(f"\nWriting {OUTPUT_CSV}...")
    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Title', 'Author', 'ISBN', 'ISBN13', 'My Rating',
            'Date Read', 'Date Added', 'Bookshelves', 'Exclusive Shelf',
            'Original Entry'  # Extra column for reference
        ])

        for r in ready:
            writer.writerow([
                r['title'],
                r['author'],
                r['isbn'],
                r['isbn13'],
                '',  # My Rating
                r['read_date'],
                r['read_date'],
                'read',
                'read',
                r['original']
            ])

    print(f"  Wrote {len(ready)} books ready to import")

    # Write review CSV
    print(f"\nWriting {REVIEW_CSV}...")
    with open(REVIEW_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Original Entry', 'Parsed Title', 'Parsed Author',
            'Year Read', 'Date Read', 'Confidence', 'Reason'
        ])

        for r in needs_review:
            writer.writerow([
                r['original'],
                r['parsed_title'],
                r['parsed_author'],
                r['year'],
                r['read_date'],
                r['confidence'],
                r['reason']
            ])

    print(f"  Wrote {len(needs_review)} books needing review")

    print(f"\n{'=' * 60}")
    print("DONE!")
    print(f"{'=' * 60}")
    print(f"\nFiles created:")
    print(f"  {OUTPUT_CSV} - Import this to Goodreads")
    print(f"  {REVIEW_CSV} - Sarah should review these manually")


if __name__ == '__main__':
    main()
