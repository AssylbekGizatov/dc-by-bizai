import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, AlertCircle, ArrowLeft, ArrowUpRight, BookOpen, Check, CheckCheck, ChevronDown, ChevronRight, Code2, Copy, FileText, FlaskConical, Globe2, Inbox, Layers3, LoaderCircle, LockKeyhole, MessageSquare, Plus, RefreshCw, Save, Search, Send, Settings2, ShieldCheck, Sparkles, UserRound, UsersRound, X } from 'lucide-react'
import { api, setAccessToken } from './api'
import { ConfirmModal, ConnectionModal, CreateTicketModal, EmptyQueue, ErrorNotice, RuleCard, RulesModal, Spinner } from './components'
import { categoryLabel, elapsed, errorText, formatTime, languageLabels, percent, priorityLabels, shortId, statusLabels, ticketDraft } from './format'
import type { Filters, Health, Rule, Ticket, TicketStatus } from './types'

const emptyFilters: Filters = {status: '', category: '', language: '', priority: '', search: ''}
const categoryOptions = ['complaint.insult','complaint.cheat','complaint.dm','complaint.scam','complaint.rmt_ads','complaint.admin','complaint.other','complaint.invalid','report.question','report.help','report.complaint','report.account','report.payment','report.offtopic']
function getLocationId() { return new URL(window.location.href).searchParams.get('ticket') }
function setLocationId(id: string | null, replace = false) {
  const url = new URL(window.location.href)
  if (id) url.searchParams.set('ticket',id); else url.searchParams.delete('ticket')
  window.history[replace ? 'replaceState' : 'pushState']({},'',url)
}
function isAbort(err: unknown) { return err instanceof Error && err.name === 'AbortError' }

