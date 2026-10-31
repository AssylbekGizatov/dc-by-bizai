import { beforeAll, describe, expect, it } from 'vitest'
import logicSource from '../public/js/logic.js?raw'
import demoSource from '../public/js/demo-data.js?raw'

// Страница — обычные скрипты без сборки: они кладут API в window.SC. Здесь грузим их так же.
type Rule = { code: string; title: string; text: string }
type Check = { id: string; ok: boolean | null }
type Triage = {
  lang: string; category: string; priority: string; is_spam_or_duplicate: boolean
  extracted: { nickname: string | null; rule_refs: string[]; has_evidence: boolean; server: string | null }
  draft_reply: { lang: string; text: string; cited: string[] }
  needs_human: boolean; confidence: number; reasons: string[]
}
type Logic = {
  normalizeKk(text: string, serverLang?: string): { text: string; changed: number }
  detectLang(text: string): string
  lintDraft(draft: string, ctx: { lang: string; rules: Map<string, Rule>; cited: string[] }): { checks: Check[] }
  demoTriage(input: { kind: string; text: string; attachments: number; server_lang: string }, rules: Map<string, Rule>): Triage
  MANDATORY_HUMAN: Set<string>
}
type Globals = { window?: unknown; SC?: { logic: Logic; demo: { RULES: Rule[] } } }

let L: Logic
let rules: Map<string, Rule>

beforeAll(() => {
  const g = globalThis as Globals
  g.window = globalThis
  new Function(logicSource)()
  new Function(demoSource)()
  if (!g.SC) throw new Error('scripts did not register window.SC')
  L = g.SC.logic
  rules = new Map(g.SC.demo.RULES.map((r) => [r.code, r]))
})

const checks = (draft: string, lang = 'ru') =>
  Object.fromEntries(L.lintDraft(draft, { lang, rules, cited: [] }).checks.map((c) => [c.id, c.ok]))

describe('cp1251 в казахском тексте', () => {
  it('восстанавливает казахские буквы на казахском сервере', () => {
    expect(L.normalizeKk('Сєлеметсіз бе, ќалай ґой', 'kk')).toEqual({ text: 'Сәлеметсіз бе, қалай ғой', changed: 3 })
  })
  it('читает ґ/є/ј по позиции: и как в ТЗ, и как в тикетах (как бэкенд)', () => {
    expect(L.normalizeKk('кґмек керек, ойынєа кірдім', 'kk').text).toBe('көмек керек, ойынға кірдім')
    expect(L.normalizeKk('ќозґала алмаймын, Кјмектесіѕізші', 'kk').text).toBe('қозғала алмаймын, Көмектесіңізші')
    expect(L.normalizeKk('ќґѕєјўї ЌҐЅЄЈЎЇ', 'kk').text).toBe('қөңғәұү ҚӨҢҒӘҰҮ')
  })
  it('не трогает узбекскую ў', () => {
    expect(L.normalizeKk('ўзбек тили', 'uz')).toEqual({ text: 'ўзбек тили', changed: 0 })
  })
})

describe('язык обращения', () => {
  it('does not count a long Latin nickname or link as the language of Russian text', () => {
    expect(L.detectLang('Christopher_Alexander_Washington помогите мне выйти из текстур')).toBe('ru')
    expect(L.detectLang('Iltimos, yordam kerak, men o’yinda qoldim')).toBe('uz')
  })
  it('различает казахский, русский и английский', () => {
    expect(L.detectLang('Сәлеметсіз бе, мен ойында қалып қойдым көмектесіңізші')).toBe('kk')
    expect(L.detectLang('Помогите, застрял в текстурах и не могу выйти')).toBe('ru')
    expect(L.detectLang('Hello, I paid for gold but did not get it')).toBe('en')
  })
  it('не угадывает по слишком короткому тексту', () => {
    expect(L.detectLang('жб')).toBe('und')
  })
})

describe('проверка черновика', () => {
  it('пропускает корректный ответ', () => {
    expect(checks('Здравствуйте! Администратор проверит жалобу. Такие действия запрещает пункт 2.1.'))
      .toEqual({ refs: true, promise: true, screen: true, lang: true })
  })
  it('ловит несуществующий пункт и обещание наказания', () => {
    const c = checks('Здравствуйте! Игрок будет забанен, пункт 9.9.')
    expect(c.refs).toBe(false)
    expect(c.promise).toBe(false)
  })
  it('не считает обещанием отрицание', () => {
    expect(checks('Здравствуйте! Этот ответ не является решением о наказании, разблокировке или возврате средств.').promise).toBe(true)
    expect(checks('Здравствуйте! Не переживайте, игрок будет забанен.').promise).toBe(false)
  })
  it('ловит выводы по скриншотам', () => {
    expect(checks('Здравствуйте! На скриншоте видно нарушение.').screen).toBe(false)
  })
  it('ловит ответ не на языке игрока', () => {
    expect(checks('Hello! An administrator will check it.', 'ru').lang).toBe(false)
  })
})

describe('демо-анализ', () => {
  it('возвращает ответ в формате /triage', () => {
    const r = L.demoTriage({ kind: 'complaint', attachments: 2, server_lang: 'ru',
      text: 'Max_Fischer оскорбил мою семью в общем чате на сервере 3, скрины приложил. 2.1' }, rules)
    // Служебные поля с "_" страница удаляет перед выводом.
    expect(Object.keys(r).filter((k) => !k.startsWith('_')).sort()).toEqual(['category', 'confidence', 'draft_reply', 'extracted', 'is_spam_or_duplicate',
      'lang', 'needs_human', 'priority', 'reasons'])
    expect(r).toMatchObject({ lang: 'ru', category: 'complaint.insult', needs_human: true,
      extracted: { nickname: 'Max_Fischer', rule_refs: ['2.1'], has_evidence: true, server: '3' } })
    expect(r.draft_reply.cited.every((code) => rules.has(code))).toBe(true)
    expect(r.confidence).toBeGreaterThanOrEqual(0)
    expect(r.confidence).toBeLessThanOrEqual(1)
  })
  it('платёж — срочно и всегда человеку', () => {
    const r = L.demoTriage({ kind: 'report', attachments: 0, server_lang: 'ru', text: 'оплатил донат, голды не пришли' }, rules)
    expect(r).toMatchObject({ category: 'report.payment', priority: 'p0', needs_human: true })
    expect(L.MANDATORY_HUMAN.has('report.payment')).toBe(true)
  })
})
