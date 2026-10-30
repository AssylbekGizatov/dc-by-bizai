/* Очередь админа: список обращений, черновик и кнопки «Отправить», «Править», «Эскалировать».
 * С API: GET /api/tickets, PATCH /api/tickets/{id}/review; каждая правка и решение сохраняются в сервисе
 * как обучающий сигнал (GET /api/tickets/{id}/feedback). Отправка имитируется: интеграции с игрой нет.
 * В демо-режиме: синтетические обращения в памяти вкладки. */
(function () {
  'use strict';
  const L = window.SC.logic, UI = window.SC.ui, D = window.SC.demo;
  const h = UI.h;
  const $ = (s) => document.querySelector(s);

  const STATUS = { pending: 'Новое', reviewed: 'Проверено', escalated: 'Эскалировано', simulated_sent: 'Отправлено' };
  const TABS = [['pending', 'Новые'], ['reviewed', 'Проверенные'], ['escalated', 'Эскалация'], ['simulated_sent', 'Отправленные'], ['', 'Все']];
  const KIND = { complaint: 'Жалоба', report: 'Репорт' };
  const state = { status: 'pending', human: false, urgent: false, items: [], total: 0, selected: null,
    editing: false, escalating: false, msg: null, error: null, loading: false, history: [] };
  let demo = null;

  // ---------- приведение обращений к одному виду ----------
  const live = () => UI.mode() === 'live';
  const ruleByCode = (code) => { const r = UI.rules().get(code); return { code, title: r ? r.title : '', text: r ? r.text : '' }; };
  function fromApi(t) {
    return { id: t.id, kind: t.kind, created_at: t.created_at, status: t.status, revision: t.revision, text: t.text,
      player: t.player_id, result: t.result, draft: t.draft_reply, note: t.reviewer_note || '',
      citations: (t.citations || []).filter((c) => c.ref !== 'section')
        .map((c) => ({ code: UI.mvpCode(c.id), ref: c.ref, title: String(c.title || '').replace(/\s·\s.*$/, ''), text: c.text || '' })) };
  }
  const demoStatus = (s) => (s === 'new' ? 'pending' : s === 'sent' ? 'simulated_sent' : s);
  function fromDemo(t) {
    return { id: t.id, kind: t.kind, created_at: t.created_at, revision: t.revision || 1, status: demoStatus(t.status),
      text: t.messages.filter((m) => m.role === 'player').map((m) => m.text).join('\n'),
      player: t.reporter || null, result: t.result, draft: t.draft_current || t.result.draft_reply.text, note: '',
      citations: (t.citations || []).map(ruleByCode),
      log: (t.history || []).filter((x) => x.action !== 'created').map((x) => ({ created_at: x.at, status: demoStatus(x.action),
        changed: x.before !== x.after, reviewer_note: x.note || '' })) };
  }
  function demoStore() {
    if (!demo) demo = D.tickets().map(fromDemo);
    return demo;
  }

  // ---------- данные ----------
  async function api(path, options) {
    let res;
    try { res = await fetch(path, options); } catch (e) { throw new Error('Сервис не отвечает. Проверьте, что API запущен.'); }
    if (res.status === 409) { const err = new Error('conflict'); err.conflict = true; throw err; }
    if (!res.ok) throw new Error(UI.HTTP_ERRORS[res.status] || 'Сервис вернул ошибку ' + res.status + '.');
    return res.json();
  }
  async function load() {
    state.loading = true; state.error = null; renderList();
    try {
      if (live()) {
        const q = new URLSearchParams({ limit: '100' }); if (state.status) q.set('status', state.status);
        const d = await api('/api/tickets?' + q);
        state.items = (d.items || []).map(fromApi); state.total = d.total || state.items.length;
      } else {
        state.items = demoStore().filter((t) => !state.status || t.status === state.status).slice().sort((a, b) => b.created_at.localeCompare(a.created_at));
        state.total = state.items.length;
      }
    } catch (e) { state.items = []; state.error = e.message; }
    state.loading = false; renderList();
  }
  const visible = () => state.items.filter((t) => (!state.human || t.result.needs_human) && (!state.urgent || t.result.priority === 'p0' || t.result.priority === 'p1'));

  async function select(id) {
    state.editing = false; state.escalating = false; state.msg = null; state.history = [];
    let t = state.items.find((x) => x.id === id) || (live() ? null : demoStore().find((x) => x.id === id));
    if (!t && live()) { try { t = fromApi(await api('/api/tickets/' + encodeURIComponent(id))); } catch (e) { t = null; } }
    state.selected = t || null;
    renderList(); renderDetail();
    if (t) loadHistory(t);
  }
  async function loadHistory(t) {
    if (!live()) { state.history = t.log || []; renderDetail(); return; }
    try {
      const d = await api('/api/tickets/' + encodeURIComponent(t.id) + '/feedback');
      if (state.selected && state.selected.id === t.id) {
        state.history = (d.items || []).map((x) => ({ created_at: x.created_at, status: x.status, changed: x.previous_draft !== x.edited_draft, reviewer_note: x.reviewer_note || '' }));
        renderDetail();
      }
    } catch (e) { /* история не обязательна для работы */ }
  }

  // ---------- действия: каждое сохраняется в сервисе вместе с текстом черновика ----------
  async function review(change, okText) {
    const t = state.selected;
    state.error = null;
    if (live()) {
      try {
        const updated = fromApi(await api('/api/tickets/' + encodeURIComponent(t.id) + '/review', { method: 'PATCH',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({ expected_revision: t.revision }, change)) }));
        replace(updated);
      } catch (e) {
        if (e.conflict) { await select(t.id); state.msg = { bad: true, text: 'Обращение уже изменили в другой вкладке. Загрузили свежую версию, проверьте черновик.' }; renderDetail(); return; }
        state.msg = { bad: true, text: e.message }; renderDetail(); return;
      }
    } else {
      const before = t.draft;
      Object.assign(t, { draft: change.draft_reply != null ? change.draft_reply : t.draft, status: change.status || t.status,
        note: change.reviewer_note != null ? change.reviewer_note : t.note, revision: t.revision + 1 });
      t.log = (t.log || []).concat([{ created_at: new Date().toISOString(), status: t.status, changed: before !== t.draft, reviewer_note: change.reviewer_note || '' }]);
      replace(t);
    }
    state.editing = false; state.escalating = false; state.msg = { text: okText };
    renderList(); renderDetail(); loadHistory(state.selected);
  }
  function replace(t) {
    state.selected = t;
    const i = state.items.findIndex((x) => x.id === t.id);
    if (i >= 0) state.items[i] = t;
  }

  // ---------- вывод ----------
  function ago(iso) {
    const ms = Date.now() - Date.parse(iso);
    if (!isFinite(ms)) return '';
    const m = Math.round(ms / 60000);
    if (m < 1) return 'только что';
    if (m < 60) return m + ' мин назад';
    if (m < 24 * 60) return Math.round(m / 60) + ' ч назад';
    return new Date(iso).toLocaleDateString('ru-RU');
  }
  const prio = (p) => h('span', { class: 'prio ' + p }, p.toUpperCase());

  function renderList() {
    const tabs = h('div', { class: 'tabs', role: 'group', 'aria-label': 'Статус' }, TABS.map(([value, label]) =>
      h('button', { type: 'button', 'aria-pressed': String(state.status === value), onclick: () => { state.status = value; load(); } }, label)));
    const chip = (label, key) => h('button', { type: 'button', class: 'chip', 'aria-pressed': String(state[key]), onclick: () => { state[key] = !state[key]; renderList(); } }, label);
    const items = visible();
    let body;
    if (state.loading) body = h('p', { class: 'muted' }, 'Загружаем…');
    else if (state.error) body = h('p', { class: 'error' }, state.error);
    else if (!items.length) body = h('div', { class: 'muted' }, h('p', null, state.items.length ? 'Под фильтры ничего не попало.' : 'В этом разделе пусто.'),
      live() && !state.items.length && state.status === 'pending' ? h('p', null, 'Проанализируйте обращение на вкладке «Анализ» или ',
        h('button', { type: 'button', class: 'link', onclick: addSamples }, 'добавьте примеры'), '.') : null);
    else body = h('ul', { class: 'qlist' }, items.map((t) => h('li', null,
      h('button', { type: 'button', 'aria-current': String(!!state.selected && state.selected.id === t.id), onclick: () => { location.hash = '#queue/' + encodeURIComponent(t.id); } },
        prio(t.result.priority),
        h('span', { class: 'txt' }, h('b', null, KIND[t.kind] + ': '), L.normalizeKk(t.text, t.result.lang).text),
        h('span', { class: 'meta' }, t.result.needs_human ? h('span', { class: 'flag', title: 'Нужен человек' }, 'человек') : null, ' ', ago(t.created_at)),
        state.status ? null : h('span', { class: 'st st-' + t.status }, STATUS[t.status])))));
    $('#q-list').replaceChildren(
      h('h1', null, 'Очередь обращений'), tabs,
      h('div', { class: 'chips' }, chip('Нужен человек', 'human'), chip('Срочные P0–P1', 'urgent'),
        h('button', { type: 'button', class: 'link refresh', onclick: load }, 'Обновить')),
      h('p', { class: 'muted small count' }, state.loading ? '' : 'Показано: ' + items.length + (live() && state.total > state.items.length ? ' из ' + state.total : '')),
      body);
  }

  function renderDetail() {
    const t = state.selected;
    const box = $('#q-detail');
    if (!t) {
      box.replaceChildren(h('h2', null, 'Обращение'), h('p', { class: 'muted' }, 'Выберите обращение в списке слева. Черновик можно отправить, поправить или передать старшему администратору.'));
      return;
    }
    const r = t.result;
    const sent = t.status === 'simulated_sent';
    const norm = L.normalizeKk(t.text, r.lang);
    // Номер в черновике — points[].ref («2.1»), поэтому правило доступно и по нему, и по коду с разделом.
    const rules = new Map(t.citations.map((c) => [c.code, c]));
    t.citations.forEach((c) => { if (c.ref && !rules.has(c.ref)) rules.set(c.ref, c); });
    UI.rules().forEach((v, k) => { if (!rules.has(k)) rules.set(k, v); });

    const draft = h('textarea', { class: 'draft', rows: '6', 'aria-label': 'Черновик ответа игроку', readonly: !state.editing });
    draft.value = t.draft;
    const checks = h('ul', { class: 'checks' });
    const drawChecks = () => {
      const lint = L.lintDraft(draft.value, { lang: r.lang, rules, cited: [] });
      checks.replaceChildren(...lint.checks.map((c) => h('li', { class: c.ok === false ? 'bad' : c.ok ? 'ok' : 'skip' },
        h('b', null, c.ok === false ? '!' : c.ok ? '✓' : '–'), h('span', null, c.ok === false ? (c.short || c.title) : c.title))));
    };
    draft.addEventListener('input', drawChecks); drawChecks();
    const needText = () => { if (draft.value.trim()) return true; state.msg = { bad: true, text: 'Черновик пустой.' }; renderDetail(); return false; };

    let actions;
    if (sent) actions = h('p', { class: 'muted' }, 'Отправленный ответ изменить нельзя.');
    else if (state.escalating) {
      const note = h('textarea', { rows: '3', id: 'q-note', maxlength: '3000', placeholder: 'Например: стороны дают разные версии, нужна проверка логов' });
      actions = h('div', { class: 'escalate' },
        h('label', { for: 'q-note' }, 'Почему нужен старший администратор'), note,
        h('div', { class: 'actions' },
          h('button', { type: 'button', class: 'primary', onclick: () => {
            if (!note.value.trim()) { note.focus(); state.msg = { bad: true, text: 'Напишите причину эскалации.' }; renderMsg(); return; }
            review({ status: 'escalated', reviewer_note: note.value.trim(), draft_reply: draft.value }, 'Передано старшему администратору.');
          } }, 'Эскалировать'),
          h('button', { type: 'button', class: 'secondary', onclick: () => { state.escalating = false; renderDetail(); } }, 'Отмена')));
      setTimeout(() => note.focus(), 0);
    } else {
      actions = h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'primary', onclick: () => { if (needText()) review({ status: 'simulated_sent', draft_reply: draft.value }, 'Отправлено игроку (имитация).'); } }, 'Отправить'),
        state.editing
          ? [h('button', { type: 'button', class: 'secondary', onclick: () => { if (needText()) review({ status: 'reviewed', draft_reply: draft.value }, 'Правка сохранена.'); } }, 'Сохранить правку'),
             h('button', { type: 'button', class: 'secondary', onclick: () => { state.editing = false; renderDetail(); } }, 'Отмена')]
          : h('button', { type: 'button', class: 'secondary', onclick: () => { state.editing = true; state.msg = null; renderDetail(); const d = $('#q-detail .draft'); d.focus(); d.setSelectionRange(d.value.length, d.value.length); } }, 'Править'),
        h('button', { type: 'button', class: 'secondary', onclick: () => { state.escalating = true; state.msg = null; renderDetail(); } }, 'Эскалировать'));
    }

    const section = (title, ...kids) => h('section', { class: 'block' }, h('h3', null, title), kids);
    box.replaceChildren(
      h('h2', null, KIND[t.kind] + ' · ' + STATUS[t.status]),
      h('p', { class: 'muted small meta-line' }, [ago(t.created_at), t.player ? 'игрок ' + t.player : null, L.LANGS[r.lang] || r.lang].filter(Boolean).join(' · ')),
      h('table', { class: 'summary' }, h('tbody', null,
        h('tr', null, h('th', null, 'Категория'), h('td', null, L.CATEGORIES[r.category] || r.category, h('code', null, r.category))),
        h('tr', null, h('th', null, 'Приоритет'), h('td', null, prio(r.priority), ' ', L.PRIORITIES[r.priority])),
        h('tr', null, h('th', null, 'Кто отвечает'), h('td', null, h('b', { class: r.needs_human ? 'human' : 'auto' }, r.needs_human ? 'Нужен человек' : 'Можно ответить сразу'),
          r.reasons.length ? h('ul', { class: 'reasons' }, r.reasons.map((x) => h('li', null, x))) : null)),
        t.note ? h('tr', null, h('th', null, 'Заметка админа'), h('td', null, t.note)) : null)),
      section('Текст игрока', h('blockquote', { class: 'quote', lang: r.lang !== 'und' ? r.lang : null }, norm.text)),
      section('Правила (RAG)', t.citations.length
        ? h('ul', { class: 'rules' }, t.citations.map((c) => h('li', null, h('b', null, UI.ruleLabel(c.code)), c.title ? ' ' + c.title + '. ' : ' ', h('span', null, c.text))))
        : h('p', { class: 'muted' }, 'Для этой категории правила не нужны или подходящий пункт не найден.')),
      section('Черновик ответа', draft, checks, actions, h('p', { class: 'msg', id: 'q-msg', role: 'status' }),
        sent ? null : h('p', { class: 'muted small' }, 'Отправка имитируется: интеграции с игрой нет. Каждая правка и решение сохраняются как обучающий сигнал.')),
      section('История правок', state.history.length
        ? h('ol', { class: 'edits' }, state.history.map((x) => h('li', null, h('span', { class: 'muted' }, ago(x.created_at)), ' ', STATUS[x.status] || x.status,
          x.changed ? ' · черновик изменён' : '', x.status === 'escalated' && x.reviewer_note ? ' · «' + x.reviewer_note + '»' : '')))
        : h('p', { class: 'muted' }, 'Правок пока нет.')));
    renderMsg();
  }
  function renderMsg() {
    const el = $('#q-msg'); if (!el) return;
    el.textContent = state.msg ? state.msg.text : '';
    el.className = 'msg' + (state.msg && state.msg.bad ? ' bad' : state.msg ? ' ok' : '');
  }

  async function addSamples() {
    const samples = D.SAMPLES.concat([{ kind: 'report', server_lang: 'ru', attachments: 0, text: 'Оплатил донат, деньги списались, а голды не пришли' },
      { kind: 'report', server_lang: 'ru', attachments: 0, text: 'Застрял в текстурах возле банка, не могу выйти' }]);
    try {
      for (const s of samples) await api('/api/tickets', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: s.kind, text: s.text, attachments_count: s.attachments, server_lang: s.server_lang }) });
    } catch (e) { state.error = e.message; }
    load();
  }

  // ---------- переключение «Анализ» / «Очередь» ----------
  let inQueue = false;
  async function route() {
    const m = /^#queue(?:\/(.+))?$/.exec(location.hash);
    const entering = !inQueue && !!m; inQueue = !!m;
    $('#view-analyze').hidden = !!m; $('#view-queue').hidden = !m;
    document.querySelectorAll('.nav a').forEach((a) => a.setAttribute('aria-current', String((a.dataset.view === 'queue') === !!m)));
    if (!m) return;
    await UI.ready;
    if (entering) await load(); // при каждом входе в очередь: туда могли попасть новые обращения со страницы анализа
    if (m[1]) await select(decodeURIComponent(m[1]));
    else { state.selected = null; renderList(); renderDetail(); }
  }

  window.SC.queue = {
    // Демо-режим: обращение со страницы анализа попадает в очередь вкладки.
    addDemo(input, result, citations) {
      const id = 'D-' + (demoStore().length + 1);
      demoStore().push({ id, kind: input.kind, created_at: new Date().toISOString(), status: 'pending', revision: 1, text: input.text,
        player: input.player || null, result: JSON.parse(JSON.stringify(result)), draft: result.draft_reply.text, note: '',
        citations: citations.map(ruleByCode), log: [] });
      return id;
    },
  };
  window.addEventListener('hashchange', route);
  route();
})();
