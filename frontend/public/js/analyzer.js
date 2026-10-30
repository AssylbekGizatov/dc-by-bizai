/* Страница анализа одного обращения. С API — POST /triage по контракту ТЗ, без API — демо-анализ в браузере. */
(function () {
  'use strict';
  const L = window.SC.logic;
  const $ = (s) => document.querySelector(s);
  let rules = new Map(window.SC.demo.RULES.map((r) => [r.code, r]));
  let mode = 'demo';

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
  const ruleLabel = (code) => (/^\d/.test(code) ? code + ' ОП' : code);

  // ---------- подключение ----------
  async function detect() {
    if (location.protocol === 'file:' || /[?&]demo=1\b/.test(location.search)) return;
    try {
      const ctrl = new AbortController(); const t = setTimeout(() => ctrl.abort(), 2500);
      const r = await fetch('/api/health', { signal: ctrl.signal }); clearTimeout(t);
      if (!r.ok) return;
      mode = 'live';
      const rr = await fetch('/api/rules');
      if (rr.ok) {
        const d = await rr.json();
        const list = (d.items || []).map((x) => ({ code: x.code || mvpCode(x.id || x.ref), title: String(x.title || '').replace(/\s·\s.*$/, ''), text: x.text || '', section: x.section || '' }));
        if (list.length) rules = new Map(list.map((x) => [x.code, x]));
      }
    } catch (e) { mode = 'demo'; }
  }
  function renderMode() {
    $('#mode').textContent = mode === 'live' ? 'Подключено к API' : 'Демо-режим';
    $('#mode').className = 'mode ' + mode;
    $('#foot-mode').textContent = mode === 'live'
      ? 'Анализ выполняет сервис через POST /triage.'
      : 'Демо-режим: анализ в браузере по ключевым словам и демо-формулировкам правил. Настоящий анализ — через API.';
  }

  // ---------- анализ ----------
  async function analyze(input) {
    const t0 = performance.now();
    let result, raw = null;
    if (mode === 'live') {
      const body = { kind: input.kind, server_lang: input.server_lang, messages: [{ role: 'player', text: input.text, attachments: input.attachments }] };
      if (input.player) Object.assign(body, { reporter_hash: input.player, created_at: new Date().toISOString() });
      let res;
      try { res = await fetch('/triage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }
      catch (e) { throw new Error('Сервис не отвечает. Проверьте, что API запущен.'); }
      if (!res.ok) throw new Error(HTTP_ERRORS[res.status] || 'Сервис вернул ошибку ' + res.status + '.');
      raw = await res.json();
      result = JSON.parse(JSON.stringify(raw));
      result.reasons = result.reasons || [];
      result.draft_reply.cited = (result.draft_reply.cited || []).map(mvpCode);
      // Сервис сам ищет повторы того же игрока; страница дополнительно считает флуд (5 обращений за час) по истории вкладки.
      applyRepeats(input, result, result.is_spam_or_duplicate);
    } else {
      result = L.demoTriage(input, rules);
      delete result._normalized;
      applyRepeats(input, result);
    }
    const cited = result.draft_reply.cited || [];
    const extra = mode === 'demo' ? (L.CATEGORY_RULES[result.category] || []).filter((c) => rules.has(c)) : [];
    const citations = Array.from(new Set(cited.concat(extra))).slice(0, 3);
    return { result, raw, citations, ms: performance.now() - t0 };
  }
  const HTTP_ERRORS = {
    401: 'API требует токен (задан API_TOKEN). Для проверки страницы запустите сервис без API_TOKEN.',
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
  function applyRepeats(input, r, serviceFlagged) {
    if (!input.player) return;
    const now = Date.now();
    const recent = history.filter((x) => x.input.player === input.player && now - x.at < HOUR);
    const mine = tokens(L.normalizeKk(input.text, input.server_lang).text);
    const dup = serviceFlagged ? null : recent.find((x) => {
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
      r.needs_human = mandatory;
      r.reasons = ['Повтор обращения №' + dup.n + ': тот же игрок, та же проблема, ' + ago].concat(mandatory ? ['Эту категорию всегда решает человек'] : []);
      r.draft_reply = { lang: r.lang, text: DUP_TEXT[r.lang] || DUP_TEXT.en, cited: [] };
      r.confidence = 0.9;
    }
    if (recent.length + 1 >= 5) {
      r.is_spam_or_duplicate = true;
      r.reasons.push('Флуд: ' + (recent.length + 1) + '-е обращение от этого игрока за час');
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

    const draft = h('textarea', { class: 'draft', rows: '6', 'aria-label': 'Черновик ответа игроку' });
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
      h('h2', { id: 'out-h' }, n ? 'Результат анализа, обращение №' + n : 'Результат анализа'),
      h('table', { class: 'summary' }, h('tbody', null,
        h('tr', null, h('th', null, 'Язык'), h('td', null, L.LANGS[r.lang] || r.lang, norm.changed ? h('span', { class: 'note' }, ` (исправлено ${norm.changed} симв. cp1251)`) : null)),
        h('tr', null, h('th', null, 'Категория'), h('td', null, L.CATEGORIES[r.category] || r.category, h('code', null, r.category))),
        h('tr', null, h('th', null, 'Приоритет'), h('td', null, h('span', { class: 'prio ' + r.priority }, r.priority.toUpperCase()), ' ', L.PRIORITIES[r.priority])),
        h('tr', null, h('th', null, 'Спам или повтор'), h('td', null, r.is_spam_or_duplicate ? 'Да' : 'Нет')),
        h('tr', null, h('th', null, 'Кто отвечает'), h('td', null, h('b', { class: r.needs_human ? 'human' : 'auto' }, r.needs_human ? 'Нужен человек' : 'Можно ответить сразу'),
          r.reasons.length ? h('ul', { class: 'reasons' }, r.reasons.map((x) => h('li', null, x))) : null)),
        h('tr', null, h('th', null, 'Уверенность'), h('td', null, pf.format(r.confidence))))),

      section('Текст игрока', quote,
        norm.changed ? h('button', { type: 'button', class: 'link', onclick: (e) => { showRaw = !showRaw; drawQuote(); e.target.textContent = showRaw ? 'Показать исправленный текст' : 'Показать как написал игрок'; } }, 'Показать как написал игрок') : null),

      section('Что извлечено из текста',
        h('table', { class: 'facts' }, h('thead', null, h('tr', null, h('th', null, 'Поле'), h('th', null, 'Значение'), h('th', null, 'Откуда'))),
          h('tbody', null, facts.map((f) => {
            const tr = h('tr', { 'data-fact': f.key }, h('td', null, h('i', { class: 'dot f-' + f.key }), FACT_LABEL[f.key]), h('td', null, f.value || '—'), h('td', { class: 'muted' }, f.source));
            tr.addEventListener('mouseenter', () => quote.querySelectorAll('[data-fact="' + f.key + '"]').forEach((m) => m.classList.add('on')));
            tr.addEventListener('mouseleave', () => quote.querySelectorAll('mark.on').forEach((m) => m.classList.remove('on')));
            return tr;
          })))),

      section('Найденные правила (RAG)',
        out.citations.length ? h('ul', { class: 'rules' }, out.citations.map((c) => {
          const rule = rules.get(c) || {};
          return h('li', null, h('b', null, ruleLabel(c)), rule.title ? ' ' + rule.title + '. ' : ' ', h('span', null, rule.text || ''));
        })) : h('p', { class: 'muted' }, 'Для этой категории правила не нужны или подходящий пункт не найден.'),
        missingRefs.length ? h('p', { class: 'warn' }, 'Игрок указал ' + missingRefs.join(', ') + ' — такого пункта нет в правилах, в ответе его не цитируем.') : null),

      section('Черновик ответа игроку', draft, checks,
        h('button', { type: 'button', class: 'secondary', onclick: async (e) => {
          try { await navigator.clipboard.writeText(draft.value); e.target.textContent = 'Скопировано'; } catch (x) { draft.select(); e.target.textContent = 'Выделено, нажмите Ctrl+C'; }
          setTimeout(() => { e.target.textContent = 'Скопировать ответ'; }, 2000);
        } }, 'Скопировать ответ')),

      h('details', { class: 'json' }, h('summary', null, out.raw ? 'Ответ API как есть (JSON)' : 'Ответ в формате API (JSON)'), h('pre', null, JSON.stringify(json, null, 2))),
      h('p', { class: 'muted small' }, (mode === 'live' ? 'Ответ /triage' : 'Демо-анализ в браузере') + ' за ' + Math.max(1, Math.round(out.ms)) + ' мс.'));
  }

  // ---------- форма ----------
  const SAMPLES = window.SC.demo.SAMPLES.concat([
    { label: 'Читы', kind: 'complaint', server_lang: 'ru', attachments: 1, text: 'Ivan_Sokolov летает на машине по воздуху и стреляет через стены. Видео приложил, 5.2' },
    { label: 'Пустая жалоба', kind: 'complaint', server_lang: 'ru', attachments: 1, text: 'жб' },
  ]);
  SAMPLES.forEach((s) => $('#examples').append(h('button', { type: 'button', onclick: () => {
    document.querySelector(`input[name=kind][value=${s.kind}]`).checked = true;
    $('#text').value = s.text; $('#att').value = s.attachments; $('#srv').value = s.server_lang;
    $('#form').requestSubmit();
  } }, s.label)));

  $('#form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const err = $('#form-error');
    const input = { kind: document.querySelector('input[name=kind]:checked').value, text: $('#text').value.trim(), player: $('#player').value.trim(),
      attachments: Math.max(0, Number($('#att').value) || 0), server_lang: $('#srv').value };
    if (!input.text) { err.hidden = false; err.textContent = 'Введите текст обращения.'; $('#text').focus(); return; }
    err.hidden = true;
    const btn = $('#go'); btn.disabled = true; btn.textContent = 'Анализируем…';
    try {
      const out = await analyze(input);
      const entry = { n: history.length + 1, at: Date.now(), input, out };
      history.push(entry);
      render(input, out, entry.n); renderHistory(entry);
      if (window.innerWidth < 900) $('#out').scrollIntoView({ block: 'start' });
    }
    catch (x) { err.hidden = false; err.textContent = x.message; }
    finally { btn.disabled = false; btn.textContent = 'Проанализировать'; }
  });

  detect().then(renderMode);
})();
