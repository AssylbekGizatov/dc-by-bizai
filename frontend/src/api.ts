import type { CreateTicket, Filters, Health, Review, Rule, Ticket, TicketList } from './types'

// The admin API token only lives in memory. Never store model-provider keys in the browser.
let accessToken = ''
export function setAccessToken(value: string) { accessToken = value.trim() }
export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = 'ApiError' }
}
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  if (options.body) headers.set('Content-Type', 'application/json')
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  let response: Response
  try { response = await fetch(`/api${path}`, {...options, headers}) }
  catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error
    throw new ApiError('Не удалось связаться с API. Проверьте подключение и запуск сервиса.', 0)
  }
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json() as {detail?: unknown}
      if (typeof body.detail === 'string') detail = body.detail
    } catch { /* Non-JSON reverse-proxy responses must not be rendered as HTML. */ }
    const messages: Record<number, string> = {
      401: 'Нужен токен доступа к API. Укажите его в настройках подключения.',
      403: 'Запрос отклонён политикой доступа. Проверьте токен и разрешённый адрес интерфейса.',
      404: 'Запись не найдена. Обновите очередь.',
      409: 'Обращение уже изменено. Обновите его, чтобы не перезаписать чужую проверку.',
      422: 'Проверьте заполненные поля: API отклонил запрос.',
      429: 'Слишком много запросов. Подождите немного и попробуйте снова.',
    }
    throw new ApiError(messages[response.status] || detail || `API вернул ошибку ${response.status}. Повторите попытку позже.`, response.status)
  }
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) throw new ApiError('API вернул неожиданный ответ. Проверьте адрес и настройки сервиса.', 502)
  return response.json() as Promise<T>
}
export const api = {
  health: (signal?: AbortSignal) => request<Health>('/health', {signal}),
  list: (filters: Filters, offset = 0, signal?: AbortSignal) => {
    const query = new URLSearchParams({limit: '100', offset: String(offset)})
    for (const [key,value] of Object.entries(filters)) if (value) query.set(key,value)
    return request<TicketList>(`/tickets?${query}`, {signal})
  },
  ticket: (id: string, signal?: AbortSignal) => request<Ticket>(`/tickets/${encodeURIComponent(id)}`, {signal}),
  create: (ticket: CreateTicket, key: string) => request<Ticket>('/tickets', {method: 'POST', headers: {'Idempotency-Key': key}, body: JSON.stringify(ticket)}),
  review: (id: string, review: Review) => request<Ticket>(`/tickets/${encodeURIComponent(id)}/review`, {method: 'PATCH', body: JSON.stringify(review)}),
  rules: (signal?: AbortSignal) => request<{items: Rule[]; total: number}>('/rules', {signal}),
  rule: (id: string, signal?: AbortSignal) => request<Rule>(`/rules/${encodeURIComponent(id)}`, {signal}),
}