export default function App() {
  const [health,setHealth] = useState<Health | null>(null)
  const [filters,setFilters] = useState<Filters>(emptyFilters)
  const [search,setSearch] = useState('')
  const [tickets,setTickets] = useState<Ticket[]>([])
  const [total,setTotal] = useState(0)
  const [offset,setOffset] = useState(0)
  const [listLoading,setListLoading] = useState(true)
  const [listError,setListError] = useState('')
  const [revision,setRevision] = useState(0)
  const [selectedId,setSelectedId] = useState<string | null>(getLocationId)
  const [ticket,setTicket] = useState<Ticket | null>(null)
  const [detailLoading,setDetailLoading] = useState(false)
  const [detailError,setDetailError] = useState('')
  const [detailRevision,setDetailRevision] = useState(0)
  const [draft,setDraft] = useState('')
  const [textMode,setTextMode] = useState<'original' | 'normalized'>('original')
  const [busy,setBusy] = useState(false)
  const busyRef = useRef(false)
  const [mutationError,setMutationError] = useState('')
  const [toast,setToast] = useState('')
  const [showCreate,setShowCreate] = useState(false)
  const [showRules,setShowRules] = useState(false)
  const [rule,setRule] = useState<Rule | undefined>()
  const [showConnection,setShowConnection] = useState(false)
  const [confirm,setConfirm] = useState<'escalate' | 'send' | null>(null)
  const [mobileDetail,setMobileDetail] = useState(Boolean(getLocationId()))
  const dirty = Boolean(ticket && draft !== ticketDraft(ticket))
  const dirtyRef = useRef(false); dirtyRef.current = dirty

  useEffect(() => {const t = setTimeout(() => {setFilters(old => ({...old,search})); setOffset(0)},250); return () => clearTimeout(t)},[search])
  useEffect(() => {if (!toast) return; const t = setTimeout(() => setToast(''),5500); return () => clearTimeout(t)},[toast])
  useEffect(() => {
    const controller = new AbortController()
    api.health(controller.signal).then(setHealth).catch(err => {if (!isAbort(err)) setHealth(null)})
    return () => controller.abort()
  },[revision])
  useEffect(() => {
    const controller = new AbortController(); setListLoading(true); setListError('')
    api.list(filters,offset,controller.signal).then(data => {setTickets(data.items); setTotal(data.total)})
      .catch(err => {if (!isAbort(err)) setListError(errorText(err))})
      .finally(() => {if (!controller.signal.aborted) setListLoading(false)})
    return () => controller.abort()
  },[filters,offset,revision])
  useEffect(() => {
    if (!selectedId && tickets.length) {setSelectedId(tickets[0].id); setLocationId(tickets[0].id,true)}
  },[selectedId,tickets])
  useEffect(() => {
    if (!selectedId) {setTicket(null); return}
    const controller = new AbortController(); setDetailLoading(true); setDetailError(''); setMutationError(''); setTicket(null); setDraft(''); setTextMode('original')
    api.ticket(selectedId,controller.signal).then(data => {setTicket(data); setDraft(ticketDraft(data))})
      .catch(err => {if (!isAbort(err)) setDetailError(errorText(err))})
      .finally(() => {if (!controller.signal.aborted) setDetailLoading(false)})
    return () => controller.abort()
  },[selectedId,detailRevision])
  useEffect(() => {
    const unload = (e: BeforeUnloadEvent) => {if (dirtyRef.current || busyRef.current) {e.preventDefault(); e.returnValue = ''}}
    const pop = () => {
      if (busyRef.current || (dirtyRef.current && !window.confirm('В черновике есть несохранённые правки. Перейти без сохранения?'))) {setLocationId(selectedId,true); return}
      setSelectedId(getLocationId()); setMobileDetail(Boolean(getLocationId()))
    }
    window.addEventListener('beforeunload',unload); window.addEventListener('popstate',pop)
    return () => {window.removeEventListener('beforeunload',unload); window.removeEventListener('popstate',pop)}
  },[selectedId])

  const selectTicket = useCallback((id: string) => {
    if (busyRef.current) return
    if (id !== selectedId && dirtyRef.current && !window.confirm('В черновике есть несохранённые правки. Перейти без сохранения?')) return
    if (id !== selectedId) {setSelectedId(id); setLocationId(id)}
    setMobileDetail(true)
  },[selectedId])
  function changeFilter(key: keyof Filters,value: string) {setFilters(old => ({...old,[key]:value})); setOffset(0)}
  function resetFilters() {setSearch(''); setFilters(emptyFilters); setOffset(0)}
  function refreshDetail() {
    if (busyRef.current || (dirty && !window.confirm('Обновить обращение и заменить несохранённый черновик версией сервера?'))) return
    setDetailRevision(n => n + 1)
  }
  async function review(status: TicketStatus,note?: string) {
    if (!ticket || busyRef.current || !draft.trim()) return
    busyRef.current = true; setBusy(true); setMutationError('')
    try {
      const updated = await api.review(ticket.id,{draft_reply: draft.trim(),status,reviewer_note: note ?? ticket.reviewer_note,expected_revision: ticket.revision})
      setTicket(updated); setDraft(ticketDraft(updated)); setConfirm(null); setRevision(n => n + 1)
      setToast(status === 'escalated' ? 'Обращение эскалировано в локальной очереди.' : status === 'simulated_sent' ? 'Симуляция сохранена. Реальное сообщение не отправлялось.' : 'Правки и проверка сохранены.')
    } catch(err) {setMutationError(errorText(err))}
    finally {busyRef.current = false; setBusy(false)}
  }
  function onCreated(created: Ticket) {
    setShowCreate(false); resetFilters(); setSelectedId(created.id); setLocationId(created.id); setMobileDetail(true); setRevision(n => n + 1)
    setToast('Обращение обработано. Проверьте факты, правила и черновик.')
  }
  async function copyId() {
    if (!ticket) return
    try {await navigator.clipboard.writeText(ticket.id); setToast('ID обращения скопирован.')}
    catch {setToast('Копирование недоступно в этом браузере. ID указан в заголовке обращения.')}
  }
  function openCreate() {if (!dirty || window.confirm('Открыть новое обращение? Несохранённые правки текущего черновика будут потеряны после создания.')) setShowCreate(true)}
  const filtered = Object.values(filters).some(Boolean)
  const stats = useMemo(() => ({human:tickets.filter(t => t.result.needs_human).length,urgent:tickets.filter(t => ['p0','p1'].includes(t.result.priority)).length,languages:new Set(tickets.map(t => t.result.lang).filter(lang => lang !== 'und')).size}),[tickets])
  const categories = [...new Set([...categoryOptions,...tickets.map(t => t.result.category)])]
  const result = ticket?.result
  const generationMode = ticket?.diagnostics?.generation_mode || health?.generation_mode || '—'

  return <div className="app-shell">
    <a className="skip-link" href="#main">Перейти к обращениям</a>
    <aside className="sidebar" aria-label="Основная навигация">
      <a className="brand" aria-label="Grand Mobile — Support Copilot" href="./" onClick={e => {e.preventDefault(); setMobileDetail(false)}}><span className="brand-mark"><Sparkles size={23} strokeWidth={1.65}/></span><span><strong>GRAND MOBILE</strong><small>Support Copilot</small></span></a>
      <div className="workspace-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <nav><button className="nav-item active" aria-label="Обращения" onClick={() => setMobileDetail(false)}><Inbox size={18}/><span>Обращения</span><span className="nav-count">{total}</span></button>
        <button className="nav-item" aria-label="База правил" onClick={() => {setRule(undefined); setShowRules(true)}}><BookOpen size={18}/><span>База правил</span><ArrowUpRight size={13}/></button>
        <button className="nav-item" aria-label="Тестовый стенд" onClick={openCreate} disabled={busy}><FlaskConical size={18}/><span>Тестовый стенд</span><Plus size={14}/></button></nav>
      <div className="sidebar-divider"/><div className="workspace-label">ПОДХОД COPILOT</div>
      <div className="workflow"><div><span>01</span><p>Понять обращение</p></div><div><span>02</span><p>Найти основание</p></div><div><span>03</span><p>Помочь с ответом</p></div><div className="human-step"><ShieldCheck size={16}/><p>Решение — за человеком</p></div></div>
      <div className="sidebar-bottom"><div className="safe-card"><span className="safe-icon"><LockKeyhole size={18}/></span><strong>Безопасный контур</strong><p>Никаких наказаний, возвратов или сообщений без интеграции.</p><span className="demo-label"><span/> ЛОКАЛЬНЫЙ MVP</span></div>
        <button className="connection-button" aria-label="Настройки подключения" onClick={() => setShowConnection(true)}><span className={`status-dot ${health ? 'online' : ''}`}/><span>{health ? 'Сервис подключён' : 'Проверить подключение'}</span><Settings2 size={15}/></button></div>
    </aside>

    <div className="workspace">
      <header className="topbar"><div className="breadcrumbs"><span>Рабочее пространство</span><ChevronRight size={14}/><strong>Поддержка игроков</strong></div>
        <div className="topbar-right"><button className="environment-pill" onClick={() => setShowConnection(true)}><span className={`status-dot ${health ? 'online' : ''}`}/><span>{health ? 'API подключён' : 'API недоступен'}</span></button><span className="topbar-separator"/><div className="operator"><span className="avatar">М</span><span><strong>Модератор</strong><small>Локальная сессия</small></span></div></div></header>
      <main id="main">
        <section className="page-heading"><div><div className="eyebrow">ПОДДЕРЖКА БЕЗ ШУМА</div><h1>Очередь обращений<span className="title-dot"/></h1><p>Copilot готовит черновик. Вы принимаете решение.</p></div><button className="button primary" onClick={openCreate} disabled={busy}><Plus size={17}/><span>Новое обращение</span></button></section>
        <div className="demo-banner"><FlaskConical size={16}/><span><strong>Тестовый контур.</strong> Отправка только симулируется; сообщения не уходят игрокам.{health && !health.real_rules_loaded && ' База правил — синтетическая.'}</span><button onClick={() => setShowConnection(true)} aria-label="Подробнее о тестовом контуре"><ArrowUpRight size={15}/></button></div>
        <section className="stats-grid" aria-label="Статистика текущей выборки"><Stat label="Обращений в выборке" value={listError || (listLoading && !tickets.length) ? '—' : String(total)} icon={<Inbox size={20}/>} foot={filtered ? 'С учётом фильтров' : 'Все статусы'} />
          <Stat label="Нужен человек" value={listError || (listLoading && !tickets.length) ? '—' : String(stats.human)} icon={<UsersRound size={20}/>} foot="В загруженной странице" amber/>
          <Stat label="Высокий приоритет" value={listError || (listLoading && !tickets.length) ? '—' : String(stats.urgent)} icon={<Activity size={20}/>} foot="P0 и P1 · на странице"/>
          <Stat label="Языков обращений" value={listError || (listLoading && !tickets.length) ? '—' : String(stats.languages)} icon={<Globe2 size={20}/>} foot="В загруженной странице"/></section>
        <section className="queue-workspace" aria-label="Работа с обращениями">
          <div className="queue-toolbar"><div className="toolbar-title"><Inbox size={18}/><h2>Входящие</h2><span>{total}</span></div><div className="toolbar-actions"><button className="icon-button" aria-label="Открыть базу правил" title="База правил" onClick={() => {setRule(undefined); setShowRules(true)}}><BookOpen size={16}/></button><span className="auto-note"><ShieldCheck size={14}/> Все ответы требуют проверки</span><button className="icon-button" aria-label="Обновить очередь" title="Обновить очередь" disabled={listLoading} onClick={() => setRevision(n => n + 1)}><RefreshCw size={16} className={listLoading ? 'spin' : ''}/></button></div></div>
          <div className="filters"><label className="search-field"><Search size={16}/><input aria-label="Поиск по обращениям" maxLength={200} value={search} onChange={e => setSearch(e.target.value)} placeholder="Поиск по тексту или ID…"/>{search && <button onClick={() => setSearch('')} aria-label="Очистить поиск"><X size={13}/></button>}</label>
            <FilterSelect label="Статус" value={filters.status} onChange={v => changeFilter('status',v)} options={Object.entries(statusLabels)}/>
            <FilterSelect label="Язык" value={filters.language} onChange={v => changeFilter('language',v)} options={Object.entries(languageLabels)}/>
            <FilterSelect label="Категория" value={filters.category} onChange={v => changeFilter('category',v)} options={categories.map(x => [x,categoryLabel(x)])}/>
            <FilterSelect label="Приоритет" value={filters.priority} onChange={v => changeFilter('priority',v)} options={Object.entries(priorityLabels).map(([key,label]) => [key,`${key.toUpperCase()} · ${label}`])}/>
            {filtered && <button className="reset-filters" onClick={resetFilters} title="Сбросить фильтры" aria-label="Сбросить фильтры"><X size={15}/></button>}</div>
          <div className={`three-columns ${mobileDetail ? 'show-detail' : ''}`}>
            <section className="ticket-queue" aria-label="Список обращений" aria-busy={listLoading}>
              <div className="list-caption"><span>{filtered ? 'Результаты поиска' : 'Последние обращения'}</span><span>{tickets.length} / {total}</span></div>
              {listError ? <div className="queue-error"><ErrorNotice message={listError} onRetry={() => setRevision(n => n + 1)}/><button className="text-button" onClick={() => setShowConnection(true)}>Настройки подключения <ArrowUpRight size={14}/></button></div>
              : listLoading && !tickets.length ? <div className="queue-skeleton" aria-label="Загрузка очереди">{[0,1,2,3].map(x => <div key={x}><i/><i/><i/></div>)}</div>
              : !tickets.length ? <EmptyQueue filtered={filtered} onClear={resetFilters} onCreate={openCreate}/>
              : <div className={`ticket-list ${listLoading ? 'is-refreshing' : ''}`} role="list">{tickets.map(item => <div key={item.id} role="listitem"><button className={`ticket-row ${selectedId === item.id ? 'selected' : ''}`} onClick={() => selectTicket(item.id)} disabled={busy} aria-current={selectedId === item.id ? 'true' : undefined}>
                <div className="ticket-row-top"><span className={`priority-dot ${item.result.priority}`}/><span className="ticket-id">#{shortId(item.id)}</span><span className="ticket-time">{formatTime(item.created_at)}</span></div>
                <h3>{categoryLabel(item.result.category)}</h3><p>{item.text}</p><div className="ticket-tags"><span className={`mini-status ${item.status}`}>{statusLabels[item.status]}</span><span className="language-tag">{item.result.lang.toUpperCase()}</span>{item.result.needs_human && <span className="human-indicator" title="Нужен человек" aria-label="Нужен человек"><UserRound size={13}/></span>}</div>
              </button></div>)}</div>}
              {total > 100 && <div className="pagination"><button disabled={!offset || listLoading} onClick={() => setOffset(n => Math.max(0,n - 100))} aria-label="Предыдущая страница"><ArrowLeft size={14}/></button><span>{offset + 1}–{Math.min(offset + 100,total)}</span><button disabled={offset + 100 >= total || listLoading} onClick={() => setOffset(n => n + 100)} aria-label="Следующая страница"><ChevronRight size={14}/></button></div>}
              <div className="queue-foot"><LockKeyhole size={12}/> Работа через ваш API</div>
            </section>

            <section className="ticket-detail" aria-label="Детали обращения" aria-busy={detailLoading}>
              <button className="mobile-back text-button" onClick={() => setMobileDetail(false)}><ArrowLeft size={15}/> Назад к очереди</button>
              {detailLoading ? <div className="detail-loading"><Spinner label="Открываем обращение…"/><div className="detail-skeleton"><i/><i/><i/></div></div>
              : detailError ? <div className="detail-error"><ErrorNotice message={detailError} onRetry={refreshDetail}/></div>
              : !ticket || !result ? <div className="detail-empty"><div className="detail-empty-icon"><MessageSquare size={30}/><Sparkles size={17}/></div><h3>Каждому обращению —<br/>внимательный ответ</h3><p>Выберите обращение слева или создайте тестовый пример. Здесь появятся факты и черновик.</p><div className="empty-flow"><span><FileText size={15}/> Текст</span><ChevronRight size={14}/><span><BookOpen size={15}/> Правила</span><ChevronRight size={14}/><span><CheckCheck size={15}/> Ответ</span></div></div>
              : <><div className="detail-header"><div><div className="detail-id-line"><span className="detail-id" title={ticket.id}>#{shortId(ticket.id)}</span><button className="icon-button tiny" onClick={copyId} title="Скопировать полный ID" aria-label="Скопировать полный ID"><Copy size={13}/></button><span className={`mini-status ${ticket.status}`}>{statusLabels[ticket.status]}</span></div><h2>{categoryLabel(result.category)}</h2><div className="ticket-context"><span>{ticket.kind === 'complaint' ? 'Жалоба на игрока' : 'Внутриигровой репорт'}</span><span>·</span><span>{formatTime(ticket.created_at)}</span></div></div>
                <button className="icon-button" onClick={refreshDetail} disabled={busy} aria-label="Обновить обращение" title="Обновить обращение"><RefreshCw size={15}/></button></div>
              <div className="detail-body">{!listLoading && !listError && !tickets.some(item => item.id === ticket.id) && <div className="outside-filter">Это обращение вне текущей выборки. <button onClick={resetFilters}>Сбросить фильтры</button></div>}<section className="message-section"><div className="section-label"><span><MessageSquare size={15}/> Сообщение игрока</span><div className="text-tabs" role="tablist" aria-label="Представление текста" onKeyDown={e => {if (['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) {e.preventDefault(); const next = e.key === 'Home' ? 'original' : e.key === 'End' ? 'normalized' : textMode === 'original' ? 'normalized' : 'original'; setTextMode(next); document.getElementById(`${next}-tab`)?.focus()}}}><button role="tab" tabIndex={textMode === 'original' ? 0 : -1} id="original-tab" aria-controls="message-text" aria-selected={textMode === 'original'} className={textMode === 'original' ? 'active' : ''} onClick={() => setTextMode('original')}>Оригинал</button><button role="tab" tabIndex={textMode === 'normalized' ? 0 : -1} id="normalized-tab" aria-controls="message-text" aria-selected={textMode === 'normalized'} className={textMode === 'normalized' ? 'active' : ''} onClick={() => setTextMode('normalized')}>Нормализация{ticket.text !== ticket.normalized_text && <i/>}</button></div></div>
                <div className="player-message" role="tabpanel" id="message-text" aria-labelledby={`${textMode}-tab`}><span className="message-avatar"><UserRound size={16}/></span><div><p>{textMode === 'original' ? ticket.text : ticket.normalized_text}</p><div className="message-footer"><span>{ticket.player_id || 'ID игрока не указан'}</span><span>{ticket.attachments_count ? `${ticket.attachments_count} влож. заявлено` : 'Без вложений'}</span></div></div></div>
                {textMode === 'normalized' && <p className="normalization-note"><Check size={12}/>{ticket.text === ticket.normalized_text ? 'Замены не потребовались.' : 'Показан нормализованный текст; оригинал сохранён.'}</p>}</section>
              <section className="triage-section"><div className="section-label"><span><Sparkles size={15}/> Результат триажа</span>{result.is_spam_or_duplicate && <span className="pill amber">Спам / повтор</span>}</div><div className="triage-grid"><div><span>Язык</span><strong><Globe2 size={14}/>{languageLabels[result.lang] || result.lang}</strong></div><div><span>Приоритет</span><strong><i className={`priority-dot ${result.priority}`}/>{result.priority.toUpperCase()} · {priorityLabels[result.priority]}</strong></div><div title="Уверенность системы, а не измеренная точность на валидации"><span>Уверенность модели</span><strong>{percent(result.confidence)}<span className="confidence-track"><i style={{width: percent(result.confidence)}}/></span></strong></div></div></section>
              <section className="facts-section"><div className="section-label"><span><Layers3 size={15}/> Извлечено из текста</span><span className="subtle-label">не подтверждённые факты</span></div><dl className="facts-grid"><div><dt>Упомянутый игрок</dt><dd>{result.extracted.nickname || 'Не указан'}</dd></div><div><dt>Сервер</dt><dd>{result.extracted.server || ticket.server || 'Не указан'}</dd></div><div><dt>Пункты со слов игрока</dt><dd>{result.extracted.rule_refs?.length ? result.extracted.rule_refs.join(', ') : 'Не указаны'}</dd></div><div><dt>Доказательства заявлены</dt><dd>{result.extracted.has_evidence ? 'Да · не проверены' : 'Нет / не указаны'}</dd></div></dl></section>
              <section className="draft-section"><div className="draft-heading"><div className="draft-icon"><Sparkles size={17}/></div><div><h3>Черновик ответа</h3><span>{languageLabels[result.draft_reply.lang] || result.draft_reply.lang} · {generationMode === 'local' || generationMode.includes('template') ? 'Локальный шаблон' : generationMode}</span></div><span className="draft-badge">COPILOT</span></div>
                <label className="sr-only" htmlFor="draft-text">Редактировать черновик ответа</label><textarea id="draft-text" value={draft} onChange={e => setDraft(e.target.value)} disabled={busy} maxLength={5000} rows={7}/><div className="draft-caption"><span className={dirty ? 'unsaved' : ''}>{dirty ? <><span/> Есть несохранённые правки</> : <><Check size={13}/> {ticket.status === 'pending' ? 'Готов к вашей проверке' : 'Версия сохранена'}</>}</span><span>{draft.length} / 5 000</span></div>
                <div className="draft-warning"><ShieldCheck size={14}/><span>Это черновик, не решение. Проверьте утверждения и ссылки перед сохранением.</span></div></section>
              {mutationError && !confirm && <ErrorNotice message={mutationError} onRetry={refreshDetail}/>}
              {ticket.reviewer_note && <div className="reviewer-note"><span><UserRound size={14}/> Заметка модератора</span><p>{ticket.reviewer_note}</p></div>}
              <details className="diagnostics"><summary><Code2 size={14}/><span>Как подготовлен ответ</span><ChevronDown size={14}/></summary><div className="diagnostics-body"><dl><div><dt>Язык</dt><dd>{ticket.diagnostics?.language_method || '—'}</dd></div><div><dt>Классификация</dt><dd>{ticket.diagnostics?.classifier_method || '—'}</dd></div><div><dt>Поиск</dt><dd>{ticket.diagnostics?.retrieval_method || '—'}</dd></div><div><dt>Генерация</dt><dd>{generationMode}</dd></div>{Object.entries(ticket.diagnostics?.timings_ms || {}).map(([key,value]) => <div key={key}><dt>{key}</dt><dd>{elapsed(value)}</dd></div>)}<div><dt>Стоимость API</dt><dd>{ticket.diagnostics?.estimated_cost_usd == null ? 'Не рассчитана' : `$${ticket.diagnostics.estimated_cost_usd.toFixed(6)}`}</dd></div><div><dt>Токены: вход / выход</dt><dd>{ticket.diagnostics?.tokens ? `${ticket.diagnostics.tokens.input} / ${ticket.diagnostics.tokens.output}` : '—'}</dd></div><div><dt>Версия записи</dt><dd>{ticket.revision}</dd></div></dl>{Boolean(ticket.diagnostics?.warnings?.length) && <ul>{ticket.diagnostics.warnings?.map((x,i) => <li key={i}>{x}</li>)}</ul>}<p>Уверенность модели не является accuracy или F1. Стоимость API не включает работу инфраструктуры.</p></div></details>
              </div><div className="detail-actions"><button className="button secondary save-button" disabled={busy || !draft.trim() || (!dirty && ticket.status === 'reviewed')} onClick={() => review('reviewed')}>{busy && !confirm ? <LoaderCircle size={15} className="spin"/> : <Save size={15}/>} Сохранить проверку</button><button className="button escalation" disabled={busy || !draft.trim() || ticket.status === 'escalated'} onClick={() => {setMutationError(''); setConfirm('escalate')}}><ArrowUpRight size={15}/> Эскалировать</button><button className="button primary send-button" disabled={busy || !draft.trim() || ticket.status === 'simulated_sent'} onClick={() => {setMutationError(''); setConfirm('send')}}><Send size={14}/> Симуляция</button></div></>}
            </section>

            <aside className="evidence-panel" aria-label="Проверка и источники"><div className="evidence-heading"><ShieldCheck size={17}/><h2>Контроль ответа</h2></div>
              {ticket && result && !detailLoading ? <><div className={`human-card ${result.needs_human ? 'needs-human' : 'review-card'}`}><div className="human-card-title">{result.needs_human ? <UserRound size={19}/> : <ShieldCheck size={19}/>}<h3>{result.needs_human ? 'Нужен человек' : 'Можно проверить ответ'}</h3></div><p>{result.needs_human ? 'Автоматическое решение запрещено. Сначала — проверка модератора.' : 'Критичных ограничений не обнаружено. Финальное решение всё равно за вами.'}</p>{result.reasons.length > 0 && <ul>{result.reasons.map((reason,i) => <li key={i}>{reason}</li>)}</ul>}</div>
                <div className="sources-title"><h3><BookOpen size={15}/> Источники RAG</h3><span>{ticket.citations.length}</span></div><p className="source-explanation">Проверьте, что каждый пункт относится к ситуации.</p>
                {ticket.citations.length ? <div className="source-cards">{ticket.citations.map(citation => <RuleCard key={citation.id} rule={citation} onOpen={item => {setRule(item); setShowRules(true)}}/>)}</div> : <div className="no-citations"><BookOpen size={21}/><p>Релевантные правила не приведены.</p><span>Не добавляйте пункты по памяти. При необходимости передайте обращение человеку.</span></div>}
                <div className="evidence-disclaimer"><AlertCircle size={15}/><p>Текст игрока — заявление, не доказательство. Copilot не видит скриншоты и не проверяет игровые логи.</p></div>
                {result.draft_reply.cited.length > 0 && <div className="cited-ids"><span>Ссылки в черновике</span>{result.draft_reply.cited.map(id => <code key={id}>{id}</code>)}</div>}
              </> : <div className="evidence-empty"><div className="source-placeholder"><i/><i/><i/></div><BookOpen size={24}/><h3>Основание важнее догадок</h3><p>Здесь появятся найденные правила и причины для передачи человеку.</p><button className="text-button" onClick={() => {setRule(undefined); setShowRules(true)}}>Открыть базу правил <ArrowUpRight size={14}/></button></div>}
              <div className="evidence-foot"><ShieldCheck size={13}/><span>Ни одного обещания без проверки</span></div>
            </aside>
          </div>
        </section>
        <footer className="page-footer"><span>Grand Mobile × Decentrathon 6.0</span><span>Support Copilot <span>·</span> Human-in-the-loop</span></footer>
      </main>
    </div>
    {showCreate && <CreateTicketModal onClose={() => setShowCreate(false)} onCreated={onCreated}/>}
    {showRules && <RulesModal onClose={() => setShowRules(false)} initialRule={rule}/>}
    {showConnection && <ConnectionModal health={health} onClose={() => setShowConnection(false)} onConnect={token => {if (dirty && !window.confirm('Применить подключение и загрузить серверную версию? Несохранённые правки будут потеряны.')) return; setAccessToken(token); setShowConnection(false); setRevision(n => n + 1); setDetailRevision(n => n + 1); setToast('Настройки подключения применены к текущей вкладке.')}}/>}
    {confirm && <ConfirmModal kind={confirm} busy={busy} error={mutationError} onClose={() => {setConfirm(null); setMutationError('')}} onConfirm={note => review(confirm === 'escalate' ? 'escalated' : 'simulated_sent',note)}/>}
    {toast && <div className="toast" role="status"><span><Check size={16}/></span><p>{toast}</p><button onClick={() => setToast('')} aria-label="Закрыть уведомление"><X size={15}/></button></div>}
  </div>
}
function Stat({label,value,icon,foot,amber = false}: {label: string; value: string; icon: React.ReactNode; foot: string; amber?: boolean}) {
  return <div className={`stat-card ${amber ? 'stat-amber' : ''}`}><div className="stat-top"><span>{label}</span><span className="stat-icon">{icon}</span></div><div className="stat-value">{value}<span>{foot}</span></div></div>
}
function FilterSelect({label,value,onChange,options}: {label: string; value: string; onChange: (value: string) => void; options: string[][]}) {
  return <label className={`filter-select ${value ? 'has-value' : ''}`}><span className="sr-only">{label}</span><select aria-label={label} value={value} onChange={e => onChange(e.target.value)}><option value="">{label}</option>{options.map(([key,text]) => <option key={key} value={key}>{text}</option>)}</select><ChevronDown size={13}/></label>
}
