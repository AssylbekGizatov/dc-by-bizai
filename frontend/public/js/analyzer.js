/* Анализ одного обращения. С API — POST /api/tickets (тот же конвейер, что POST /triage; обращение попадает в очередь админа),
 * без API — демо-анализ в браузере. */
(function () {
  'use strict';
  const L = window.SC.logic;
  const $ = (s) => document.querySelector(s);
  let rules = new Map(window.SC.demo.RULES.map((r) => [r.code, r]));
  let mode = 'demo';
  let token = '', authRequired = false, submitting = false;
  const intakeKeys = new Map();

  function h(tag, props) {
    const el = document.createElement(tag);
    if (props) Object.keys(props).forEach((k) => {
      const v = props[k];
      if (v == null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    });
    for (let i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, c) {
    if (c == null || c === false) return;
    if (Array.isArray(c)) { c.forEach((x) => add(el, x)); return; }
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  const pf = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 0 });
  const mvpCode = (id) => { const m = /^(\d+):(.+)$/.exec(String(id || '')); if (!m) return String(id || ''); return m[1] === '31' ? 'ЖБ ' + m[2] : m[1] === '32' ? 'GZ ' + m[2] : m[2]; };
  const ruleLabel = (code) => (/^\d/.test(code) ? 'Пункт ' + code : code);
  // Сервис цитирует points[].ref («2.1»), а пункт однозначно задаёт внутренний id («31:2.1» -> «ЖБ 2.1»).
  // Правило кладём под обоими ключами, чтобы находить его и по цитате, и по номеру в тексте черновика.
  function addRule(c) {
    const code = c.id || c.ref;
    const rule = { code, id: c.id || code, ref: c.ref, title: String(c.title || ''), text: c.text || '', section: c.section || '', synthetic: !!c.synthetic };
    rules.set(code, rule);
    // Bare refs in the teammate API remain supported, canonical IDs stay intact for provenance.
    if (c.ref && c.ref !== 'section' && !rules.has(c.ref)) rules.set(c.ref, rule);
    return code;
  }
  function ruleNode(c) {
    return h('li', null, h('div', { class: 'rule-heading' }, h('b', null, c.ref ? 'Пункт ' + c.ref : ruleLabel(c.code)),
      h('span', { class: 'rule-id' }, c.id || c.code), c.synthetic || String(c.code).startsWith('demo:') ? h('span', { class: 'synthetic' }, 'Синтетический пример') : null),
      c.title ? h('b', null, c.title + '. ') : null, h('span', null, c.text || ''),
      c.section ? h('span', { class: 'rule-section' }, 'Раздел: ' + c.section) : null);
  }

  // Same-origin API only. A bearer token exists solely in this closure, never browser storage.
  async function api(path, options = {}) {
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 45000);
    let res;
    try {
      const headers = Object.assign({}, options.headers || {}, token ? { Authorization: 'Bearer ' + token } : {});
      res = await fetch(path, Object.assign({}, options, { headers, signal: ctrl.signal }));
    } catch (e) {
      throw new Error(e.name === 'AbortError' ? 'Сервис не успел ответить. Повторите запрос; ваши данные остались на месте.' : 'Нет связи с API. Проверьте подключение и повторите запрос.');
    } finally { clearTimeout(timeout); }
    if (!res.ok) {
      const error = new Error(HTTP_ERRORS[res.status] || 'Сервис вернул ошибку ' + res.status + '.');
      error.conflict = res.status === 409;
      if (res.status === 429) error.message = 'Лимит запросов. Повторите через ' + (Number(res.headers.get('Retry-After')) || 60) + ' сек.';
      throw error;
    }
    return res.json();
  }
  async function detect() {
    if (location.protocol === 'file:' || /[?&]demo=1\b/.test(location.search)) return;
    const ctrl = new AbortController(); const timeout = setTimeout(() => ctrl.abort(), 2500);
    try {
      const response = await fetch('/api/health', { signal: ctrl.signal });
      if (!response.ok) return;
      const health = await response.json();
      mode = 'live'; authRequired = !!health.auth_required;
      try { const d = await api('/api/rules'); if ((d.items || []).length) { rules = new Map(); d.items.forEach(addRule); } } catch (_) { /* Protected API stays live and asks for its token. */ }
    } catch (_) { mode = 'demo'; } finally { clearTimeout(timeout); }
  }
  function renderMode() {
    $('#mode').textContent = mode === 'live' ? authRequired && !token ? 'API · нужен токен' : 'API подключён' : 'Демо в браузере';
    $('#mode').className = 'mode ' + mode;
    $('#foot-mode').textContent = mode === 'live'
      ? 'Обращения и правки сохраняются в API. Отправка только имитируется — связи с игрой нет.'
      : 'Локальная демонстрация: синтетические правила, анализ по ключевым словам. Очередь хранится только в памяти этой вкладки.';
  }
  document.querySelector('.skip-link').addEventListener('click', e => { e.preventDefault(); const main = document.querySelector('main:not([hidden])'); main.setAttribute('tabindex', '-1'); main.focus(); });
  const dialog = $('#connection-dialog');
  $('#connection-open').addEventListener('click', () => { $('#api-token').value = ''; $('#connection-status').textContent = token ? 'Токен установлен в этой вкладке.' : ''; dialog.showModal(); });
  $('#connection-close').addEventListener('click', () => dialog.close());
  $('#connection-clear').addEventListener('click', () => { token = ''; $('#api-token').value = ''; $('#connection-status').textContent = 'Токен удалён.'; renderMode(); });
  $('#connection-form').addEventListener('submit', async (e) => {
    e.preventDefault(); const button = e.submitter || $('#connection-form .primary'); if (button.disabled) return;
    token = $('#api-token').value.trim(); $('#api-token').value = ''; button.disabled = true;
    $('#connection-status').textContent = 'Проверяем доступ…';
    try { const d = await api('/api/rules'); mode = 'live'; if (d.items) { rules = new Map(); d.items.forEach(addRule); } $('#connection-status').textContent = 'Доступ подтверждён. Можно вернуться к работе.'; }
    catch (err) { $('#connection-status').textContent = err.message; }
    finally { button.disabled = false; renderMode(); }
  });

  // ---------- анализ ----------
  async function analyze(input) {
    const t0 = performance.now();
    let result, raw = null, ticketId = null, found = null;
    if (mode === 'live') {
      // POST /api/tickets запускает тот же конвейер, что /triage, и сохраняет обращение в очередь админа.
      const body = { kind: input.kind, text: input.text, attachments_count: input.attachments, server_lang: input.server_lang };
      if (input.player) body.player_id = input.player;
      const fingerprint = JSON.stringify(body);
      if (!intakeKeys.has(fingerprint)) { if (intakeKeys.size >= 50) intakeKeys.delete(intakeKeys.keys().next().value); intakeKeys.set(fingerprint, crypto.randomUUID()); }
      const ticket = await api('/api/tickets', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': intakeKeys.get(fingerprint) }, body: fingerprint });
      intakeKeys.delete(fingerprint);
      ticketId = ticket.id;
      found = (ticket.citations || []).filter((c) => c.ref !== 'section').map(addRule);
      raw = ticket.result;
      result = JSON.parse(JSON.stringify(raw));
      result.reasons = result.reasons || [];
      // Повторы и флуд (больше 5 обращений игрока за час) сервис определяет сам по reporter_hash и created_at.
    } else {
      result = L.demoTriage(input, rules);
      delete result._normalized;
      applyRepeats(input, result);
    }
    const cited = result.draft_reply.cited || [];
    const extra = mode === 'demo' ? (L.CATEGORY_RULES[result.category] || []).filter((c) => rules.has(c)) : [];
    // С API показываем пункты, которые нашёл поиск по правилам (с разделом); без API — цитаты демо-анализа.
    const citations = (found && found.length ? found : Array.from(new Set(cited.concat(extra)))).slice(0, 3);
    if (mode === 'demo' && window.SC.queue) { try { ticketId = window.SC.queue.addDemo(input, result, citations); } catch (e) { ticketId = null; } }
    return { result, raw, citations, ticketId, ms: performance.now() - t0 };
  }
  const HTTP_ERRORS = {
    401: 'Нужен действующий токен. Откройте «Подключение к API» в правом верхнем углу.',
    403: 'API отклонил запрос с этого адреса. Откройте страницу с того же адреса, что и API.',
    413: 'Текст слишком длинный для API.',
    422: 'API не принял обращение: проверьте текст и поля формы.',
    429: 'Слишком много запросов подряд. Подождите минуту и повторите.',
  };

  // ---------- повторы: 1 игрок, 1 проблема, 5 обращений за час ----------
  const history = [];
  const HOUR = 3600e3;
  const tokens = (s) => new Set(s.toLowerCase().split(/[^\p{L}\d]+/u).filter((w) => w.length > 2));
  const DUP_TEXT = {
    ru: 'Здравствуйте! Ваше обращение уже передано администратору, повторно писать не нужно. Ответим в первом обращении.',
    kk: 'Сәлеметсіз бе! Өтінішіңіз әкімшіге жіберілді, қайта жазудың қажеті жоқ. Жауапты алғашқы өтінішке береміз.',
    uz: 'Salom! Murojaatingiz administratorga yuborilgan, qayta yozish shart emas. Javobni birinchi murojaatda beramiz.',
    en: 'Hello! Your request has already been passed to an administrator, there is no need to write again. We will reply in your first request.',
  };
  // Только для демо-режима: та же логика, что в сервисе (backend/app/storage.py, check_repeat).
  const FLOOD_LIMIT = 5;
  function applyRepeats(input, r) {
    if (!input.player) return;
    const now = Date.now();
    const recent = history.filter((x) => x.input.player === input.player && now - x.at < HOUR);
    const mine = tokens(L.normalizeKk(input.text, input.server_lang).text);
    const dup = recent.find((x) => {
      const xr = x.out.result;
      const sameTarget = input.kind === 'report' || (xr.extracted.nickname || '') === (r.extracted.nickname || '');
      if (xr.category === r.category && sameTarget) return true;
      const other = tokens(L.normalizeKk(x.input.text, x.input.server_lang).text);
      const inter = [...mine].filter((w) => other.has(w)).length;
      return mine.size > 0 && inter / Math.max(1, Math.min(mine.size, other.size)) >= 0.6;
    });
    if (dup) {
      const m = Math.round((now - dup.at) / 60000);
      const ago = m < 1 ? 'только что' : m + ' мин назад';
      const mandatory = L.MANDATORY_HUMAN.has(r.category);
      r.is_spam_or_duplicate = true;
      r.priority = 'p3';
      r.needs_human = r.needs_human || mandatory;
      r.reasons = ['Повтор обращения №' + dup.n + ': тот же игрок, та же проблема, ' + ago].concat(mandatory ? ['Эту категорию всегда решает человек'] : []);
      r.draft_reply = { lang: r.lang, text: DUP_TEXT[r.lang] || DUP_TEXT.en, cited: [] };
      r.confidence = 0.9;
    }
    if (recent.length + 1 > FLOOD_LIMIT) {
      r.is_spam_or_duplicate = true;
      r.needs_human = true;
      r.reasons.push('Флуд: ' + (recent.length + 1) + '-е обращение этого игрока за час (лимит ' + FLOOD_LIMIT + ')');
    }
  }
  function renderHistory(current) {
    const box = $('#history');
    box.hidden = !history.length;
    $('#history-list').replaceChildren(...history.slice().reverse().map((x) => {
      const r = x.out.result;
      const flag = r.reasons.some((t) => t.startsWith('Флуд')) ? 'флуд' : r.is_spam_or_duplicate ? 'повтор' : null;
      return h('li', null, h('button', { type: 'button', 'aria-current': String(x === current), onclick: () => { render(x.input, x.out, x.n); renderHistory(x); } },
        h('span', { class: 'num' }, '№' + x.n), h('span', { class: 'prio ' + r.priority }, r.priority.toUpperCase()),
        h('span', { class: 'txt' }, (x.input.player ? x.input.player + ': ' : '') + L.normalizeKk(x.input.text, x.input.server_lang).text),
        flag ? h('span', { class: 'flag' }, flag) : h('span')));
    }));
  }

  // ---------- вывод ----------
  function highlight(text, facts) {
    const spans = [];
    facts.forEach((f) => f.spans.forEach(([s, e]) => spans.push({ s, e, key: f.key })));
    spans.sort((a, b) => a.s - b.s);
    const frag = document.createDocumentFragment(); let pos = 0;
    spans.forEach((sp) => {
      if (sp.s < pos) return;
      if (sp.s > pos) frag.append(text.slice(pos, sp.s));
      frag.append(h('mark', { class: 'f-' + sp.key, 'data-fact': sp.key }, text.slice(sp.s, sp.e)));
      pos = sp.e;
    });
    if (pos < text.length) frag.append(text.slice(pos));
    return frag;
  }
  const FACT_LABEL = { nickname: 'Ник нарушителя', rule_refs: 'Пункт правил от игрока', has_evidence: 'Доказательства', server: 'Сервер' };

  function render(input, out, n) {
    const r = out.result;
    const norm = L.normalizeKk(input.text, input.server_lang);
    const ticket = { result: r, messages: [{ role: 'player', text: input.text, attachments: input.attachments }], images_count: input.attachments };
    const facts = L.factSources(ticket, norm.text);
    const missingRefs = (r.extracted.rule_refs || []).filter((x) => !rules.has(x.replace(/^ОП\s*/i, '')));
    let showRaw = false;

    const quote = h('blockquote', { class: 'quote', lang: r.lang !== 'und' ? r.lang : null });
    const drawQuote = () => { quote.replaceChildren(highlight(showRaw ? input.text : norm.text, facts)); };
    drawQuote();

    const draft = h('textarea', { class: 'draft', rows: '6', maxlength: '5000', 'aria-label': 'Черновик ответа игроку' });
    draft.value = r.draft_reply.text;
    const checks = h('ul', { class: 'checks' });
    const drawChecks = () => {
      const lint = L.lintDraft(draft.value, { lang: r.lang, rules, cited: [] });
      checks.replaceChildren(...lint.checks.map((c) => h('li', { class: c.ok === false ? 'bad' : c.ok ? 'ok' : 'skip' },
        h('b', null, c.ok === false ? '!' : c.ok ? '✓' : '–'), h('span', null, c.ok === false ? (c.short || c.title) : c.title + ': ' + c.detail))));
    };
    draft.addEventListener('input', drawChecks); drawChecks();

    const json = out.raw || Object.assign({}, r);
    const section = (title, ...kids) => h('section', { class: 'block' }, h('h3', null, title), kids);

    $('#out').replaceChildren(
      h('div', { class: 'section-heading' }, h('span', { class: 'section-no' }, '02'), h('h2', { id: 'out-h' }, 'Разбор обращения'), h('span', { class: 'doc-tag' }, n ? 'В сессии №' + n : 'Готово')),
      h('p', { class: 'analysis-verdict' }, h('span', { class: r.needs_human ? 'human' : 'auto' }, r.needs_human ? 'На проверку специалисту' : 'Черновик готов к проверке')),
      h('table', { class: 'summary' }, h('tbody', null,
        h('tr', null, h('th', null, 'Язык'), h('td', null, L.LANGS[r.lang] || r.lang, norm.changed ? h('span', { class: 'note' }, ` (исправлено ${norm.changed} симв. cp1251)`) : null)),
        h('tr', null, h('th', null, 'Категория'), h('td', null, L.CATEGORIES[r.category] || r.category, h('code', null, r.category))),
        h('tr', null, h('th', null, 'Приоритет'), h('td', null, h('span', { class: 'prio ' + r.priority }, r.priority.toUpperCase()), ' ', L.PRIORITIES[r.priority])),
        h('tr', null, h('th', null, 'Спам или повтор'), h('td', null, r.is_spam_or_duplicate ? 'Да' : 'Нет')),
        h('tr', null, h('th', null, 'Кто отвечает'), h('td', null, h('b', { class: r.needs_human ? 'human' : 'auto' }, r.needs_human ? 'Нужен человек' : 'Стандартная проверка'),
          r.reasons.length ? h('ul', { class: 'reasons' }, r.reasons.map((x) => h('li', null, x))) : null)),
        h('tr', null, h('th', null, 'Оценка алгоритма'), h('td', null, pf.format(r.confidence), h('span', { class: 'note small' }, ' · не измеренная точность'))))),

      section('Текст игрока', quote,
        norm.changed ? h('button', { type: 'button', class: 'link', onclick: (e) => { showRaw = !showRaw; drawQuote(); e.target.textContent = showRaw ? 'Показать исправленный текст' : 'Показать как написал игрок'; } }, 'Показать как написал игрок') : null),

      section('Факты и происхождение',
        h('table', { class: 'facts' }, h('thead', null, h('tr', null, h('th', null, 'Поле'), h('th', null, 'Значение'), h('th', null, 'Откуда'))),
          h('tbody', null, facts.map((f) => {
            const tr = h('tr', { 'data-fact': f.key, tabindex: '0' }, h('td', null, h('i', { class: 'dot f-' + f.key }), FACT_LABEL[f.key]), h('td', null, f.value || '—'), h('td', { class: 'muted' }, f.source));
            tr.addEventListener('mouseenter', () => quote.querySelectorAll('[data-fact="' + f.key + '"]').forEach((m) => m.classList.add('on')));
            tr.addEventListener('mouseleave', () => quote.querySelectorAll('mark.on').forEach((m) => m.classList.remove('on')));
            tr.addEventListener('focus', () => quote.querySelectorAll('[data-fact="' + f.key + '"]').forEach((m) => m.classList.add('on')));
            tr.addEventListener('blur', () => quote.querySelectorAll('mark.on').forEach((m) => m.classList.remove('on')));
            return tr;
          })))),

      section('Основание ответа',
        out.citations.length ? h('ul', { class: 'rules' }, out.citations.map((c) => {
          const rule = rules.get(c) || {};
          return ruleNode(Object.assign({ code: c }, rule));
        })) : h('p', { class: 'muted' }, 'Для этой категории правила не нужны или подходящий пункт не найден.'),
        missingRefs.length ? h('p', { class: 'warn' }, 'Игрок указал ' + missingRefs.join(', ') + ' — пункт не найден в загруженной базе. Не используйте его без проверки раздела.') : null),

      section('Черновик ответа', h('p', { class: 'small muted' }, 'Проверьте формулировку. Изменения здесь не сохраняются в очередь — используйте «Открыть в очереди» для правок.'), draft, checks,
        h('button', { type: 'button', class: 'secondary', onclick: async (e) => {
          try { await navigator.clipboard.writeText(draft.value); e.target.textContent = 'Скопировано'; } catch (x) { draft.select(); e.target.textContent = 'Выделено, нажмите Ctrl+C'; }
          setTimeout(() => { e.target.textContent = 'Скопировать ответ'; }, 2000);
        } }, 'Скопировать ответ'),
        out.ticketId ? h('p', { class: 'muted small' }, 'Обращение добавлено в очередь админа. ',
          h('a', { href: '#queue/' + encodeURIComponent(out.ticketId) }, 'Открыть в очереди')) : null),

      h('details', { class: 'json' }, h('summary', null, out.raw ? 'Ответ сервиса как есть (JSON, формат /triage)' : 'Ответ в формате API (JSON)'), h('pre', null, JSON.stringify(json, null, 2))),
      h('p', { class: 'muted small' }, (mode === 'live' ? 'Ответ сервиса' : 'Демо-анализ в браузере') + ' за ' + Math.max(1, Math.round(out.ms)) + ' мс.'));
    const root = $('#out');
    const summary = root.querySelector('.summary');
    const blocks = [...root.querySelectorAll(':scope > .block')];
    const textBlock = blocks[0], factsBlock = blocks[1], rulesBlock = blocks[2], draftBlock = blocks[3];
    const overview = h('div', { class: 'case-overview' },
      h('div', null, h('span', { class: 'overview-label' }, 'Категория'), h('strong', null, L.CATEGORIES[r.category] || r.category)),
      h('div', null, h('span', { class: 'overview-label' }, 'Приоритет'), h('strong', null, h('span', { class: 'prio ' + r.priority }, r.priority.toUpperCase()), ' ', L.PRIORITIES[r.priority])),
      h('div', null, h('span', { class: 'overview-label' }, 'Язык'), h('strong', null, L.LANGS[r.lang] || r.lang)));
    const decision = h('details', { class: 'decision', open: r.needs_human }, h('summary', null, r.needs_human ? 'Нужен человек — причины' : 'Стандартная проверка'),
      r.reasons.length ? h('ul', { class: 'reasons' }, r.reasons.map(x => h('li', null, x))) : h('p', { class: 'small muted' }, 'Проверьте ответ перед использованием.'));
    const diagnostics = h('details', { class: 'document-details' }, h('summary', null, 'Параметры анализа и извлечённые факты'), summary, factsBlock);
    const verdict = root.querySelector('.analysis-verdict'); if (verdict) verdict.remove();
    root.querySelector('.section-heading').after(overview, textBlock, decision, draftBlock, rulesBlock, diagnostics);
    draftBlock.classList.add('reply-block');
    const draftHint = draftBlock.querySelector('p'); if (draftHint) draftHint.textContent = 'Редактирование здесь — для копирования. Чтобы сохранить правки, откройте обращение в очереди.';

  }

  // ---------- форма ----------
  const SAMPLES = window.SC.demo.SAMPLES.concat([
    { label: 'Читы', kind: 'complaint', server_lang: 'ru', attachments: 1, text: 'Ivan_Sokolov летает на машине по воздуху и стреляет через стены. Видео приложил, 5.2' },
    { label: 'Пустая жалоба', kind: 'complaint', server_lang: 'ru', attachments: 1, text: 'жб' },
  ]);
  SAMPLES.forEach((s) => $('#examples').append(h('button', { type: 'button', onclick: () => {
    if (submitting) return;
    document.querySelector(`input[name=kind][value=${s.kind}]`).checked = true;
    $('#text').value = '[Синтетический пример] ' + s.text; $('#att').value = s.attachments; $('#srv').value = s.server_lang;
    $('#form').requestSubmit();
  } }, s.label)));

  $('#form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (submitting) return;
    const err = $('#form-error');
    const input = { kind: document.querySelector('input[name=kind]:checked').value, text: $('#text').value.trim(), player: $('#player').value.trim(),
      attachments: Math.max(0, Number($('#att').value) || 0), server_lang: $('#srv').value };
    if (!input.text) { err.hidden = false; err.textContent = 'Введите текст обращения.'; $('#text').focus(); return; }
    if (input.attachments > 50 || !Number.isInteger(input.attachments)) { err.hidden = false; err.textContent = 'Количество скриншотов: целое число от 0 до 50.'; $('#att').focus(); return; }
    err.hidden = true; submitting = true;
    const btn = $('#go'); btn.disabled = true; btn.textContent = 'Анализируем…';
    try {
      await window.SC.ui.ready;
      const out = await analyze(input);
      const entry = { n: history.length + 1, at: Date.now(), input, out };
      history.push(entry);
      render(input, out, entry.n); renderHistory(entry);
      if (window.innerWidth < 900) $('#out').scrollIntoView({ block: 'start' });
    }
    catch (x) { err.hidden = false; err.textContent = x.message; }
    finally { submitting = false; btn.disabled = false; btn.textContent = 'Проанализировать'; }
  });

  // Общие помощники для очереди админа (queue.js).
  window.SC.ui = { h, pf, mvpCode, ruleLabel, ruleNode, api, HTTP_ERRORS, mode: () => mode, rules: () => rules,
    ready: detect().then(renderMode) };
})();
