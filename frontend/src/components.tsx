import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { AlertCircle, ArrowRight, BookOpen, Check, ChevronRight, FileText, FlaskConical, KeyRound, LoaderCircle, Plus, Search, ShieldCheck, Sparkles, X } from 'lucide-react'
import { api } from './api'
import { errorText, languageLabels } from './format'
import { samples } from './samples'
import type { CreateTicket, Health, Rule, Ticket } from './types'

export function Spinner({label = 'Загрузка…'}: {label?: string}) {
  return <span className="spinner-line" role="status"><LoaderCircle size={16} className="spin" aria-hidden="true" />{label}</span>
}
export function ErrorNotice({message, onRetry}: {message: string; onRetry?: () => void}) {
  return <div className="error-notice" role="alert"><AlertCircle size={18} aria-hidden="true"/><div>{message}{onRetry && <button className="text-button" onClick={onRetry}>Попробовать снова <ArrowRight size={13}/></button>}</div></div>
}
export function Modal({title, description, onClose, busy = false, wide = false, children}: {
  title: string; description?: string; onClose: () => void; busy?: boolean; wide?: boolean; children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {const el = ref.current; el?.showModal(); return () => el?.close()}, [])
  return <dialog ref={ref} className={`modal ${wide ? 'modal-wide' : ''}`} aria-labelledby="modal-title" aria-describedby={description ? 'modal-desc' : undefined}
    onCancel={e => {e.preventDefault(); if (!busy) onClose()}}
    onMouseDown={e => {if (e.target === e.currentTarget && !busy) onClose()}}>
    <div className="modal-inner"><div className="modal-header"><div><h2 id="modal-title">{title}</h2>{description && <p id="modal-desc">{description}</p>}</div>
      <button type="button" className="icon-button" aria-label="Закрыть окно" onClick={onClose} disabled={busy}><X size={20}/></button></div>{children}</div>
  </dialog>
}
export function CreateTicketModal({onClose, onCreated}: {onClose: () => void; onCreated: (ticket: Ticket) => void}) {
  const [data, setData] = useState<CreateTicket>({kind: 'complaint', text: '', player_id: '', server: '', attachments_count: 0, server_lang: ''})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const busyRef = useRef(false)
  const submission = useRef<{payload: string; key: string} | null>(null)
  function update<K extends keyof CreateTicket>(key: K, value: CreateTicket[K]) {setData(old => ({...old, [key]: value})); setError('')}
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (busyRef.current) return
    const body = {...data, text: data.text.trim(), player_id: data.player_id?.trim() || undefined, server: data.server?.trim() || undefined, server_lang: data.server_lang || undefined}
    if (body.text.length < 3) {setError('Опишите ситуацию хотя бы в трёх символах.'); return}
    const payload = JSON.stringify(body)
    if (submission.current?.payload !== payload) submission.current = {payload, key: crypto.randomUUID()}
    busyRef.current = true; setBusy(true); setError('')
    try { onCreated(await api.create(body, submission.current.key)) }
    catch (err) {setError(errorText(err))}
    finally {busyRef.current = false; setBusy(false)}
  }
  return <Modal title="Новое тестовое обращение" description="Проверьте полный путь: от текста игрока до черновика с правилами." onClose={onClose} busy={busy} wide>
    <form onSubmit={submit} className="create-form">
      <div className="sample-heading"><FlaskConical size={15}/><span>Синтетические примеры</span></div>
      <div className="sample-grid">{samples.map((sample, i) => <button type="button" key={sample.label} className="sample-card" aria-label={`${sample.label} — ${sample.caption}`} onClick={() => {setData({...sample.data}); setError('')}} disabled={busy}>
        <span className="sample-number">0{i + 1}</span><strong>{sample.label}</strong><small>{sample.caption}</small><ChevronRight size={14}/>
      </button>)}</div>
      <div className="form-row"><label>Канал<select value={data.kind} onChange={e => update('kind', e.target.value as CreateTicket['kind'])} disabled={busy}>
        <option value="complaint">Жалоба на игрока</option><option value="report">Внутриигровой репорт</option></select></label>
        <label>Язык сервера<select value={data.server_lang} onChange={e => update('server_lang', e.target.value)} disabled={busy}>
          <option value="">Не указан</option>{Object.entries(languageLabels).filter(([k]) => k !== 'und').map(([key,label]) => <option value={key} key={key}>{label}</option>)}</select></label></div>
      <label>Текст игрока <span className="required">*</span><textarea name="ticket-text" value={data.text} onChange={e => update('text', e.target.value)} rows={5} maxLength={8000} required disabled={busy} placeholder="Опишите тестовую ситуацию или выберите пример выше…"/></label>
      <div className="field-hint"><span>Не вводите реальные персональные или платёжные данные.</span><span>{data.text.length.toLocaleString('ru')} / 8 000</span></div>
      <div className="form-row three"><label>Синтетический ID игрока<input value={data.player_id} maxLength={128} onChange={e => update('player_id',e.target.value)} disabled={busy} placeholder="synthetic-player-001"/></label>
        <label>Сервер<input value={data.server} maxLength={100} onChange={e => update('server',e.target.value)} disabled={busy} placeholder="demo-kz-01"/></label>
        <label>Кол-во вложений<input type="number" min={0} max={20} value={data.attachments_count} onChange={e => update('attachments_count',Math.max(0,Math.min(20,Number(e.target.value))))} disabled={busy}/></label></div>
      <div className="subtle-note"><ShieldCheck size={16}/><span>Вложения не загружаются и не просматриваются. Их количество — только заявление игрока, не доказательство нарушения.</span></div>
      {error && <ErrorNotice message={error}/>}
      {busy && <div className="processing-notice"><Spinner label="Обрабатываем текст, ищем правила и готовим черновик…"/></div>}
      <div className="modal-footer"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>Отмена</button><button type="submit" className="button primary" disabled={busy || !data.text.trim()}>{busy ? <LoaderCircle size={16} className="spin"/> : <Sparkles size={16}/>}Обработать обращение</button></div>
    </form>
  </Modal>
}
export function RuleCard({rule, onOpen}: {rule: Rule; onOpen: (rule: Rule) => void}) {
  return <button className="rule-card" onClick={() => onOpen(rule)}><div className="rule-card-top"><span className="rule-ref"><BookOpen size={13}/>{rule.ref || rule.id}</span><ChevronRight size={15}/></div>
    <strong>{rule.title || rule.section}</strong><p>{rule.section}</p><span className="rule-excerpt">{rule.text}</span>
    <span className={rule.synthetic ? 'rule-source synthetic' : 'rule-source'}>{rule.synthetic ? <FlaskConical size={12}/> : <FileText size={12}/>} {rule.synthetic ? 'Синтетическое демо-правило' : rule.source || 'Локальная база правил'}</span></button>
}
export function RuleContent({rule}: {rule: Rule}) {
  return <article className="rule-content"><div className="rule-meta"><span className="pill blue"><BookOpen size={13}/> Пункт {rule.ref || '—'}</span>{rule.synthetic && <span className="pill amber"><FlaskConical size={13}/> Синтетическое правило</span>}</div>
    <h3>{rule.title}</h3><p className="rule-section">{rule.section}</p><div className="rule-fulltext">{rule.text}</div>
    <dl className="source-meta"><div><dt>Уникальный ID</dt><dd><code>{rule.id}</code></dd></div><div><dt>Источник</dt><dd>{rule.source || 'Локальная база правил'}</dd></div></dl>
    {rule.synthetic && <div className="warning-inline"><AlertCircle size={16}/>Это тестовое правило, а не действующее правило Grand Mobile. Не используйте его для решений по реальным игрокам.</div>}
  </article>
}
export function RulesModal({onClose, initialRule}: {onClose: () => void; initialRule?: Rule}) {
  const [rules, setRules] = useState<Rule[]>([])
  const [selected, setSelected] = useState<Rule | null>(initialRule || null)
  const [search, setSearch] = useState('')
  const [error,setError] = useState('')
  const [loading,setLoading] = useState(!initialRule)
  const [retry,setRetry] = useState(0)
  useEffect(() => {
    if (initialRule) return
    const controller = new AbortController(); setLoading(true); setError('')
    api.rules(controller.signal).then(data => setRules(data.items)).catch(err => {if (err.name !== 'AbortError') setError(errorText(err))}).finally(() => {if (!controller.signal.aborted) setLoading(false)})
    return () => controller.abort()
  }, [initialRule,retry])
  const query = search.trim().toLowerCase()
  const visible = rules.filter(rule => `${rule.id} ${rule.ref} ${rule.title} ${rule.section} ${rule.text}`.toLowerCase().includes(query))
  return <Modal title={initialRule ? 'Источник черновика' : 'База правил'} description="Ссылка всегда включает раздел: одинаковые номера пунктов могут означать разные правила." onClose={onClose} wide>
    {selected ? <><RuleContent rule={selected}/>{!initialRule && <div className="modal-footer"><button className="button secondary" onClick={() => setSelected(null)}>К списку правил</button></div>}</> : <div className="rules-browser">
      <label className="search-field"><Search size={16}/><input aria-label="Поиск по базе правил" placeholder="Номер, раздел или текст правила" value={search} onChange={e => setSearch(e.target.value)}/></label>
      {loading ? <div className="center-state"><Spinner label="Загружаем правила…"/></div> : error ? <ErrorNotice message={error} onRetry={() => setRetry(n => n + 1)}/> : <><div className="rules-count">{visible.length} из {rules.length} правил</div><div className="rules-results">{visible.map(rule => <RuleCard key={rule.id} rule={rule} onOpen={setSelected}/>)}</div>{!visible.length && <div className="center-state"><BookOpen size={28}/><h3>Правила не найдены</h3><p>Попробуйте другой номер или ключевое слово.</p></div>}</>}
    </div>}
  </Modal>
}
export function ConnectionModal({health,onClose,onConnect}: {health: Health | null; onClose: () => void; onConnect: (token: string) => void}) {
  const [token,setToken] = useState('')
  return <Modal title="Подключение к сервису" description="Браузер работает только с вашим сервером. Ключ Groq здесь не нужен." onClose={onClose}>
    <div className="connection-summary"><div className="connection-icon"><ShieldCheck size={24}/></div><div><strong>{health ? 'API доступен' : 'Нет подключения к API'}</strong><p>Same-origin API · /api</p></div><span className={`status-dot ${health ? 'online' : ''}`}/></div>
    <dl className="connection-details"><div><dt>Правила в базе</dt><dd>{health?.rules_count ?? '—'}</dd></div><div><dt>Генерация</dt><dd>{health?.generation_mode || '—'}</dd></div><div><dt>Данные правил</dt><dd>{health ? health.real_rules_loaded ? 'Локальная база' : 'Синтетические примеры' : '—'}</dd></div></dl>
    <form onSubmit={e => {e.preventDefault(); onConnect(token)}}><label>Токен доступа к вашему API<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} placeholder="Только если включена авторизация" maxLength={1024}/></label>
      <p className="input-caption">Токен хранится только в памяти вкладки и исчезнет после перезагрузки. Не вводите ключи провайдеров моделей. При включённом Groq сервер отправляет обезличенный контекст провайдеру.</p>
      <div className="modal-footer"><button className="button secondary" type="button" onClick={onClose}>Закрыть</button><button className="button primary" type="submit"><KeyRound size={15}/>Применить</button></div></form>
  </Modal>
}
export function ConfirmModal({kind,busy,error,onClose,onConfirm}: {kind: 'escalate' | 'send'; busy: boolean; error: string; onClose: () => void; onConfirm: (note: string) => void}) {
  const [note,setNote] = useState('')
  const [checked,setChecked] = useState(false)
  const escalate = kind === 'escalate'
  return <Modal title={escalate ? 'Передать на дополнительную проверку' : 'Симулировать отправку ответа'} description={escalate ? 'Причина и правки сохранятся в истории обращения.' : 'Это локальная симуляция. Игрок не получит сообщение, игра не изменится.'} onClose={onClose} busy={busy}>
    <form onSubmit={e => {e.preventDefault(); onConfirm(note)}}><div className="warning-inline"><ShieldCheck size={18}/>{escalate ? 'Сервис не уведомляет внешнюю команду. Изменится только статус в этой очереди.' : 'Проверьте факты, язык и ссылки. Ни одно действие не назначает наказание, не снимает блокировку и не возвращает средства.'}</div>
      <label>Комментарий модератора {escalate && <span className="required">*</span>}<textarea value={note} onChange={e => setNote(e.target.value)} placeholder={escalate ? 'Почему нужен человек или дополнительная проверка?' : 'Необязательная заметка о проверке'} rows={3} maxLength={2000} required={escalate} disabled={busy}/></label>
      {!escalate && <label className="check-label"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)} disabled={busy}/><span>Я проверил(а) черновик и понимаю, что это симуляция.</span></label>}
      {error && <ErrorNotice message={error}/>}
      <div className="modal-footer"><button className="button secondary" type="button" onClick={onClose} disabled={busy}>Отмена</button><button className="button primary" type="submit" disabled={busy || (escalate ? !note.trim() : !checked)}>{busy ? <LoaderCircle size={16} className="spin"/> : escalate ? <ArrowRight size={16}/> : <Check size={16}/>} {escalate ? 'Эскалировать' : 'Подтвердить симуляцию'}</button></div>
    </form>
  </Modal>
}
export function EmptyQueue({filtered,onClear,onCreate}: {filtered: boolean; onClear: () => void; onCreate: () => void}) {
  return <div className="empty-queue"><div className="empty-illustration"><span/><span/><div><Search size={26}/></div></div><h3>{filtered ? 'Ничего не найдено' : 'Всё начинается с обращения'}</h3><p>{filtered ? 'Попробуйте изменить запрос или сбросить фильтры.' : 'Добавьте синтетический пример и проверьте, как Copilot готовит ответ.'}</p>
    <button className="button secondary" onClick={filtered ? onClear : onCreate}>{filtered ? <X size={15}/> : <Plus size={15}/>} {filtered ? 'Сбросить фильтры' : 'Добавить пример'}</button></div>
}
