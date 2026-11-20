#!/usr/bin/env python3
"""Read-only original-image audit. Diagnostic only; never a dashboard score.

Compare rendered image bytes separately from the original files represented by
Wix/CDN and Payload derivative URLs. Asset identity is established by fetching
both originals and comparing SHA-256, not by matching filenames or legacy IDs.
This does not establish derivative pixel equality, layout, or visual similarity.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from difflib import SequenceMatcher
from email.parser import BytesParser
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from threading import Lock
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from compare_content import parse_page, require_url, target_url, write_report

MAX_BYTES = 20 * 1024 * 1024
METHOD = 'verified-original-asset-diagnostic-v1'


def origin(url):
    p = require_url(url)
    if p.scheme != 'https' or p.port not in (None, 443):
        raise ValueError('https_default_port_required')
    return 'https://' + p.hostname


def wix_original(url):
    try:
        p = require_url(url)
        if origin(url) != 'https://static.wixstatic.com' or not p.path.startswith('/media/'):
            return None
        media_id = unquote(p.path.split('/')[2])
        if not re.fullmatch(r'[A-Za-z0-9_.~-]+', media_id) or media_id in ('.', '..'):
            return None
        suffix = '/'.join(p.path.split('/')[3:])
        if suffix and not suffix.startswith('v1/'):
            return None
        return 'https://static.wixstatic.com/media/' + media_id
    except (ValueError, IndexError):
        return None


def intersection_score(left, right):
    if not left and not right:
        return 1.0
    matches = sum((Counter(x for x in left if x) & Counter(x for x in right if x)).values())
    return 2 * matches / (len(left) + len(right))


class SafeFetcher:
    """Restrict every request and redirect to the explicitly named sites/CDN."""
    def __init__(self, allowed_origins, timeout=30):
        self.allowed = set(allowed_origins)
        self.timeout = timeout
        self.executable = shutil.which('curl')
        if not self.executable:
            raise ValueError('curl_required_for_bounded_public_requests')
        self.requests = 0
        self.bytes_received = 0
        self.counter_lock = Lock()

    def check(self, url):
        if origin(url) not in self.allowed:
            raise ValueError('outside_allowed_origins')

    def __call__(self, url):
        deadline = time.monotonic() + self.timeout
        for _ in range(6):
            self.check(url)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('request_deadline_exceeded')
            p = urlsplit(url)
            encoded = urlunsplit((p.scheme, p.netloc, quote(p.path, safe="/%:@!$&'()*+,;=-._~"),
                                 quote(p.query, safe="=&%/:?@!$'()*+,;=-._~"), ''))
            with self.counter_lock:
                self.requests += 1
            result = subprocess.run([self.executable, '--silent', '--show-error', '--include',
                                     '--max-time', str(remaining), '--max-filesize', str(MAX_BYTES),
                                     '--proto', '=https', '--header', 'Accept-Encoding: identity',
                                     '--user-agent', 'FeverCoach-Original-Asset-Audit/1.0', '--', encoded],
                                    capture_output=True, timeout=remaining + 2)
            if result.returncode:
                raise ValueError('image_audit_transport_failed')
            data = result.stdout
            with self.counter_lock:
                self.bytes_received += len(data)
            while True:
                head, body = data.split(b'\r\n\r\n', 1)
                first = head.splitlines()[0]
                status = int(first.split()[1])
                if 100 <= status < 200 or b'connection established' in first.lower():
                    data = body
                    continue
                headers = BytesParser().parsebytes(head.split(b'\r\n', 1)[1] + b'\r\n\r\n')
                break
            if status in (301, 302, 303, 307, 308):
                url = urljoin(url, headers.get('Location', ''))
                self.check(url)  # Before any redirected network request; curl never auto-follows.
                continue
            if status != 200 or not body or len(body) > MAX_BYTES:
                raise ValueError('invalid_or_oversized_response')
            if headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise ValueError('unexpected_content_encoding')
            return body, headers.get_content_type(), url
        raise ValueError('redirect_limit_exceeded')


class AssetAuditor:
    def __init__(self, cms_base, fetcher):
        self.cms = origin(cms_base)
        if urlsplit(cms_base).path not in ('', '/') or urlsplit(cms_base).query:
            raise ValueError('cms_must_be_an_origin')
        self.fetch = fetcher
        self.image_hash = lru_cache(maxsize=32768)(self._image_hash)
        self.records = lru_cache(maxsize=8192)(self._records)

    def _image_hash(self, url):
        if not url:
            return None
        try:
            body, kind, final = self.fetch(url)
            if origin(final) != origin(url) or not kind.startswith('image/') or not body:
                return None
            return hashlib.sha256(body).hexdigest()
        except Exception:
            return None

    def _records(self, original):
        query = urlencode({'depth': '0', 'limit': '100', 'where[legacy.wixUrl][equals]': original})
        body, kind, final = self.fetch(self.cms + '/api/media?' + query)
        if origin(final) != self.cms or kind != 'application/json':
            raise ValueError('invalid_cms_response')
        data = json.loads(body)
        if data.get('hasNextPage') or not isinstance(data.get('docs'), list):
            raise ValueError('incomplete_cms_media_result')
        return [doc for doc in data['docs'] if doc.get('legacy', {}).get('wixUrl') == original]

    def cms_file(self, value):
        if not isinstance(value, str) or not value or '\\' in value:
            return None
        url = urljoin(self.cms + '/', value)
        try:
            p = require_url(url)
            if (origin(url) != self.cms or not re.fullmatch(r'/api/media/file/[^/]+', p.path)
                    or parse_qsl(p.query, keep_blank_values=True) not in ([], [('prefix', 'media')])
                    or '/' in unquote(p.path[len('/api/media/file/'):])
                    or '\\' in unquote(p.path) or unquote(p.path.rsplit('/', 1)[-1]) in ('.', '..')):
                return None
            return url
        except ValueError:
            return None

    def image_hashes(self, urls):
        # Fetch a URL once, but retain every occurrence in the returned slots.
        unique = list(dict.fromkeys(urls))
        with ThreadPoolExecutor(max_workers=6) as pool:
            hashes = dict(zip(unique, pool.map(self.image_hash, unique)))
        return [hashes[url] for url in urls]

    def audit(self, source, target):
        row = dict(source_url=source, target_url=target, status='error', text_score=0.0,
                   legacy_byte_image_score=0.0, verified_original_asset_score=0.0,
                   legacy_combined_score=0.0, diagnostic_text_asset_score=0.0)
        try:
            pages = []
            for url in (source, target):
                body, kind, final = self.fetch(url)
                if kind not in ('text/html', 'application/xhtml+xml') or origin(final) != origin(url):
                    raise ValueError('invalid_page_response')
                pages.append(parse_page(body, final))
            (old_text, old_images), (new_text, new_images) = pages
            text_score = SequenceMatcher(None, old_text.split(), new_text.split(), autojunk=False).ratio()
            hashes = self.image_hashes(old_images + new_images)
            raw_old, raw_new = hashes[:len(old_images)], hashes[len(old_images):]
            # Keep all candidate slots and multiplicities. No placeholders are dropped.
            # Wix transformations need original/CMS proof. Reusing an old Wix URL
            # on the new page must never count as a migrated original asset.
            verified_old = [('bytes:' + digest) if digest and not wix_original(url) else None
                            for url, digest in zip(old_images, raw_old)]
            verified_new = []
            for url, digest in zip(new_images, raw_new):
                try:
                    hosted_on_target = origin(url) in {origin(target), self.cms}
                except ValueError:
                    hosted_on_target = False
                verified_new.append(('bytes:' + digest) if digest and hosted_on_target else None)
            evidence, media_errors, target_mapping = [], [], {}
            originals = sorted({wix_original(url) for url in old_images} - {None})
            for original in originals:
                source_hash = self.image_hash(original)
                if not source_hash:
                    media_errors.append('source_original_unavailable')
                    continue
                try:
                    records = self.records(original)
                except Exception:
                    media_errors.append('cms_lookup_failed')
                    continue
                for doc in records:
                    cms_url = self.cms_file(doc.get('url'))
                    cms_hash = self.image_hash(cms_url)
                    if not cms_hash or cms_hash != source_hash:
                        media_errors.append('cms_original_missing_or_hash_mismatch')
                        continue
                    displays = {cms_url}
                    displays.update(self.cms_file(size.get('url')) for size in doc.get('sizes', {}).values()
                                    if isinstance(size, dict))
                    displays.discard(None)
                    used = sorted(set(new_images) & displays)
                    if not used:
                        continue
                    token = 'original:' + source_hash
                    for display in used:
                        target_mapping.setdefault(display, set()).add(token)
                    evidence.append(dict(wix_original_url=original, cms_original_url=cms_url,
                                         original_sha256=source_hash, target_display_urls=used))
                    for index, url in enumerate(old_images):
                        # A broken displayed source is not rescued by an available original.
                        if raw_old[index] and wix_original(url) == original:
                            verified_old[index] = token
            for index, url in enumerate(new_images):
                tokens = target_mapping.get(url, set())
                if len(tokens) > 1:
                    verified_new[index] = None
                    media_errors.append('ambiguous_target_mapping')
                elif len(tokens) == 1 and raw_new[index]:
                    verified_new[index] = next(iter(tokens))
            byte_score = intersection_score(raw_old, raw_new)
            asset_score = intersection_score(verified_old, verified_new)
            has_images = bool(old_images or new_images)
            row.update(status='ok', text_score=text_score, legacy_byte_image_score=byte_score,
                       verified_original_asset_score=asset_score,
                       legacy_combined_score=(text_score + byte_score) / 2 if has_images else text_score,
                       diagnostic_text_asset_score=(text_score + asset_score) / 2 if has_images else text_score,
                       source_image_slots=len(old_images), target_image_slots=len(new_images),
                       source_unresolved_slots=sum(x is None for x in verified_old),
                       target_unresolved_slots=sum(x is None for x in verified_new),
                       verified_original_pairs=evidence, media_errors=media_errors)
        except Exception as error:
            row['error'] = type(error).__name__
        return row


def summarize_page_types(rows):
    """Group the original rows without dropping errors or regrouping redirects by destination."""
    groups = {kind: {'urls': 0, 'errors': 0, 'score_sum': 0.0}
              for kind in ('home', 'articles', 'other')}
    for row in rows:
        parts = urlsplit(row['source_url']).path.strip('/').split('/')
        if parts[0] in ('en', 'es', 'ko', 'fr', 'vi', 'zh'):
            parts = parts[1:]
        if not any(parts):
            kind = 'home'
        elif len(parts) >= 2 and parts[0] == 'post':
            kind = 'articles'
        else:
            kind = 'other'
        group = groups[kind]
        group['urls'] += 1
        group['errors'] += row['status'] == 'error'
        group['score_sum'] += row['diagnostic_text_asset_score']
    return groups


def make_report(rows):
    if not rows or len({r['source_url'] for r in rows}) != len(rows):
        raise ValueError('nonempty_unique_inventory_required')
    return dict(status='diagnostic_only', method=METHOD,
                generated_at=datetime.now(timezone.utc).isoformat(),
                accepted_dashboard_metric=False, total_urls=len(rows), results=rows,
                by_page_type=summarize_page_types(rows),
                legacy_percentage=100 * sum(r['legacy_combined_score'] for r in rows) / len(rows),
                diagnostic_text_asset_percentage=100 * sum(r['diagnostic_text_asset_score'] for r in rows) / len(rows),
                limitation='Original bytes and live image responses verified; derivative pixels, placement and layout are NOT compared. Explicit input URLs only; not a full-site result.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--urls', required=True, help='JSON list of explicit source URLs')
    parser.add_argument('--source-origin', required=True)
    parser.add_argument('--target-origin', required=True)
    parser.add_argument('--cms-origin', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    urls = json.loads(Path(args.urls).read_text(encoding='utf-8'))
    if not isinstance(urls, list) or not urls or any(origin(u) != origin(args.source_origin) for u in urls):
        parser.error('Expected nonempty URLs from the specified source origin')
    fetcher = SafeFetcher({origin(args.source_origin), origin(args.target_origin), origin(args.cms_origin),
                           'https://static.wixstatic.com'})
    auditor = AssetAuditor(args.cms_origin, fetcher)
    rows = []
    for index, url in enumerate(urls, 1):
        print(json.dumps({'starting': index, 'total': len(urls), 'requests': fetcher.requests}), flush=True)
        row = auditor.audit(url, target_url(url, args.target_origin))
        rows.append(row)
        print(json.dumps({'completed': index, 'total': len(urls), 'status': row['status']}), flush=True)
    report = make_report(rows)
    report['transport'] = {'requests': fetcher.requests, 'bytes_received': fetcher.bytes_received,
                           'per_request_total_timeout_seconds': fetcher.timeout}
    write_report(args.output, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'results'}), flush=True)


if __name__ == '__main__':
    main()
