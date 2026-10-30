// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, waitFor, within } from '@testing-library/dom'
import html from '../index.html?raw'
import logicSource from '../public/js/logic.js?raw'
import demoSource from '../public/js/demo-data.js?raw'
import analyzerSource from '../public/js/analyzer.js?raw'
import queueSource from '../public/js/queue.js?raw'

// Run the actual vanilla scripts, not a React replica. All API inputs are synthetic.
const syntheticTicket = (revision = 3) => ({
  id: 'synthetic-ticket', kind: 'report', text: '[Synthetic test] Please help with a stuck character.',
  created_at: '2026-10-30T12:00:00Z', status: 'pending', revision, player_id: 'synthetic-player',
  draft_reply: `Synthetic draft revision ${revision}`, reviewer_note: 'Synthetic moderator note',
  result: {lang: 'en', category: 'report.help', priority: 'p2', is_spam_or_duplicate: false,
    needs_human: true, confidence: 0.5, reasons: ['Synthetic review reason'],
    extracted: {nickname: null, server: null, rule_refs: [], has_evidence: false},
    draft_reply: {lang: 'en', text: `Synthetic draft revision ${revision}`, cited: []}},
  citations: [{id: 'demo:2.1', ref: '2.1', title: 'Synthetic rule', section: 'Synthetic section',
    text: '<img src=x onerror=alert(1)> Synthetic rule text.', synthetic: true}],
})
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}})
let current = syntheticTicket()
let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>
let listeners: [string, EventListenerOrEventListenerObject][]
const $ = <T extends Element = HTMLElement>(selector: string) => document.querySelector<T>(selector)!
const detail = () => within($('#q-detail'))
const draft = () => $<HTMLTextAreaElement>('#q-detail .draft')

