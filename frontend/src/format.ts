import type { Ticket, TicketStatus } from './types'
export const languageLabels: Record<string, string> = {ru: 'Русский', kk: 'Қазақша', uz: 'O‘zbekcha', en: 'English', es: 'Español', pt: 'Português', und: 'Не определён'}
export const statusLabels: Record<TicketStatus, string> = {pending: 'К проверке', reviewed: 'Проверено', escalated: 'Эскалировано', simulated_sent: 'Симуляция отправки'}
export const priorityLabels: Record<string, string> = {p0: 'Критический', p1: 'Высокий', p2: 'Обычный', p3: 'Низкий'}
export const categoryLabels: Record<string, string> = {
  'complaint.insult': 'Оскорбления', 'complaint.cheat': 'Подозрение на читы', 'complaint.cheating': 'Подозрение на читы',
  'complaint.scam': 'Мошенничество', 'complaint.admin': 'Жалоба на администратора', 'complaint.rdm': 'Нарушение RP',
  'complaint.dm': 'Нарушение RP', 'complaint.other': 'Жалоба на игрока', 'report.stuck': 'Персонаж застрял',
  'report.bug': 'Техническая проблема', 'report.technical': 'Техническая проблема', 'report.payment': 'Платежи',
  'report.account': 'Доступ к аккаунту', 'report.ban': 'Апелляция блокировки', 'report.ban_appeal': 'Апелляция блокировки',
  'report.question': 'Вопрос по игре', 'report.help': 'Нужна помощь', 'report.complaint': 'Жалоба в репорте', 'report.offtopic': 'Вне темы', 'complaint.invalid': 'Неверный формат', 'complaint.rmt_ads': 'RMT / реклама', 'report.gameplay': 'Игровой вопрос', 'report.other': 'Вопрос поддержки',
  'spam': 'Спам', 'duplicate': 'Повторное обращение', 'other': 'Другое',
}
export function categoryLabel(value: string) { return categoryLabels[value] || value.replaceAll('.', ' · ') }
export function shortId(value: string) { return value.length > 13 ? value.slice(0, 8).toUpperCase() : value.toUpperCase() }
export function formatTime(value: string) {
  const date = new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`)
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat('ru', {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'}).format(date)
}
export function ticketDraft(ticket: Ticket) { return ticket.draft_reply ?? ticket.result.draft_reply.text }
export function errorText(error: unknown) { return error instanceof Error ? error.message : 'Не удалось выполнить действие. Попробуйте ещё раз.' }
export function percent(value: number) { return Number.isFinite(value) ? `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` : '—' }
export function elapsed(value?: number) { return value == null ? '—' : value < 1000 ? `${Math.round(value)} мс` : `${(value / 1000).toFixed(2)} с` }
