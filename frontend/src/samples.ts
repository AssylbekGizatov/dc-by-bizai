import type { CreateTicket } from './types'
export const samples: { label: string; caption: string; data: CreateTicket }[] = [
  { label: 'Жалоба · RU', caption: 'Извлечение фактов и поиск правил', data: {
    kind: 'complaint', text: '[Синтетический пример] Demo_Player оскорблял меня в чате. Указываю пункт 2.1, есть 2 скриншота. Прошу проверить ситуацию.',
    player_id: 'synthetic-player-001', server: 'demo-kz-01', attachments_count: 2, server_lang: 'ru',
  } },
  { label: 'Қазақша · CP1251', caption: 'Нормализация казахских символов', data: {
    kind: 'report', text: '[Синтетический пример] Сєлеметсіз бе! Мен картада ќатып ќалдым, ќозґала алмаймын. Кјмектесе аласыз ба?',
    player_id: 'synthetic-player-002', server: 'demo-kz-02', attachments_count: 0, server_lang: 'kk',
  } },
  { label: 'Payment · EN', caption: 'Обязательная проверка человеком', data: {
    kind: 'report', text: '[Synthetic example] I made a payment but did not receive my in-game currency. Please check the transaction. This is a test, not a real purchase.',
    player_id: 'synthetic-player-003', server: 'demo-en-01', attachments_count: 0, server_lang: 'en',
  } },
]