beforeEach(() => {
  window.history.replaceState({}, '', '/')
  document.body.innerHTML = new DOMParser().parseFromString(html, 'text/html').body.innerHTML
  current = syntheticTicket()
  listeners = []
  const add = window.addEventListener.bind(window)
  vi.spyOn(window, 'addEventListener').mockImplementation((type, listener, options) => {
    if (listener) listeners.push([type, listener])
    add(type, listener, options)
  })
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  HTMLElement.prototype.scrollIntoView = vi.fn()
  HTMLDialogElement.prototype.showModal = function () {this.setAttribute('open', '')}
  HTMLDialogElement.prototype.close = function () {this.removeAttribute('open')}
  fetchMock = vi.fn<typeof fetch>(async (input, options) => {
    const url = String(input)
    if (url === '/api/health') return json({status: 'ok'})
    if (url === '/api/rules') return json({items: []})
    if (url.startsWith('/api/tickets?')) return json({items: [current], total: 1})
    if (url.endsWith('/feedback')) return json({items: []})
    if (url.endsWith('/review')) {
      current = {...current, ...JSON.parse(String(options?.body)), revision: current.revision + 1}
      return json(current)
    }
    if (url === '/api/tickets/synthetic-ticket' || url === '/api/tickets') return json(current)
    throw new Error(`Unexpected synthetic request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => {
  listeners.forEach(([type, listener]) => window.removeEventListener(type, listener))
  vi.restoreAllMocks(); vi.unstubAllGlobals()
  delete (window as unknown as {SC?: unknown}).SC
  document.body.replaceChildren(); window.history.replaceState({}, '', '/')
})
async function start(hash = '#queue/synthetic-ticket', demo = false) {
  window.history.replaceState({}, '', `${demo ? '/?demo=1' : '/'}${hash}`)
  for (const source of [logicSource, demoSource, analyzerSource, queueSource]) new Function(source)()
  await (window as unknown as {SC: {ui: {ready: Promise<void>}}}).SC.ui.ready
  if (hash.includes('synthetic-ticket')) await waitFor(() => expect(draft()?.value).toBe('Synthetic draft revision 3'))
}
const patches = () => fetchMock.mock.calls.filter(([, options]) => options?.method === 'PATCH')

describe('vanilla workbench API integration', () => {
  it('does not silently switch to browser demo when the real API is unavailable', async () => {
    fetchMock.mockRejectedValue(new TypeError('Synthetic offline'))
    await start('')
    const ui = (window as unknown as {SC: {ui: {mode: () => string}}}).SC.ui
    expect(ui.mode()).toBe('live')
    expect($('#mode').textContent).toContain('недоступен')
    $<HTMLTextAreaElement>('#text').value = '[Synthetic test] Please help.'
    fireEvent.submit($('#form'))
    await waitFor(() => expect($('#form-error').hidden).toBe(false))
    expect($('#history-list').children).toHaveLength(0)
  })

  it('keeps 401 in API mode and preserves the submitted player text', async () => {
    const fallback = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input, options) => options?.method === 'POST'
      ? Promise.resolve(json({detail: 'Synthetic expired token'}, 401)) : fallback(input, options))
    await start('')
    $<HTMLTextAreaElement>('#text').value = '[Synthetic test] Please help.'
    fireEvent.submit($('#form'))
    await waitFor(() => expect($('#form-error').textContent).toContain('токен'))
    expect($<HTMLTextAreaElement>('#text').value).toBe('[Synthetic test] Please help.')
    expect($('#history-list').children).toHaveLength(0)
  })

  it('rejects out-of-range attachment counts instead of silently normalizing them', async () => {
    await start('')
    $<HTMLTextAreaElement>('#text').value = '[Synthetic test] Please help.'
    $<HTMLInputElement>('#att').value = '-1'
    fireEvent.submit($('#form'))
    expect($('#form-error').hidden).toBe(false)
    expect(fetchMock.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
  })

  it('keeps player identity and complete intake fields on POST /api/tickets', async () => {
    await start('')
    $<HTMLTextAreaElement>('#text').value = '[Synthetic test] Character is stuck.'
    $<HTMLInputElement>('#player').value = 'synthetic-player'
    $<HTMLInputElement>('#att').value = '2'
    $<HTMLSelectElement>('#srv').value = 'en'
    fireEvent.submit($('#form'))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) => url === '/api/tickets' && options?.method === 'POST')).toBe(true))
    const call = fetchMock.mock.calls.find(([url, options]) => url === '/api/tickets' && options?.method === 'POST')!
    expect(JSON.parse(String(call[1]?.body))).toEqual({kind: 'complaint', text: '[Synthetic test] Character is stuck.', player_id: 'synthetic-player', attachments_count: 2, server_lang: 'en'})
    await waitFor(() => expect($('#out a[href="#queue/synthetic-ticket"]')).toBeTruthy())
  })

  it('renders untrusted source text inertly and saves the real revision with edits', async () => {
    await start()
    expect($('#q-detail img')).toBeNull()
    expect($('#q-detail').textContent).toContain('<img src=x onerror=alert(1)>')
    fireEvent.click(detail().getByRole('button', {name: 'Править'}))
    fireEvent.input(draft(), {target: {value: 'Synthetic edited draft'}})
    fireEvent.click(detail().getByRole('button', {name: 'Сохранить правку'}))
    await waitFor(() => expect(patches()).toHaveLength(1))
    expect(JSON.parse(String(patches()[0][1]?.body))).toMatchObject({expected_revision: 3, draft_reply: 'Synthetic edited draft', status: 'reviewed'})
  })

  it('keeps public rule provenance without exposing internal IDs in the workbench', async () => {
    current.citations = [{...current.citations[0], id: '30:2.1', synthetic: false}]
    await start()
    const citations = $('#q-detail .rules')
    expect(citations.textContent).toContain('Пункт 2.1')
    expect(citations.textContent).toContain('Synthetic section')
    expect(citations.textContent).toContain('Synthetic rule text.')
    expect(citations.textContent).not.toContain('30:2.1')
  })

  it('moves keyboard focus between queue sections without navigation or losing edits', async () => {
    await start()
    fireEvent.click(detail().getByRole('button', {name:'Править'}))
    fireEvent.input(draft(), {target:{value:'Synthetic unsaved draft during source comparison'}})
    const originalHash = location.hash
    const navigation = within(detail().getByRole('navigation', {name:'Разделы обращения'}))
    fireEvent.click(navigation.getByRole('button', {name:'Правила'}))
    expect(document.activeElement?.textContent).toBe('Основание ответа')
    fireEvent.click(navigation.getByRole('button', {name:'Ответ'}))
    expect(document.activeElement?.textContent).toBe('Черновик ответа')
    fireEvent.click(navigation.getByRole('button', {name:'История'}))
    expect(document.activeElement?.textContent).toBe('История решений')
    expect(location.hash).toBe(originalHash)
    expect(draft().value).toBe('Synthetic unsaved draft during source comparison')
    expect(window.confirm).not.toHaveBeenCalled()
    expect(patches()).toHaveLength(0)
  })

  it('actually fetches a new revision after 409 rather than reusing cached queue data', async () => {
    await start()
    const fallback = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation(async (input, options) => {
      if (options?.method === 'PATCH') {current = syntheticTicket(8); return json({detail: 'Synthetic stale revision'}, 409)}
      return fallback(input, options)
    })
    fireEvent.click(detail().getByRole('button', {name: 'Править'}))
    fireEvent.input(draft(), {target: {value: 'Synthetic conflicting draft'}})
    fireEvent.click(detail().getByRole('button', {name: 'Сохранить правку'}))
    await waitFor(() => expect(draft().value).toBe('Synthetic draft revision 8'))
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/tickets/synthetic-ticket')).toBe(true)
    expect($('#q-detail').textContent).toMatch(/другой вкладке|свежую версию/)
    expect($<HTMLTextAreaElement>('[aria-label="Несохранённый вариант черновика"]').value).toBe('Synthetic conflicting draft')
    window.history.pushState({}, '', '/#queue')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await waitFor(() => expect($('#q-detail .draft')).toBeNull())
    window.history.pushState({}, '', '/#queue/synthetic-ticket')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await waitFor(() => expect(draft()?.value).toBe('Synthetic draft revision 8'))
  })

  it('keeps a recoverable human draft if fetching the post-conflict version fails', async () => {
    await start()
    const fallback = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation(async (input, options) => {
      if (options?.method === 'PATCH') return json({detail: 'Synthetic stale revision'}, 409)
      if (String(input) === '/api/tickets/synthetic-ticket') return json({detail: 'Synthetic unavailable'}, 503)
      return fallback(input, options)
    })
    fireEvent.click(detail().getByRole('button', {name: 'Править'}))
    fireEvent.input(draft(), {target: {value: 'Synthetic recoverable draft after failed refresh'}})
    fireEvent.click(detail().getByRole('button', {name: 'Сохранить правку'}))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/tickets/synthetic-ticket')).toBe(true))
    await waitFor(() => {
      const texts = Array.from(document.querySelectorAll<HTMLTextAreaElement>('#q-detail textarea')).map(el => el.value)
      expect(texts).toContain('Synthetic recoverable draft after failed refresh')
    })
  })

  it('keeps failed detail retry recoverable rather than stuck loading', async () => {
    const fallback = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input, options) => String(input) === '/api/tickets/synthetic-missing'
      ? Promise.resolve(json({detail: 'Synthetic unavailable'}, 503)) : fallback(input, options))
    await start('#queue/synthetic-missing')
    await waitFor(() => expect(detail().getByRole('alert')).toBeTruthy())
    fireEvent.click(detail().getByRole('button', {name: 'Повторить'}))
    await waitFor(() => expect(detail().getByRole('alert')).toBeTruthy())
    expect(detail().getByRole('button', {name: 'Повторить'})).toBeTruthy()
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/tickets/synthetic-missing')).toHaveLength(2)
  })

  it('does not discard active draft edits when feedback arrives late', async () => {
    let resolve!: (response: Response) => void
    const pending = new Promise<Response>(done => {resolve = done})
    const fallback = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input, options) => String(input).endsWith('/feedback') ? pending : fallback(input, options))
    await start()
    fireEvent.click(detail().getByRole('button', {name: 'Править'}))
    fireEvent.input(draft(), {target: {value: 'Synthetic unsaved draft during history load'}})
    resolve(json({items: [{created_at: '2026-10-30T11:00:00Z', status: 'reviewed', previous_draft: 'a', edited_draft: 'b', reviewer_note: ''}]}))
    await waitFor(() => expect($('#q-detail .edits')).toBeTruthy())
    expect(draft().value).toBe('Synthetic unsaved draft during history load')
  })

  it('requires a nonblank escalation reason before any PATCH', async () => {
    await start()
    fireEvent.click(detail().getByRole('button', {name: 'Эскалировать'}))
    fireEvent.click(detail().getByRole('button', {name: 'Эскалировать'}))
    expect(patches()).toHaveLength(0)
    fireEvent.input($('#q-note'), {target: {value: 'Synthetic manual-review reason'}})
    fireEvent.click(detail().getByRole('button', {name: 'Эскалировать'}))
    await waitFor(() => expect(patches()).toHaveLength(1))
    expect(JSON.parse(String(patches()[0][1]?.body))).toMatchObject({status: 'escalated', reviewer_note: 'Synthetic moderator note\n\nSynthetic manual-review reason', expected_revision: 3})
  })

  it('requires explicit simulation consent and performs only a review PATCH', async () => {
    await start()
    fireEvent.click(detail().getByRole('button', {name: 'Симулировать отправку'}))
    expect(window.confirm).toHaveBeenCalledOnce()
    expect(patches()).toHaveLength(0)
    vi.mocked(window.confirm).mockReturnValue(true)
    fireEvent.click(detail().getByRole('button', {name: 'Симулировать отправку'}))
    await waitFor(() => expect(patches()).toHaveLength(1))
    expect(JSON.parse(String(patches()[0][1]?.body))).toMatchObject({status: 'simulated_sent', expected_revision: 3})
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes('/send'))).toBe(true)
  })

  it('blocks duplicate review submissions while a save is pending', async () => {
    await start()
    let resolve!: (response: Response) => void
    const pending = new Promise<Response>(done => {resolve = done})
    const fallback = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input, options) => options?.method === 'PATCH' ? pending : fallback(input, options))
    fireEvent.click(detail().getByRole('button', {name: 'Править'}))
    fireEvent.input(draft(), {target: {value: 'Synthetic pending save'}})
    const save = detail().getByRole('button', {name: 'Сохранить правку'})
    fireEvent.click(save); fireEvent.click(save)
    expect(patches()).toHaveLength(1)
    resolve(json({...current, draft_reply: 'Synthetic pending save', revision: 4, status: 'reviewed'}))
    await waitFor(() => expect(draft().value).toBe('Synthetic pending save'))
  })

  it('keeps unsaved edits when hash navigation is canceled', async () => {
    await start()
    fireEvent.click(detail().getByRole('button', {name: 'Править'}))
    fireEvent.input(draft(), {target: {value: 'Synthetic dirty navigation draft'}})
    const oldURL = location.href
    window.history.pushState({}, '', '/#')
    window.dispatchEvent(new HashChangeEvent('hashchange', {oldURL, newURL: location.href}))
    await waitFor(() => expect(window.confirm).toHaveBeenCalledOnce())
    expect(location.hash).toBe('#queue/synthetic-ticket')
    expect(draft().value).toBe('Synthetic dirty navigation draft')
    expect($('#view-queue').hidden).toBe(false)
  })

  it('sends search and filters to the server rather than filtering only one loaded page', async () => {
    await start('#queue')
    await waitFor(() => expect($('#queue-search')).toBeTruthy())
    fireEvent.input($('#queue-search'), {target:{value:'Synthetic needle'}})
    fireEvent.submit($('.queue-search'))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes('search=Synthetic+needle'))).toBe(true))
    fireEvent.click(within($('#q-list')).getByRole('button', {name:'Нужен человек'}))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes('needs_human=true'))).toBe(true))
    fireEvent.click(within($('#q-list')).getByRole('button', {name:'Срочные P0–P1'}))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes('urgent=true'))).toBe(true))
  })

  it('preserves a moderator note in conflict recovery and can restore both edits', async () => {
    await start()
    const fallback=fetchMock.getMockImplementation()!
    fetchMock.mockImplementation(async(input,options)=>{
      if(options?.method==='PATCH'){current=syntheticTicket(9);return json({detail:'Synthetic conflict'},409)}
      return fallback(input,options)
    })
    fireEvent.click(detail().getByRole('button',{name:'Править'}))
    fireEvent.input(draft(),{target:{value:'Synthetic human draft'}})
    fireEvent.input($('#q-admin-note'),{target:{value:'Synthetic unsaved moderator note'}})
    fireEvent.click(detail().getByRole('button',{name:'Сохранить правку'}))
    await waitFor(()=>expect($<HTMLTextAreaElement>('[aria-label="Несохранённая заметка"]')?.value).toBe('Synthetic unsaved moderator note'))
    fireEvent.click(detail().getByRole('button',{name:'Вернуть мой вариант в редактор'}))
    expect(draft().value).toBe('Synthetic human draft')
    expect($<HTMLTextAreaElement>('#q-admin-note').value).toBe('Synthetic unsaved moderator note')
  })

  it('keeps unsaved note and draft when an escalation is canceled', async () => {
    await start()
    fireEvent.click(detail().getByRole('button',{name:'Править'}))
    fireEvent.input(draft(),{target:{value:'Synthetic edit before escalation'}})
    fireEvent.input($('#q-admin-note'),{target:{value:'Synthetic unsaved note before escalation'}})
    fireEvent.click(detail().getByRole('button',{name:'Эскалировать'}))
    fireEvent.input($('#q-note'),{target:{value:'Synthetic canceled escalation reason'}})
    fireEvent.click(detail().getByRole('button',{name:'Отмена'}))
    expect(draft().value).toBe('Synthetic edit before escalation')
    expect($<HTMLTextAreaElement>('#q-admin-note').value).toBe('Synthetic unsaved note before escalation')
  })

  it('reopens a protected deep link after the administrator enters a token', async () => {
    current={...syntheticTicket(),id:'synthetic-auth'}
    const fallback=fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input,options)=>{
      if(String(input)==='/api/health') return Promise.resolve(json({status:'ok',auth_required:true}))
      if(!new Headers(options?.headers).has('Authorization')) return Promise.resolve(json({detail:'Synthetic token required'},401))
      if(String(input)==='/api/tickets/synthetic-auth') return Promise.resolve(json(current))
      return fallback(input,options)
    })
    await start('#queue/synthetic-auth')
    await waitFor(()=>expect(detail().getByRole('alert')).toBeTruthy())
    fireEvent.click($('#connection-open'))
    fireEvent.input($('#api-token'),{target:{value:'synthetic-valid-admin-token'}})
    fireEvent.submit($('#connection-form'))
    await waitFor(()=>expect(draft()?.value).toBe('Synthetic draft revision 3'))
    expect(detail().getByRole('button',{name:'Править'})).toBeTruthy()
  })

  it('keeps the admin token in memory and sends it only in request headers', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    await start('')
    fireEvent.click($('#connection-open'))
    fireEvent.input($('#api-token'), {target: {value: '  synthetic-admin-token  '}})
    fireEvent.submit($('#connection-form'))
    await waitFor(() => expect($('#connection-status').textContent).toContain('Доступ подтверждён'))
    const authorized = fetchMock.mock.calls.filter(([, options]) => new Headers(options?.headers).has('Authorization'))
    expect(authorized.length).toBeGreaterThan(0)
    for (const [url, options] of authorized) {
      expect(new Headers(options?.headers).get('Authorization')).toBe('Bearer synthetic-admin-token')
      expect(String(url)).not.toContain('synthetic-admin-token')
      expect(String(options?.body)).not.toContain('synthetic-admin-token')
    }
    expect($<HTMLInputElement>('#api-token').value).toBe('')
    expect(storage).not.toHaveBeenCalled()
    fireEvent.click($('#connection-clear'))
    const ui = (window as unknown as {SC: {ui: {api: (path: string) => Promise<unknown>}}}).SC.ui
    await ui.api('/api/rules')
    expect(new Headers(fetchMock.mock.calls.at(-1)?.[1]?.headers).has('Authorization')).toBe(false)
  })

  it('preserves teammate demo duplicate/flood behavior for the sixth same-player intake', async () => {
    await start('', true)
    for (let n = 0; n < 6; n++) {
      $<HTMLTextAreaElement>('#text').value = '[Synthetic test] I am stuck near a wall, please help.'
      $<HTMLInputElement>('#player').value = 'synthetic-flood-player'
      fireEvent.submit($('#form'))
      await waitFor(() => expect($('#history-list').children.length).toBe(n + 1))
    }
    expect($('#out').textContent).toContain('Флуд: 6-е обращение')
    expect($('#out').textContent).toContain('Повтор обращения')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
