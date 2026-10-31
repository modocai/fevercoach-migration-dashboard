/* Public same-origin manifest only. No GitHub credentials or private API calls. */
(() => {
  'use strict';
  if (!['https:', 'http:'].includes(location.protocol)) return;
  const current = document.querySelector('meta[name="dashboard-version"]')?.content;
  const notice = document.getElementById('auto-update-status');
  if (!/^[a-f0-9]{64}$/.test(current || '') || !notice) return;
  const key = 'dashboard-view-v1';
  const filters = new Set(['open', 'all', 'todo', 'doing', 'done', 'blocked', 'unknown', 'excluded']);
  let busy = false;
  let highest = Number(document.querySelector('meta[name="dashboard-generation"]')?.content) || 0;
  let attempted = null;
  const say = text => { notice.textContent = text; notice.hidden = !text; };
  const storage = {
    get() { try { return JSON.parse(sessionStorage.getItem(key)); } catch { return null; } },
    set(value) { try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* query also bounds navigation */ } }
  };
  const saved = storage.get();
  const requested = new URL(location.href).searchParams.get('v');
  if (saved && saved.target === current) {
    if (filters.has(saved.filter)) document.querySelector(`[data-filter="${saved.filter}"]`)?.click();
    if (Array.isArray(saved.open)) {
      saved.open.slice(0, 6).filter(id => /^phase-[0-5]$/.test(id)).forEach(id => {
        const details = document.getElementById(id)?.querySelector('details');
        if (details) details.open = true;
      });
    }
    if (Number.isFinite(saved.scroll) && saved.scroll >= 0) requestAnimationFrame(() => scrollTo(0, Math.min(saved.scroll, document.body.scrollHeight)));
  }
  function valid(value) {
    return value && Object.keys(value).sort().join(',') === 'build_id,degraded,generated_at,generation,last_success_at,revision,schema_version' &&
      value.schema_version === 1 && /^[a-f0-9]{64}$/.test(value.build_id) && /^[a-f0-9]{40}$/.test(value.revision) &&
      Number.isSafeInteger(value.generation) && value.generation > 0 && typeof value.degraded === 'boolean' &&
      typeof value.generated_at === 'string' && Number.isFinite(Date.parse(value.generated_at)) &&
      (value.last_success_at === null || (typeof value.last_success_at === 'string' && Number.isFinite(Date.parse(value.last_success_at))));
  }
  async function check() {
    if (busy || document.visibilityState !== 'visible') return;
    busy = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const url = new URL('manifest.json', location.href);
      url.searchParams.set('t', String(Date.now()));
      const response = await fetch(url, {cache: 'no-store', credentials: 'omit', redirect: 'error', signal: controller.signal});
      if (!response.ok) throw new Error();
      // Stream-bound the response, including when Content-Length is absent.
      const reader = response.body.getReader();
      let bytes = 0;
      const chunks = [];
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        bytes += value.byteLength;
        if (bytes > 4096) { await reader.cancel(); throw new Error(); }
        chunks.push(value);
      }
      const raw = new Uint8Array(bytes);
      let offset = 0;
      chunks.forEach(chunk => { raw.set(chunk, offset); offset += chunk.byteLength; });
      const value = JSON.parse(new TextDecoder().decode(raw));
      if (!valid(value) || value.generation < highest) throw new Error();
      highest = value.generation;
      const stale = value.last_success_at === null || Date.now() - Date.parse(value.last_success_at) > 45 * 60 * 1000;
      say(value.degraded ? '일부 자료를 갱신하지 못해 마지막 확인값을 표시하고 있습니다.' :
        stale ? '마지막 자료 확인 후 45분이 지났습니다. 수집 작업 상태를 확인해 주세요.' : '');
      if (value.build_id === current) return;
      if (attempted === value.build_id || requested === value.build_id) {
        say('새 자료가 있습니다. 배포 캐시가 갱신된 뒤 페이지를 다시 열어 주세요.');
        return;
      }
      attempted = value.build_id;
      storage.set({target: value.build_id,
        filter: document.querySelector('[data-filter][aria-pressed="true"]')?.dataset.filter || 'all',
        open: [...document.querySelectorAll('.phase')].filter(p => p.querySelector('details')?.open).map(p => p.id),
        scroll: scrollY});
      const destination = new URL(location.href);
      destination.searchParams.set('v', value.build_id);
      location.replace(destination.href);
    } catch {
      say('자동 갱신을 확인하지 못했습니다. 현재 표시된 자료는 그대로 유지됩니다.');
    } finally {
      clearTimeout(timeout);
      busy = false;
    }
  }
  check();
  setInterval(check, 60000);
  addEventListener('focus', check);
  document.addEventListener('visibilitychange', check);
})();
