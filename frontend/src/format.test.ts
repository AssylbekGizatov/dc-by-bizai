import { describe, expect, it } from 'vitest'
import { categoryLabel, elapsed, errorText, formatTime, percent, shortId, ticketDraft } from './format'
import type { Ticket } from './types'

describe('display helpers', () => {
  it('does not invent category labels for unknown taxonomy values', () => {
    expect(categoryLabel('unknown.category')).toBe('unknown · category')
    expect(categoryLabel('report.payment')).toBe('Платежи')
  })
  it('handles untrusted values without HTML rendering', () => {
    expect(errorText(new Error('<script>alert(1)</script>'))).toBe('<script>alert(1)</script>')
    expect(categoryLabel('<img src=x onerror=alert(1)>')).toBe('<img src=x onerror=alert(1)>')
  })
  it('formats model confidence without misleading out-of-range numbers', () => {
    expect(percent(0.82)).toBe('82%'); expect(percent(1.7)).toBe('100%'); expect(percent(NaN)).toBe('—')
  })
  it('formats actual latency, never fake estimates', () => {
    expect(elapsed()).toBe('—'); expect(elapsed(1250)).toBe('1.25 с'); expect(elapsed(42)).toBe('42 мс')
  })
  it('handles invalid dates and readable identifiers', () => {
    expect(formatTime('not-a-date')).toBe('—'); expect(shortId('abcdef123456789')).toBe('ABCDEF12')
  })
  it('preserves an explicitly empty reviewer draft', () => {
    const ticket = {draft_reply: '', result: {draft_reply: {text: 'generated'}}} as Ticket
    expect(ticketDraft(ticket)).toBe('')
  })
})
