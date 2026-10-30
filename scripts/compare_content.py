#!/usr/bin/env python3
"""Compare every public sitemap URL with the same path on a target deployment.

Uses server-rendered main/article content, normalized text and image byte hashes.
No JavaScript is executed. A successful run records every source URL, including
failed requests; an incomplete sitemap inventory never replaces the last report.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

MAX_BYTES = 20 * 1024 * 1024
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
EXCLUDED = {'script', 'style', 'noscript', 'template', 'nav', 'header', 'footer', 'svg'}
TEXT_BOUNDARIES = {'address', 'article', 'aside', 'blockquote', 'body', 'br', 'caption',
                   'dd', 'details', 'dialog', 'div', 'dl', 'dt', 'fieldset', 'figcaption',
                   'figure', 'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'legend',
                   'li', 'main', 'ol', 'p', 'pre', 'section', 'summary', 'table', 'tbody',
                   'td', 'tfoot', 'th', 'thead', 'tr', 'ul'}


def srcset_urls(value):
    """Collect every candidate without treating commas inside URLs as separators.

    Follow the srcset URL/descriptor token boundaries. Unsupported descriptors
    produce an unresolved image slot rather than silently earning a full match.
    Data URLs are kept intact; the HTTP-only fetcher conservatively fails them.
    """
    candidates = []
    position = 0
    while position < len(value):
        while position < len(value) and (value[position].isspace() or value[position] == ','):
            position += 1
        if position == len(value):
            break
        start = position
        while position < len(value) and not value[position].isspace():
            position += 1
        url = value[start:position]
        if url.endswith(','):
            candidates.append(url.rstrip(',') or '')
            continue
        start = position
        parentheses = 0
        while position < len(value):
            char = value[position]
            if char == ',' and parentheses == 0:
                break
            if char == '(':
                parentheses += 1
            elif char == ')' and parentheses:
                parentheses -= 1
            position += 1
        descriptors = value[start:position].split()
        position += 1
        valid = not descriptors or (len(descriptors) == 1 and bool(
            re.fullmatch(r'(?:[1-9][0-9]*w|(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)x)', descriptors[0])))
        candidates.append(url if valid else '')
    return candidates


def image_candidates(attrs, source=False):
    candidates = []
    if not source:
        candidates.extend(attrs[key] for key in ('src', 'data-src') if attrs.get(key))
    for key in ('srcset', 'data-srcset'):
        if attrs.get(key):
            candidates.extend(srcset_urls(attrs[key]))
    # Count a URL once per element while preserving repeated images on the page.
    return list(dict.fromkeys(candidates)) or ['']


def require_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError('Expected an HTTP(S) URL without credentials or fragment')
    return parts


def fetch(url, timeout=20):
    require_url(url)
    request = Request(url, headers={'User-Agent': 'FeverCoach-Migration-Comparison/1.0'})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f'http_{response.status}')
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError('response_too_large')
        return body, response.headers.get_content_type(), response.geturl()


def sitemap_urls(sitemap, fetcher=fetch):
    """Fail closed on unreadable children; never silently shrink the denominator."""
    host = require_url(sitemap).hostname
    pending, visited, pages = [sitemap], set(), set()
    while pending:
        url = pending.pop()
        if url in visited:
            continue
        if len(visited) >= 1000:
            raise ValueError('sitemap_limit_exceeded')
        visited.add(url)
        body, _, final_url = fetcher(url)
        if require_url(final_url).hostname != host:
            raise ValueError('sitemap_redirect_outside_source')
        root = ET.fromstring(body)
        kind = root.tag.rsplit('}', 1)[-1]
        if kind not in ('sitemapindex', 'urlset'):
            raise ValueError('invalid_sitemap_root')
        item_name = 'sitemap' if kind == 'sitemapindex' else 'url'
        for item in root:
            if item.tag.rsplit('}', 1)[-1] != item_name:
                continue
            locations = [child.text.strip() for child in item
                         if child.tag.rsplit('}', 1)[-1] == 'loc' and child.text]
            if len(locations) != 1:
                raise ValueError('missing_or_duplicate_sitemap_location')
            location = locations[0]
            if require_url(location).hostname != host:
                raise ValueError('sitemap_location_outside_source')
            if kind == 'sitemapindex':
                pending.append(location)
            else:
                pages.add(location)
    if not pages:
        raise ValueError('empty_sitemap_inventory')
    return sorted(pages)


class ContentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.text = {key: [] for key in ('body', 'main', 'article')}
        self.images = {key: [] for key in self.text}
        self.seen = set()
        self.title = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        excluded = (tag in EXCLUDED or 'hidden' in attrs or attrs.get('aria-hidden') == 'true'
                    or bool(re.search(r'(display\s*:\s*none|visibility\s*:\s*hidden)', attrs.get('style', ''), re.I)))
        self.stack.append((tag, excluded))
        if not self.is_excluded():
            self.seen.update({tag} & {'body', 'main', 'article'})
            if tag in TEXT_BOUNDARIES:
                self.text_boundary()
            if tag == 'img' or (tag == 'source' and any(parent == 'picture' for parent, _ in self.stack)):
                # Missing/inline image sources remain failures, never silently disappear.
                for scope in self.scopes():
                    self.images[scope].extend(image_candidates(attrs, source=tag == 'source'))
        if tag in VOID:
            self.stack.pop()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in TEXT_BOUNDARIES and not self.is_excluded():
            self.text_boundary()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def is_excluded(self):
        return any(excluded for _, excluded in self.stack)

    def scopes(self):
        tags = {tag for tag, _ in self.stack}
        return tags & self.text.keys()

    def text_boundary(self):
        for scope in self.scopes():
            self.text[scope].append(' ')

    def handle_data(self, data):
        if any(tag == 'title' for tag, _ in self.stack):
            self.title.append(data)
        if not self.is_excluded():
            for scope in self.scopes():
                self.text[scope].append(data)

    def result(self, url):
        scope = next((key for key in ('article', 'main', 'body') if key in self.seen), 'body')
        text = ' '.join(unicodedata.normalize('NFC', ''.join(self.text[scope])).split())
        title = ' '.join(self.title).lower()
        if re.search(r'\b404\b|page not found|페이지를 찾을 수 없', title):
            raise ValueError('soft_404')
        if not text:
            raise ValueError('empty_content')
        return text, [urljoin(url, src) if src else '' for src in self.images[scope]]


def parse_page(body, url):
    parser = ContentParser()
    parser.feed(body.decode('utf-8', errors='replace'))
    return parser.result(url)


def target_url(source_url, target_base_url):
    source, target = require_url(source_url), require_url(target_base_url)
    if target.path not in ('', '/') or target.query:
        raise ValueError('target_must_be_an_origin')
    def origin(parts):
        return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80)
    if origin(source) == origin(target):
        raise ValueError('source_and_target_must_be_different_origins')
    return urlunsplit((target.scheme, target.netloc, source.path or '/', source.query, ''))


def preflight_target(target_base_url, fetcher=fetch):
    """Reject unavailable deployments before replacing a prior measured report."""
    parts = require_url(target_base_url)
    if parts.path not in ('', '/') or parts.query:
        raise ValueError('target_must_be_an_origin')
    root = urlunsplit((parts.scheme, parts.netloc, '/', '', ''))
    body, kind, final = fetcher(root)
    if kind not in ('text/html', 'application/xhtml+xml'):
        raise ValueError('target_preflight_not_html')
    if require_url(final).hostname != parts.hostname:
        raise ValueError('target_preflight_redirect_outside_deployment')
    if b'DEPLOYMENT_NOT_FOUND' in body or b'DEPLOYMENT_DISABLED' in body:
        raise ValueError('target_preflight_deployment_unavailable')
    parse_page(body, final)


class Comparator:
    def __init__(self, fetcher=fetch):
        self.fetcher = fetcher
        self.image_hash = lru_cache(maxsize=32768)(self._image_hash)

    def _image_hash(self, url):
        try:
            body, kind, _ = self.fetcher(url)
            if not kind.startswith('image/') or not body:
                return None
            return hashlib.sha256(body).hexdigest()
        except Exception:
            return None

    def compare(self, source, target):
        row = dict(source_url=source, target_url=target, status='error', score=0.0,
                   text_score=0.0, image_score=0.0)
        try:
            # Check the destination first: known missing pages need no source/image requests.
            new_body, kind, final = self.fetcher(target)
            if kind not in ('text/html', 'application/xhtml+xml'):
                raise ValueError('target_not_html')
            if require_url(final).hostname != require_url(target).hostname:
                raise ValueError('target_redirect_outside_deployment')
            new_text, new_images = parse_page(new_body, final)
            old_body, kind, final = self.fetcher(source)
            if kind not in ('text/html', 'application/xhtml+xml'):
                raise ValueError('source_not_html')
            if require_url(final).hostname != require_url(source).hostname:
                raise ValueError('source_redirect_outside_site')
            old_text, old_images = parse_page(old_body, final)
            text_score = SequenceMatcher(None, old_text.split(), new_text.split(), autojunk=False).ratio()
            if old_images or new_images:
                old_hashes = [self.image_hash(url) for url in old_images]
                new_hashes = [self.image_hash(url) for url in new_images]
                matched = sum((Counter(x for x in old_hashes if x) & Counter(x for x in new_hashes if x)).values())
                image_score = 2 * matched / (len(old_images) + len(new_images))
                score = (text_score + image_score) / 2
            else:
                image_score, score = 1.0, text_score
            row.update(status='ok', score=score, text_score=text_score, image_score=image_score)
        except Exception as error:
            # Persist only an error type/code; raw network exceptions can expose credentials.
            row['error'] = str(error) if isinstance(error, ValueError) else type(error).__name__
        return row


def compare_inventory(urls, target_base_url, source_sitemap, fetcher=fetch, workers=6):
    if not urls or len(urls) != len(set(urls)):
        raise ValueError('inventory_must_be_nonempty_and_unique')
    targets = [target_url(url, target_base_url) for url in urls]
    if len(targets) != len(set(targets)):
        raise ValueError('target_mapping_must_be_one_to_one')
    comparator = Comparator(fetcher)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(comparator.compare, urls, targets))
    score_sum = sum(row['score'] for row in results)
    return dict(status='measured', generated_at=datetime.now(timezone.utc).isoformat(),
                source_sitemap=source_sitemap, target_base_url=target_base_url,
                total_urls=len(urls), results=results, score_sum=score_sum,
                percentage=100 * score_sum / len(urls))


def write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', delete=False) as handle:
            temporary = handle.name
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-sitemap', required=True)
    parser.add_argument('--target-base-url', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--timeout', type=float, default=20)
    args = parser.parse_args()
    if not 1 <= args.workers <= 16 or not 0 < args.timeout <= 120:
        parser.error('workers must be 1–16 and timeout must be >0 and <=120')
    target_url(args.source_sitemap, args.target_base_url)
    fetcher = lambda url: fetch(url, args.timeout)
    preflight_target(args.target_base_url, fetcher)
    urls = sitemap_urls(args.source_sitemap, fetcher)
    print(f'Comparing all {len(urls)} source URLs against {args.target_base_url}', flush=True)
    report = compare_inventory(urls, args.target_base_url, args.source_sitemap, fetcher, args.workers)
    write_report(args.output, report)
    errors = sum(row['status'] == 'error' for row in report['results'])
    print(f'{report["percentage"]:.2f}% · {len(urls)} pages · {errors} errors (scored zero)')


if __name__ == '__main__':
    main()
