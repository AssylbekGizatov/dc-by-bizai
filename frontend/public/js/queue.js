/* Vanilla admin workbench. API is authoritative; browser demo is ephemeral and synthetic.
 * A simulated send only records a review. There is no game integration. */
(function () {
  'use strict';
  const L = window.SC.logic, UI = window.SC.ui, D = window.SC.demo, h = UI.h;
  const $ = (s) => document.querySelector(s);
  const replaceContent = (el, ...children) => { const holder = h('div', null, children); el.replaceChildren(...holder.childNodes); };
  const STATUS = { pending: 'Новое', reviewed: 'Проверено', escalated: 'Эскалировано', simulated_sent: 'Симуляция' };
  const TABS = [['pending', 'Новые'], ['reviewed', 'Проверенные'], ['escalated', 'Эскалация'], ['simulated_sent', 'Симуляции'], ['', 'Все']];
  const KIND = { complaint: 'Жалоба', report: 'Репорт' };
  const state = { status: 'pending', human: false, urgent: false, search: '', lang: '', category: '', priority: '', offset: 0, limit: 50, items: [], total: 0, selected: null,
    editing: false, escalating: false, escalationReason:'', msg: null, error: null, loading: false, busy: false, history: [], draft: '', note: '', recovery: '', recoveryNote: '' };
  let demo = null, selectionRequest = 0, loadRequest = 0, historyRequest = 0, inQueue = false, acceptedHash = location.hash;
  const live = () => UI.mode() === 'live';
  const api = UI.api;
  const dirty = () => !!state.selected && ((state.editing && (state.draft !== state.selected.draft || state.note !== state.selected.note)) || (state.escalating && !!state.escalationReason.trim()));
  const ruleByCode = (code) => Object.assign({ code, synthetic: true }, UI.rules().get(code) || {});
  function fromApi(t) {
    return { id: t.id, kind: t.kind, created_at: t.created_at, status: t.status, revision: t.revision, text: t.text,
      player: t.player_id, result: t.result, draft: t.draft_reply, note: t.reviewer_note || '', normalizedText:t.normalized_text, diagnostics:t.diagnostics,
      citations: (t.citations || []).filter(c => c.ref !== 'section').map(c => ({ code: c.id || c.ref, id: c.id, ref: c.ref,
        title: c.title || '', text: c.text || '', section: c.section || '', synthetic: !!c.synthetic })) };
  }
  const demoStatus = s => s === 'new' ? 'pending' : s === 'sent' ? 'simulated_sent' : s;
  function fromDemo(t) {
    return { id: t.id, kind: t.kind, created_at: t.created_at, revision: t.revision || 1, status: demoStatus(t.status),
      text: '[Синтетический пример] ' + t.messages.filter(m => m.role === 'player').map(m => m.text).join('\n'),
      player: t.reporter || null, result: t.result, draft: t.draft_current || t.result.draft_reply.text, note: '',
      citations: (t.citations || []).map(ruleByCode), log: (t.history || []).filter(x => x.action !== 'created').map(x => ({
        created_at: x.at, status: demoStatus(x.action), changed: x.before !== x.after, reviewer_note: x.note || '' })) };
  }
  function demoStore() { if (!demo) demo = D.tickets().map(fromDemo); return demo; }
  async function load() {
    const request = ++loadRequest;
    state.loading = true; state.error = null; renderList();
    try {
      let items, total;
      if (live()) {
        const q = new URLSearchParams({ limit: String(state.limit), offset: String(state.offset) }); if (state.status) q.set('status', state.status);
        if (state.search) q.set('search', state.search);
        if (state.human) q.set('needs_human', 'true');
        if (state.urgent) q.set('urgent', 'true');
        if (state.lang) q.set('language', state.lang);
        if (state.category) q.set('category', state.category);
        if (state.priority) q.set('priority', state.priority);
        const d = await api('/api/tickets?' + q); items = (d.items || []).map(fromApi); total = d.total ?? items.length;
      } else { items = demoStore().filter(t => (!state.status || t.status === state.status) && (!state.human || t.result.needs_human) && (!state.urgent || ['p0','p1'].includes(t.result.priority)) && byFields(t) && (!state.search || [t.text,t.id,t.player,t.draft].join(' ').toLocaleLowerCase().includes(state.search.toLocaleLowerCase()))).slice().sort((a, b) => b.created_at.localeCompare(a.created_at)); total = items.length; items = items.slice(state.offset,state.offset + state.limit); }
      if (request !== loadRequest) return;
      state.items = items; state.total = total;
    } catch (e) { if (request !== loadRequest) return; state.items = []; state.error = e.message; }
    state.loading = false; renderList();
  }
  // Фильтры очереди по языку, категории и приоритету (п. 7 ТЗ); API фильтрует так же: language, category, priority.
  const byFields = t => (!state.lang || t.result.lang === state.lang) && (!state.category || t.result.category === state.category) && (!state.priority || t.result.priority === state.priority);
  const filtered = () => !!(state.search || state.human || state.urgent || state.lang || state.category || state.priority);
  const visible = () => state.items.filter(t => (!state.status || t.status === state.status) && (!state.human || t.result.needs_human) && (!state.urgent || ['p0', 'p1'].includes(t.result.priority)) && byFields(t));
  async function select(id, force = false) {
    const request = ++selectionRequest;
    state.editing = false; state.escalating = false; state.msg = null; state.history = []; state.recovery = ''; state.recoveryNote = '';
    let t = force ? null : state.items.find(x => x.id === id) || (!live() ? demoStore().find(x => x.id === id) : null);
    if (!t && live()) {
      $('#q-detail').replaceChildren(h('p', { role: 'status', class: 'muted' }, 'Открываем обращение…'));
      $('#view-queue').classList.add('has-selection');
      try { t = fromApi(await api('/api/tickets/' + encodeURIComponent(id))); }
      catch (e) { if (request !== selectionRequest) return; if (force) throw e; state.selected = null; renderList(); $('#q-detail').replaceChildren(h('a', { class: 'detail-back', href: '#queue' }, 'К очереди'), h('p', { role: 'alert', class: 'error' }, e.message), h('button', { class: 'secondary', type: 'button', onclick: () => select(id) }, 'Повторить')); return; }
    }
    if (request !== selectionRequest) return;
    state.selected = t || null; if (t && force) { const cached = state.items.findIndex(x => x.id === t.id); if (cached >= 0) state.items[cached] = t; } state.draft = t ? t.draft : ''; state.note = t ? t.note : '';
    renderList(); renderDetail();
    if (t) loadHistory(t);
  }
  async function loadHistory(t) {
    const request = ++historyRequest;
    if (!live()) { state.history = t.log || []; renderHistory(); return; }
    try {
      const d = await api('/api/tickets/' + encodeURIComponent(t.id) + '/feedback');
      if (request === historyRequest && state.selected && state.selected.id === t.id) {
        state.history = (d.items || []).map(x => ({ created_at: x.created_at, status: x.status, changed: x.previous_draft !== x.edited_draft, reviewer_note: x.reviewer_note || '' }));
        // Never replace the editor or its focus when asynchronous feedback arrives.
        renderHistory();
      }
    } catch (_) { if (request === historyRequest && state.selected && state.selected.id === t.id) { const box = $('#q-history'); if (box) replaceContent(box, h('p', { class: 'muted small' }, 'История сейчас недоступна. Черновик можно проверить и сохранить.')); } }
  }
  async function review(change, okText) {
    const t = state.selected; if (!t || state.busy) return;
    state.busy = true; state.msg = null; renderDetail(); renderList();
    try {
      if (live()) {
        const updated = fromApi(await api('/api/tickets/' + encodeURIComponent(t.id) + '/review', { method: 'PATCH',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({ expected_revision: t.revision, reviewer_note: t.note }, change)) }));
        replace(updated);
      } else {
        const before = t.draft;
        Object.assign(t, { draft: change.draft_reply ?? t.draft, status: change.status || t.status,
          note: change.reviewer_note ?? t.note, revision: t.revision + 1 });
        t.log = (t.log || []).concat([{ created_at: new Date().toISOString(), status: t.status, changed: before !== t.draft, reviewer_note: t.note }]); replace(t);
      }
      state.editing = false; state.escalating = false; state.draft = state.selected.draft; state.note = state.selected.note;
      state.recovery = ''; state.recoveryNote = ''; state.msg = { text: okText }; loadHistory(state.selected);
    } catch (e) {
      if (e.conflict) {
        const unsaved = state.draft, unsavedNote = change.reviewer_note ?? state.note;
        try {
          await select(t.id, true);
          state.recovery = unsaved; state.recoveryNote = unsavedNote;
          state.msg = { bad: true, text: 'Обращение изменили в другой вкладке. Загрузили свежую версию. Ваш вариант сохранён ниже для сравнения.' };
        } catch (refreshError) {
          state.selected = t; state.draft = unsaved; state.note = unsavedNote; state.editing = true;
          state.msg = { bad: true, text: 'Версия изменилась, но обновление сейчас недоступно. Ваш черновик сохранён в редакторе. ' + refreshError.message };
        }
      } else state.msg = { bad: true, text: e.message };
    } finally { state.busy = false; renderList(); renderDetail(); }
  }
  function replace(t) { state.selected = t; const i = state.items.findIndex(x => x.id === t.id); if (i >= 0) state.items[i] = t; }
  function ago(iso) {
    const ms = Date.now() - Date.parse(iso); if (!isFinite(ms)) return '';
    const m = Math.max(0, Math.round(ms / 60000)); if (m < 1) return 'только что'; if (m < 60) return m + ' мин назад';
    if (m < 1440) return Math.round(m / 60) + ' ч назад'; return new Date(iso).toLocaleDateString('ru-RU');
  }
  const prio = p => h('span', { class: 'prio ' + p }, String(p).toUpperCase());
  function renderList() {
    const items = visible();
    const tabs = h('div', { class: 'tabs', role: 'group', 'aria-label': 'Статус' }, TABS.map(([value, label]) =>
      h('button', { type: 'button', disabled: state.busy, 'aria-pressed': String(state.status === value), onclick: () => { state.status = value; state.offset = 0; load(); } }, label)));
    const chip = (label, key) => h('button', { type: 'button', class: 'chip', disabled: state.busy, 'aria-pressed': String(state[key]), onclick: () => { state[key] = !state[key]; state.offset = 0; load(); } }, label);
    const search = h('input', { type: 'search', id: 'queue-search', maxlength: '200', placeholder: 'Текст, ID или ник игрока', disabled: state.busy }); search.value = state.search;
    const searchForm = h('form', { class: 'queue-search', role: 'search', onsubmit: e => { e.preventDefault(); if (state.busy) return; state.search = search.value.trim(); state.offset = 0; load(); } }, h('label', { class: 'field', for: 'queue-search' }, h('span', null, 'Поиск по обращениям'), search), h('button', { type: 'submit', class: 'primary', disabled: state.busy }, 'Найти'));
    const picker = (label, key, options) => {
      const id = 'queue-filter-' + key;
      const el = h('select', { id, disabled: state.busy, onchange: e => { state[key] = e.target.value; state.offset = 0; load(); } },
        h('option', { value: '' }, 'Все'), Object.entries(options).map(([value, text]) => h('option', { value }, text)));
      el.value = state[key];
      return h('label', { class: 'field', for: id }, h('span', null, label), el);
    };
    const filters = h('div', { class: 'q-filters' }, picker('Язык', 'lang', L.LANGS), picker('Категория', 'category', L.CATEGORIES),
      picker('Приоритет', 'priority', Object.fromEntries(Object.entries(L.PRIORITIES).map(([k, v]) => [k, k.toUpperCase() + ' · ' + v]))));
    let body;
    if (state.loading) body = h('div', { role: 'status' }, h('div', { class: 'loading-line' }), h('p', { class: 'muted small' }, 'Загружаем очередь…'));
    else if (state.error) body = h('div', { class: 'queue-empty' }, h('p', { class: 'error', role: 'alert' }, state.error), h('button', { type: 'button', class: 'secondary', onclick: load }, 'Повторить'));
    else if (!items.length) body = h('div', { class: 'queue-empty' }, h('h3', null, filtered() ? 'Обращения не найдены' : 'В этом статусе нет обращений'),
      h('p', null, filtered() ? 'Измените запрос или сбросьте фильтры.' : 'Новые обращения появятся после анализа. Проверенные остаются в своих разделах.'),
      filtered() || state.offset ? h('button', {type:'button',class:'secondary',onclick:()=>{state.search='';state.human=false;state.urgent=false;state.lang='';state.category='';state.priority='';state.offset=0;load();}}, 'Сбросить фильтры') : null,
      h('a', { href: '#', class: 'secondary' }, 'К анализу обращения'),
      live() && !state.items.length && state.status === 'pending' ? h('p', null, h('button', { class: 'link', type: 'button', disabled: state.busy, onclick: addSamples }, 'Добавить синтетические примеры')) : null);
    else body = h('div', null,
      h('div', { class: 'queue-columns', 'aria-hidden': 'true' }, ['Приоритет', 'Обращение / игрок', 'Категория', 'Проверка', 'Статус'].map(label => h('span', null, label))),
      h('ul', { class: 'qlist' }, items.map(t => h('li', null, h('button', { type: 'button', disabled: state.busy,
        'aria-current': String(!!state.selected && state.selected.id === t.id), onclick: () => { location.hash = '#queue/' + encodeURIComponent(t.id); } },
        prio(t.result.priority), h('span', { class: 'q-text' }, h('strong', null, L.normalizeKk(t.text, t.result.lang).text),
          h('small', null, [KIND[t.kind], t.player || 'ID не указан', ago(t.created_at)].join(' · '))),
        h('span', { class: 'q-category' }, L.CATEGORIES[t.result.category] || t.result.category),
        h('span', { class: t.result.needs_human ? 'q-human' : 'muted small' }, t.result.needs_human ? 'Нужен человек' : 'Стандартная'),
        h('span', { class: 'q-status' }, STATUS[t.status]))))));
    replaceContent($('#q-list'), h('div', { class: 'queue-list-heading' }, h('h2', null, 'Обращения'), h('span', { class: 'count' }, state.loading ? '…' : items.length + ' в списке')),
      tabs, searchForm, h('div', { class: 'chips' }, chip('Нужен человек', 'human'), chip('Срочные P0–P1', 'urgent'),
        h('button', { type: 'button', class: 'link refresh', disabled: state.loading || state.busy, onclick: load }, 'Обновить')),
      filters, body, state.total > state.limit || state.offset ? h('div', {class:'pagination', 'aria-label':'Страницы очереди'},
        h('button',{type:'button',class:'secondary',disabled:state.loading||state.busy||state.offset===0,onclick:()=>{state.offset=Math.max(0,state.offset-state.limit);load();}},'Назад'),
        h('span',null,(state.total ? state.offset+1 : 0)+'–'+Math.min(state.offset+state.items.length,state.total)+' из '+state.total),
        h('button',{type:'button',class:'secondary',disabled:state.loading||state.busy||state.offset+state.limit>=state.total,onclick:()=>{state.offset+=state.limit;load();}},'Далее')) : null);
  }
  function renderDetail() {
    const t = state.selected, box = $('#q-detail');
    $('#view-queue').classList.toggle('has-selection', !!t);
    if (!t) { replaceContent(box); return; }
    const r = t.result, sent = t.status === 'simulated_sent', norm = typeof t.normalizedText === 'string' ? {text:t.normalizedText,changed:t.normalizedText!==t.text} : L.normalizeKk(t.text, r.lang);
    const rules = new Map(t.citations.map(c => [c.code, c]));
    t.citations.forEach(c => {
      if (c.ref && !rules.has(c.ref)) rules.set(c.ref, c);
      // «32:1.1» в черновике выглядит как «1.1 GZ», проверка ищет «GZ 1.1» (так же, как в analyzer.js).
      const m = /^(\d+):(.+)$/.exec(String(c.id || ''));
      const coded = m && (m[1] === '31' ? 'ЖБ ' + m[2] : m[1] === '32' ? 'GZ ' + m[2] : null);
      if (coded && !rules.has(coded)) rules.set(coded, c);
    });
    UI.rules().forEach((v, k) => { if (!rules.has(k)) rules.set(k, v); });
    const draft = h('textarea', { class: 'draft', rows: '6', maxlength: '5000', 'aria-label': 'Черновик ответа игроку', readonly: sent || !state.editing, disabled: state.busy });
    draft.value = state.draft;
    const checks = h('ul', { class: 'checks' });
    const drawChecks = () => { const lint = L.lintDraft(draft.value, { lang: r.lang, rules, cited: [] });
      checks.replaceChildren(...lint.checks.map(c => h('li', { class: c.ok === false ? 'bad' : c.ok ? 'ok' : 'skip' }, h('b', null, c.ok === false ? '!' : c.ok ? '✓' : '–'), h('span', null, c.ok === false ? c.short || c.title : c.title)))); };
    const draftState = h('p', { class: 'draft-state', role:'status' });
    const drawState = () => { draftState.textContent = dirty() ? 'Есть несохранённые изменения' : state.editing ? 'Правки сохраняются кнопкой ниже' : 'Сохранённая версия ' + t.revision; draftState.classList.toggle('unsaved', dirty()); };
    draft.addEventListener('input', () => { state.draft = draft.value; drawChecks(); drawState(); }); drawChecks(); drawState();
    const noteInput = h('textarea', { id:'q-admin-note',rows:'2',maxlength:'3000',readonly:sent || !state.editing,disabled:state.busy,placeholder:'Комментарий для других администраторов' }); noteInput.value=state.note;
    noteInput.addEventListener('input',()=>{state.note=noteInput.value;drawState();});
    const noteEditor = h('label', { class:'field note-editor', for:'q-admin-note' }, h('span',null,'Заметка администратора'),noteInput);
    const needText = () => { if (state.draft.trim()) return true; state.msg = { bad: true, text: 'Черновик пустой.' }; renderMsg(); draft.focus(); return false; };
    const action = (label, cls, onclick) => h('button', { type: 'button', class: cls, disabled: state.busy, onclick }, label);
    let actions;
    if (sent) actions = h('p', { class: 'small muted' }, 'Симуляция зафиксирована. Реальное сообщение не отправлялось. Этот ответ больше не редактируется.');
    else if (state.escalating) {
      const note = h('textarea', { rows: '3', id: 'q-note', maxlength: String(Math.max(0,2998-state.note.length)), disabled: state.busy, placeholder: 'Что должен проверить старший администратор?' }); note.value = state.escalationReason;
      note.addEventListener('input', () => { state.escalationReason = note.value; });
      actions = h('div', { class: 'escalate' }, h('label', { for: 'q-note' }, 'Почему нужен старший администратор'), note,
        h('div', { class: 'actions' }, action('Эскалировать', 'primary', () => {
          if (!state.escalationReason.trim()) { state.msg = { bad: true, text: 'Напишите причину эскалации.' }; renderMsg(); note.focus(); return; }
          if (needText()) review({ status: 'escalated', reviewer_note: [state.note.trim(),state.escalationReason.trim()].filter(Boolean).join('\n\n'), draft_reply: state.draft }, 'Эскалация и заметка сохранены в очереди.');
        }), action('Отмена', 'secondary', () => { state.escalating = false; state.escalationReason=''; renderDetail(); })));
    } else actions = h('div', { class: 'actions' },
      state.editing ? [action('Сохранить правку', 'primary', () => { if (needText()) review({ status: 'reviewed', draft_reply: state.draft, reviewer_note: state.note }, 'Правка и заметка сохранены.'); }),
        action('Отмена', 'secondary', () => { if (dirty() && !window.confirm('Отменить несохранённые изменения черновика и заметки?')) return; state.editing = false; state.draft = t.draft; state.note=t.note; renderDetail(); })]
        : action('Править', 'primary', () => { state.editing = true; state.msg = null; renderDetail(); $('#q-detail .draft').focus(); }),
      action('Эскалировать', 'secondary', () => { state.escalating = true; state.escalationReason=''; state.msg = null; renderDetail(); $('#q-note').focus(); }),
      action('Симулировать отправку', 'secondary', () => { if (needText() && window.confirm('Зафиксировать симуляцию отправки? Сообщение НЕ будет отправлено игроку: интеграции с игрой нет. После подтверждения этот ответ нельзя редактировать.')) review({ status: 'simulated_sent', draft_reply: state.draft, reviewer_note: state.note }, 'Симуляция сохранена. Ничего не отправлено в игру.'); }));
    const section = (title, ...kids) => h('section', { class: 'block' }, h('h3', null, title), kids);
    const quote = h('blockquote', { class: 'quote', lang: r.lang === 'und' ? null : r.lang }, norm.text);
    let showRaw = false;
    replaceContent(box, h('div', { class: 'detail-topline' }, h('a', { class: 'detail-back', href: '#queue' }, 'К очереди'), h('span', { class: 'detail-id' }, t.id)),
      h('div', { class: 'detail-heading' }, h('h2', null, KIND[t.kind] + ' игрока'), h('span', { class: 'st' }, STATUS[t.status])),
      h('p', { class: 'meta-line' }, [ago(t.created_at), t.player ? 'ID ' + t.player : 'ID не указан', L.LANGS[r.lang] || r.lang, 'версия ' + t.revision].join(' · ')),
      h('table', { class: 'summary' }, h('tbody', null,
        h('tr', null, h('th', null, 'Категория'), h('td', null, L.CATEGORIES[r.category] || r.category, h('code', null, r.category))),
        h('tr', null, h('th', null, 'Приоритет'), h('td', null, prio(r.priority), ' ', L.PRIORITIES[r.priority])),
        h('tr', null, h('th', null, 'Решение'), h('td', null, h('b', { class: r.needs_human ? 'human' : 'auto' }, r.needs_human ? 'Нужен человек' : 'Стандартная проверка'),
          (r.reasons || []).length ? h('ul', { class: 'reasons' }, r.reasons.map(x => h('li', null, x))) : null)),
        t.note ? h('tr', null, h('th', null, 'Заметка'), h('td', null, t.note)) : null)),
      section('Текст игрока', quote, norm.changed ? h('button', { class: 'link', type: 'button', onclick: e => { showRaw = !showRaw; quote.textContent = showRaw ? t.text : norm.text; e.target.textContent = showRaw ? 'Показать нормализованный текст' : 'Показать оригинал'; } }, 'Показать оригинал') : null),
      section('Основание ответа', t.citations.length ? h('ul', { class: 'rules' }, t.citations.map(UI.ruleNode)) : h('p', { class: 'small muted' }, 'Подходящий пункт не найден или для этой категории правила не нужны.')),
      section('Черновик ответа',h('p',{class:'small generation-source'},'Исходный черновик: '+UI.generationLabel(t.diagnostics)), draft, draftState, checks, !state.escalating ? noteEditor : null, actions, h('p', { class: 'msg', id: 'q-msg', role: 'status' }),
        state.busy ? h('p', { role: 'status', class: 'small muted' }, 'Сохраняем решение…') : null,
        h('p', { class: 'small muted' }, 'Никакой автоматической отправки. Правки и решения сохраняются в истории обращения.'),
        state.recovery || state.recoveryNote ? h('details', { class: 'review-recovery', open:true }, h('summary', null, 'Ваш несохранённый вариант'), h('textarea', { readonly: true, rows: '4', 'aria-label': 'Несохранённый вариант черновика' }, state.recovery), state.recoveryNote ? h('textarea',{readonly:true,rows:'2','aria-label':'Несохранённая заметка'},state.recoveryNote) : null,
          !sent ? action('Вернуть мой вариант в редактор','secondary',()=>{state.draft=state.recovery;state.note=state.recoveryNote;state.editing=true;state.escalating=false;state.recovery='';state.recoveryNote='';renderDetail();$('#q-detail .draft').focus();}) : h('p',{class:'small muted'},'Симуляция уже зафиксирована другим администратором. Ваш вариант доступен для копирования.')) : null),
      section('История решений', h('div', { id: 'q-history' })));
    const summary = box.querySelector('.summary');
    const blocks = [...box.querySelectorAll(':scope > .block')];
    const textBlock = blocks[0], rulesBlock = blocks[1], draftBlock = blocks[2], historyBlock = blocks[3];
    const overview = h('div', { class: 'case-overview queue-overview' },
      h('div', null, h('span', { class: 'overview-label' }, 'Категория'), h('strong', null, L.CATEGORIES[r.category] || r.category)),
      h('div', null, h('span', { class: 'overview-label' }, 'Приоритет'), h('strong', null, prio(r.priority), ' ', L.PRIORITIES[r.priority])));
    const decision = h('details', { class: 'decision', open: r.needs_human }, h('summary', null, r.needs_human ? 'Нужен человек — причины' : 'Стандартная проверка'),
      (r.reasons || []).length ? h('ul', { class: 'reasons' }, r.reasons.map(x => h('li', null, x))) : null,
      t.note ? h('p', { class: 'small' }, 'Заметка: ' + t.note) : null);
    summary.remove();
    const sourcePane=h('div',{class:'source-pane'},textBlock,rulesBlock);
    const responsePane=h('div',{class:'response-pane'},draftBlock);
    const jumps = UI.sectionJumps('Разделы обращения', [[textBlock,'Текст'],[rulesBlock,'Правила'],[draftBlock,'Ответ'],[historyBlock,'История']]);
    box.querySelector('.meta-line').after(jumps,overview,decision,h('div',{class:'case-body'},sourcePane,responsePane));
    draftBlock.classList.add('reply-block');
    const toolbar = draftBlock.querySelector('.actions');
    if (toolbar && !state.escalating) toolbar.classList.add('editor-toolbar');
    renderMsg(); renderHistory();
  }
  function renderHistory() { const box = $('#q-history'); if (!box) return;
    replaceContent(box, state.history.length ? h('ol', { class: 'edits' }, state.history.map(x => h('li', null,
      h('span', { class: 'muted' }, ago(x.created_at)), ' ', STATUS[x.status] || x.status, x.changed ? ' · черновик изменён' : '', x.reviewer_note ? ' · ' + x.reviewer_note : '')))
      : h('p', { class: 'small muted' }, 'Пока без правок. Здесь будут сохранённые решения.'));
  }
  function renderMsg() { const el = $('#q-msg'); if (!el) return; el.textContent = state.msg ? state.msg.text : ''; el.className = 'msg' + (state.msg ? state.msg.bad ? ' bad' : ' ok' : ''); }
  async function addSamples() {
    if (state.busy) return; state.busy = true; renderList();
    try { for (const s of D.SAMPLES) await api('/api/tickets', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'ui-synthetic-sample-' + s.label },
      body: JSON.stringify({ kind: s.kind, text: '[Синтетический пример] ' + s.text, attachments_count: s.attachments, server_lang: s.server_lang }) });
      await load();
    } catch (e) { state.error = e.message; } finally { state.busy = false; renderList(); }
  }
  async function route() {
    const nextHash = location.hash;
    if (nextHash !== acceptedHash && (state.busy || dirty())) {
      if (state.busy || !window.confirm('Есть несохранённые изменения. Перейти и отменить их?')) { history.replaceState(null, '', location.pathname + location.search + acceptedHash); return; }
    }
    acceptedHash = nextHash;
    const m = /^#queue(?:\/([^?]+))?$/.exec(nextHash);
    const entering = !inQueue && !!m; inQueue = !!m;
    $('#view-analyze').hidden = !!m; $('#view-queue').hidden = !m;
    document.querySelectorAll('.nav a').forEach(a => a.setAttribute('aria-current', String((a.dataset.view === 'queue') === !!m)));
    if (!m) { selectionRequest++; state.selected = null; state.editing = false; state.escalating = false; return; }
    await UI.ready;
    if (entering) await load();
    if (location.hash !== nextHash) return;
    if (m[1]) { let id; try { id = decodeURIComponent(m[1]); } catch (_) { id = m[1]; } await select(id); }
    else { selectionRequest++; state.selected = null; state.editing = false; state.escalating = false; renderList(); renderDetail(); }
  }
  window.SC.queue = { addDemo(input, result, citations) { const id = 'D-' + (demoStore().length + 1);
    demoStore().push({ id, kind: input.kind, created_at: new Date().toISOString(), status: 'pending', revision: 1, text: input.text,
      player: input.player || null, result: JSON.parse(JSON.stringify(result)), draft: result.draft_reply.text, note: '', citations: citations.map(ruleByCode), log: [] }); return id; } };
  window.addEventListener('beforeunload', e => { if (dirty() || state.busy) { e.preventDefault(); e.returnValue = ''; } });
  window.addEventListener('copilot:connected', async () => {
    if (!inQueue) return;
    await load();
    // Reload/deep links may have failed before the in-memory token was entered.
    // Reopen the current route only when there is no active human editor to disturb.
    if (inQueue && !state.editing && !state.escalating && !state.busy) route();
  });
  window.addEventListener('hashchange', route); route();
})();
