/* Support Copilot · клиентская логика без зависимостей.
 * Нормализация cp1251, определение языка, источники фактов, проверка черновика,
 * пословный diff и упрощённый демо-триаж (только для демо-режима). */
(function () {
  'use strict';
  const SC = (window.SC = window.SC || {});

  const CATEGORIES = {
    'complaint.insult': 'Оскорбления и токсичность',
    'complaint.cheat': 'Читы и стороннее ПО',
    'complaint.dm': 'Убийство без повода, нарушение РП',
    'complaint.scam': 'Обман с имуществом',
    'complaint.rmt_ads': 'Реклама и продажа за реальные деньги',
    'complaint.admin': 'Жалоба на администратора',
    'complaint.other': 'Другое нарушение',
    'complaint.invalid': 'Не жалоба или без доказательств',
    'report.question': 'Вопрос по механике игры',
    'report.help': 'Просьба о помощи: застрял, баг',
    'report.complaint': 'Жалоба на игрока через репорт',
    'report.account': 'Аккаунт: доступ, взлом, пропажа',
    'report.payment': 'Платёж и донат',
    'report.offtopic': 'Оффтоп и пустые сообщения',
  };
  // Категории, которые по таксономии всегда решает человек.
  const MANDATORY_HUMAN = new Set(['report.account', 'report.payment', 'complaint.admin']);
  const CATEGORY_RULES = {
    'complaint.insult': ['2.1', '2.4', '2.6'], 'complaint.cheat': ['5.2'], 'complaint.dm': ['5.3', '5.4', 'GZ 1.1'],
    'complaint.scam': ['4.1', '4.2'], 'complaint.rmt_ads': ['4.4', '2.3'], 'complaint.admin': ['3.4'],
    'complaint.invalid': ['ЖБ 1.3.3', 'ЖБ 1.1.2'], 'report.account': ['1.4'], 'report.complaint': ['2.1'],
  };
  const PRIORITIES = { p0: 'Критично', p1: 'Высокий', p2: 'Обычный', p3: 'Низкий' };
  const LANGS = { ru: 'Русский', kk: 'Қазақша', uz: 'Oʻzbekcha', en: 'English', es: 'Español', pt: 'Português', und: 'Не определён' };
  const STATUSES = { new: 'Новое', reviewed: 'Проверено', escalated: 'Эскалировано', sent: 'Отправлено' };

  // Таблица замен из ТЗ: на kz-серверах казахские буквы набраны похожими символами cp1251.
  const KK_MAP = { 'ќ': 'қ', 'ґ': 'ғ', 'ѕ': 'ң', 'є': 'ә', 'ј': 'ө', 'ў': 'ұ', 'ї': 'ү' };
  Object.keys(KK_MAP).forEach((k) => { KK_MAP[k.toUpperCase()] = KK_MAP[k].toUpperCase(); });
  const KK_RE = /[ќґѕєјўїЌҐЅЄЈЎЇ]/g;

  /** Замена 1:1 по символам, поэтому позиции в тексте не сдвигаются. */
  function normalizeKk(text, serverLang) {
    // ў — штатная буква узбекской кириллицы, поэтому меняем только для казахского контекста.
    if (serverLang !== 'kk' && !/[ќґѕєј]/i.test(text)) return { text, changed: 0 };
    let changed = 0;
    const out = text.replace(KK_RE, (ch) => { changed += 1; return KK_MAP[ch] || ch; });
    return { text: out, changed };
  }

  const WORDS = {
    uz: /(?<!\p{L})(salom|iltimos|yordam|uchun|sizga|bilan|emas|kerak|men|qildi|qoldim|bor|haqorat|administrator\p{L}*|qoidalar\p{L}*|murojaat\p{L}*)(?!\p{L})/giu,
    en: /(?<!\p{L})(the|you|please|your|hello|hi|thanks|player|is|are|will|and|rule|report|i|it|my|me|for|not|but|did|get|have|was|to|of|can|help|account|paid)(?!\p{L})/giu,
    es: /(?<!\p{L})(hola|gracias|por|favor|jugador|cuenta|usted|para|está|reporte)(?!\p{L})/giu,
    pt: /(?<!\p{L})(olá|obrigad[oa]|você|não|conta|jogador|para|está|relatório)(?!\p{L})/giu,
  };
  function countMatches(re, text) { const m = text.match(re); return m ? m.length : 0; }

  /** Простое определение языка для проверки черновика. Возвращает und при сомнении. */
  function detectLang(text) {
    // Nicknames and links carry identity, not the player's language.
    const t = (text || '').replace(/https?:\/\/\S+/giu, ' ').replace(/[\p{L}\d]+_[\p{L}\d_]+/gu, ' ').toLowerCase().replace(/[’ʼ`]/g, "'");
    const cyr = (t.match(/[а-яёәғқңөұүһіў]/g) || []).length;
    const lat = (t.match(/[a-zñçãõáéíóúʻ‘']/g) || []).length;
    if (cyr + lat < 12) return 'und';
    if (cyr > lat) {
      if (/[әғқңөұүһі]/.test(t)) return 'kk';
      if (/[ўҳ]/.test(t)) return 'uz';
      return 'ru';
    }
    const scores = { uz: countMatches(WORDS.uz, t) + (/(o|g)[ʻ‘']/.test(t) ? 2 : 0), en: countMatches(WORDS.en, t), es: countMatches(WORDS.es, t), pt: countMatches(WORDS.pt, t) };
    const best = Object.keys(scores).sort((a, b) => scores[b] - scores[a])[0];
    return scores[best] >= 2 ? best : 'und';
  }

  function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  function allSpans(text, re) {
    const spans = []; let m; re.lastIndex = 0;
    while ((m = re.exec(text))) { if (m[0].length) spans.push([m.index, m.index + m[0].length]); if (!re.global) break; }
    return spans;
  }

  const EVIDENCE_RE = /скрин\p{L}*|видео\p{L}*|запис\p{L}*|фрапс\p{L}*|fraps|пруф\p{L}*|доказательств\p{L}*|переписк\p{L}*|screen\p{L}*|video|skrin\p{L}*|dalil\p{L}*/giu;

  /** Факты с источниками: где именно в тексте или в каком поле найдено значение. */
  function factSources(ticket, text) {
    const r = ticket.result || {}; const ex = r.extracted || {};
    const given = ticket.facts_sources || {};
    const facts = [];
    const fromApi = (key) => (given[key] && Array.isArray(given[key].spans) ? given[key].spans : null);

    const nick = ex.nickname;
    if (nick) {
      const spans = fromApi('nickname') || allSpans(text, new RegExp(escapeRe(nick), 'gi'));
      facts.push({ key: 'nickname', label: 'Упомянутый игрок', value: nick, spans,
        source: spans.length ? 'из текста игрока' : (ticket.reported_nick ? 'из поля «ник нарушителя»' : 'источник не указан') });
    } else {
      facts.push({ key: 'nickname', label: 'Упомянутый игрок', value: null, spans: [], source: 'не найден' });
    }

    const refs = ex.rule_refs || [];
    let refSpans = fromApi('rule_refs') || [];
    if (!refSpans.length) refs.forEach((ref) => {
      const bare = ref.replace(/^(ЖБ|GZ|ГЗ|ОП)\s*/i, '');
      refSpans = refSpans.concat(allSpans(text, new RegExp('(?<![\\d.])' + escapeRe(bare) + '(?![\\d])', 'g')));
    });
    facts.push({ key: 'rule_refs', label: 'Пункты со слов игрока', value: refs.length ? refs.join(', ') : null, spans: refSpans,
      source: refs.length ? (refSpans.length ? 'из текста игрока' : 'из поля «пункт правил»' + (ticket.rule_refs_raw ? ': ' + ticket.rule_refs_raw : '')) : 'не указаны' });

    const attachments = ticket.images_count || (ticket.messages || []).reduce((n, m) => n + (m.attachments || 0), 0);
    const evSpans = fromApi('has_evidence') || allSpans(text, new RegExp(EVIDENCE_RE.source, 'giu'));
    facts.push({ key: 'has_evidence', label: 'Доказательства', value: ex.has_evidence ? 'заявлены, не проверены' : null, spans: evSpans,
      source: ex.has_evidence ? [attachments ? `вложений: ${attachments}` : '', evSpans.length ? 'упомянуты в тексте' : ''].filter(Boolean).join(', ') || 'со слов игрока' : 'не заявлены' });

    const server = ex.server;
    const srvSpans = server ? (fromApi('server') || allSpans(text, new RegExp('(сервер\\p{L}*|server)\\s*[№#:]?\\s*' + escapeRe(String(server)), 'giu'))) : [];
    facts.push({ key: 'server', label: 'Сервер', value: server || null, spans: srvSpans,
      source: server ? (srvSpans.length ? 'из текста игрока' : 'из метаданных обращения') : 'неизвестен' });
    return facts;
  }

  // ---------- Проверка черновика ----------
  const PROMISE_RE = new RegExp([
    'разбан\\w*', 'разблокир\\w*', 'сним(ем|ут|у)\\s+(бан|блок\\w*|мут|наказан\\w*)',
    'верн(ём|ем|ут|у)\\s+(вам\\s+)?(деньги|средства|донат|голд\\w*|валют\\w*|имущество|машин\\w*)', 'возврат\\s+(средств|денег)\\s+(будет|оформ\\w*)',
    'получит\\s+(бан|мут|блок\\w*|варн|деморган)', 'будет\\s+(забанен|наказан|заблокирован)', 'накажем', 'забаним', 'выдадим\\s+(бан|мут)',
    'гарантиру\\w*',
    'unban\\w*', 'refund\\w*', 'will\\s+be\\s+(banned|punished|refunded)', 'we\\s+will\\s+return',
    'бұғаттан\\s+шығар\\w*', 'ақша\\w*\\s+қайтар\\w*', 'жазаланады',
    'blokdan\\s+chiqar\\w*', 'pul\\w*\\s+qaytar\\w*', 'jazolanadi',
  ].join('|').replace(/\\w/g, '\\p{L}'), 'giu');
  // «не является решением о разблокировке», «игрок не будет забанен» — это не обещание.
  const NEG_RE = /(?<!\p{L})(не|not|no|never|без|емес|emas)\s+(\p{L}+\s+)?$|(?<!\p{L})(не|not|does\s+not|is\s+not)\s+(является|означает|обеща\p{L}*|гарантир\p{L}*|можем|может|будет|mean\p{L}*|promise\p{L}*|guarantee\p{L}*|a\s+decision)(?!\p{L})/iu;
  function negated(text, start) {
    const from = Math.max(text.lastIndexOf('.', start), text.lastIndexOf('!', start), text.lastIndexOf('?', start), text.lastIndexOf('\n', start)) + 1;
    return NEG_RE.test(text.slice(from, start));
  }
  const SCREEN_RE = /(на|по)\s+(скриншот\p{L}*|скрин\p{L}*|видео)\s+(видно|заметно)|судя\s+по\s+(скрин\p{L}*|видео)|скриншот\p{L}*\s+подтвержда\p{L}*|screenshots?\s+(show|prove)|скриншот\p{L}*\s+көрін\p{L}*|skrinshot\p{L}*\s+ko[ʻ‘']?rin\p{L}*/giu;
  const REF_RE = /(?<![\d.])(?:(ЖБ|GZ|ГЗ)\s*)?(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)(?![\d])(?:\s*(ОП|OP|GZ|ГЗ|ЖБ)(?!\p{L}))?/giu;

  function refCode(prefix, num, suffix) {
    const p = (prefix || suffix || '').toUpperCase();
    if (p === 'ЖБ') return 'ЖБ ' + num;
    if (p === 'GZ' || p === 'ГЗ') return 'GZ ' + num;
    return num;
  }

  /**
   * ctx: {lang, rules: Map(code -> rule) | null, cited: string[]}
   * Возвращает {checks:[{id, ok, title, detail}], marks:[{start,end,kind}]}
   */
  function lintDraft(draft, ctx) {
    const text = draft || '';
    const checks = []; const marks = [];
    // 1. Цитаты существуют
    const found = [];
    let m; REF_RE.lastIndex = 0;
    while ((m = REF_RE.exec(text))) {
      const code = refCode(m[1], m[2], m[3]);
      found.push({ code, start: m.index, end: m.index + m[0].length });
    }
    const codes = Array.from(new Set(found.map((f) => f.code).concat(ctx.cited || [])));
    if (!ctx.rules) {
      checks.push({ id: 'refs', ok: null, title: 'Цитаты правил', detail: 'База правил недоступна, проверка пропущена.' });
    } else {
      const missing = codes.filter((c) => !ctx.rules.has(c));
      found.filter((f) => missing.includes(f.code)).forEach((f) => marks.push({ start: f.start, end: f.end, kind: 'ref' }));
      checks.push(missing.length
        ? { id: 'refs', ok: false, title: 'Пункт не найден в базе правил', short: 'Пункта ' + missing.join(', ') + ' нет в правилах', detail: 'Уберите его или замените на существующий.' }
        : { id: 'refs', ok: true, title: 'Цитаты правил', detail: codes.length ? 'Все пункты есть в базе: ' + codes.join(', ') : 'В черновике нет ссылок на правила.' });
    }
    // 2. Обещания
    const promises = allSpans(text, new RegExp(PROMISE_RE.source, 'giu')).filter(([s]) => !negated(text, s));
    promises.forEach(([s, e]) => marks.push({ start: s, end: e, kind: 'promise' }));
    checks.push(promises.length
      ? { id: 'promise', ok: false, title: 'Похоже на обещание', short: 'Похоже на обещание разбана, возврата или наказания', detail: 'Черновик не может обещать разбан, возврат средств или наказание другого игрока.' }
      : { id: 'promise', ok: true, title: 'Без обещаний', detail: 'Нет обещаний разбана, возврата или наказания.' });
    // 3. Скриншоты
    const screens = allSpans(text, new RegExp(SCREEN_RE.source, 'giu'));
    screens.forEach(([s, e]) => marks.push({ start: s, end: e, kind: 'screen' }));
    checks.push(screens.length
      ? { id: 'screen', ok: false, title: 'Ссылка на содержимое вложений', short: 'Сервис не видел скриншоты, не пишите, что на них видно', detail: 'Сервис знает только количество вложений. Оставьте фразу, только если проверили их сами.' }
      : { id: 'screen', ok: true, title: 'Без выводов по скриншотам', detail: 'Черновик не утверждает, что видно на вложениях.' });
    // 4. Язык
    const dl = detectLang(text);
    if (dl === 'und' || !ctx.lang || ctx.lang === 'und') {
      checks.push({ id: 'lang', ok: null, title: 'Язык ответа', detail: 'Недостаточно текста, чтобы проверить язык.' });
    } else {
      checks.push(dl === ctx.lang
        ? { id: 'lang', ok: true, title: 'Язык ответа', detail: 'Совпадает с языком игрока: ' + LANGS[ctx.lang] + '.' }
        : { id: 'lang', ok: false, title: 'Другой язык', short: 'Ответ не на языке игрока (' + (LANGS[ctx.lang] || ctx.lang) + ')', detail: 'Черновик похож на «' + (LANGS[dl] || dl) + '», а игрок пишет на «' + (LANGS[ctx.lang] || ctx.lang) + '».' });
    }
    return { checks, marks: mergeMarks(marks) };
  }

  function mergeMarks(marks) {
    const sorted = marks.slice().sort((a, b) => a.start - b.start || b.end - a.end);
    const out = [];
    sorted.forEach((mk) => { const last = out[out.length - 1]; if (last && mk.start < last.end) return; out.push(mk); });
    return out;
  }

  // ---------- Пословный diff ----------
  function wordDiff(before, after) {
    const a = (before || '').split(/(\s+)/).filter((x) => x.length);
    const b = (after || '').split(/(\s+)/).filter((x) => x.length);
    if (a.length * b.length > 250000) return [{ op: 'del', text: before }, { op: 'ins', text: after }];
    const n = a.length, mm = b.length;
    const dp = Array.from({ length: n + 1 }, () => new Uint16Array(mm + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = mm - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    const ops = []; let i = 0, j = 0;
    const push = (op, text) => { const last = ops[ops.length - 1]; if (last && last.op === op) last.text += text; else ops.push({ op, text }); };
    while (i < n && j < mm) {
      if (a[i] === b[j]) { push('eq', a[i]); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { push('del', a[i]); i++; }
      else { push('ins', b[j]); j++; }
    }
    while (i < n) push('del', a[i++]);
    while (j < mm) push('ins', b[j++]);
    return ops;
  }

  // ---------- Демо-триаж (только для демо-режима, без сети) ----------
  const KW = [
    ['report.payment', /донат|плат[её]ж|оплат|списал|не пришл|(?<!\p{L})голд|payment|(?<!\p{L})paid|tolov|to[ʻ‘']lov|төле/iu],
    ['report.account', /взлом|украл\p{L}* акк|не могу (войти|зайти)|пропал\p{L}* (машин|дом|имущ)|hacked|бұз|buzib|кіре алмай/iu],
    ['complaint.admin', /админ\p{L}*.{0,30}(без причин|неправ|выдал|забан)|забанил\p{L}*|разбан|апелляц|снять (мут|бан)/iu],
    ['complaint.cheat', /(?<!\p{L})чит|аимбот|aimbot|wallhack|летает|через стен|(?<!\p{L})софт|(?<!\p{L})soft/iu],
    ['complaint.scam', /обман|мошен|(?<!\p{L})кинул|не отдал|не перев[её]л|(?<!\p{L})scam|(?<!\p{L})alda/iu],
    ['complaint.rmt_ads', /реал\p{L}* деньг|за реал|прода[её]т акк|реклам|real money/iu],
    ['complaint.insult', /(?<!\p{L})оск|оскорб|(?<!\p{L})мат(?!ч)|балағат|haqorat|insult|(?<!\p{L})родн|(?<!\p{L})семь/iu],
    ['complaint.dm', /(?<!\p{L})(дм|dm|rdm)(?!\p{L})|убил|убива|без причин|зел[её]н\p{L}* зон|o[ʻ‘']?ldir|өлтір|(?<!\p{L})killed/iu],
    ['report.help', /застр|текстур|(?<!\p{L})баг|вылет|телепорт|stuck|qotib|қатып|тұрып қал/iu],
    ['report.question', /(?<!\p{L})(как|где|почему|сколько|how|where|qanday|қалай|қайда)(?!\p{L})/iu],
  ];
  const T = {
    ru: { hi: 'Здравствуйте!', rule: (c) => `Такие действия запрещает пункт ${c}.`, complaint: (n) => `Спасибо за жалобу${n ? ' на ' + n : ''}. Администратор проверит доказательства и примет решение.`,
      invalid: 'В жалобе не хватает описания. Укажите, что произошло, где и когда, ник нарушителя, и приложите доказательства.',
      payment: 'Передали обращение специалисту по платежам. Ответьте, пожалуйста: дата, время, способ и сумма оплаты. Не отправляйте данные карты и коды из SMS.',
      account: 'Передали обращение специалисту по безопасности аккаунтов. Никому не сообщайте пароль и коды подтверждения.',
      help: 'Администратор скоро поможет. Пожалуйста, оставайтесь в игре.', question: 'Администратор уточнит актуальный порядок и ответит в этом обращении.',
      offtopic: 'Опишите, пожалуйста, что случилось, и администратор вам поможет.' },
    kk: { hi: 'Сәлеметсіз бе!', rule: (c) => `Мұндай әрекетке ${c}-тармақ тыйым салады.`, complaint: (n) => `Шағымыңызға рақмет${n ? ' (' + n + ')' : ''}. Әкімші дәлелдерді тексеріп, шешім қабылдайды.`,
      invalid: 'Шағымда сипаттама жеткіліксіз. Не болғанын, қай жерде және қашан болғанын, ойыншының никін жазып, дәлел тіркеңіз.',
      payment: 'Өтінішіңізді төлем жөніндегі маманға жібердік. Төлем күнін, уақытын, тәсілін және сомасын жазыңыз. Карта деректерін жібермеңіз.',
      account: 'Өтінішіңізді аккаунт қауіпсіздігі жөніндегі маманға жібердік. Құпиясөзді ешкімге бермеңіз.',
      help: 'Әкімші жақын арада көмектеседі. Ойыннан шықпай күте тұрыңыз.', question: 'Әкімші өзекті тәртіпті нақтылап, осы өтінішке жауап береді.',
      offtopic: 'Не болғанын жазыңызшы, әкімші көмектеседі.' },
    uz: { hi: 'Salom!', rule: (c) => `Bunday harakat ${c}-band bilan taqiqlangan.`, complaint: (n) => `Shikoyatingiz uchun rahmat${n ? ' (' + n + ')' : ''}. Administrator dalillarni tekshirib, qaror qabul qiladi.`,
      invalid: 'Shikoyatda tavsif yetarli emas. Nima, qayerda va qachon bo‘lganini, o‘yinchi nikini yozing va dalil biriktiring.',
      payment: 'Murojaatingiz to‘lovlar bo‘yicha mutaxassisga yuborildi. To‘lov sanasi, vaqti, usuli va summasini yozing. Karta ma’lumotlarini yubormang.',
      account: 'Murojaatingiz akkaunt xavfsizligi bo‘yicha mutaxassisga yuborildi. Parolni hech kimga bermang.',
      help: 'Administrator tez orada yordam beradi. Iltimos, o‘yindan chiqmang.', question: 'Administrator amaldagi tartibni aniqlab, shu murojaatda javob beradi.',
      offtopic: 'Iltimos, nima bo‘lganini yozing, administrator yordam beradi.' },
    en: { hi: 'Hello!', rule: (c) => `This is prohibited by rule ${c}.`, complaint: (n) => `Thank you for the report${n ? ' about ' + n : ''}. An administrator will check the evidence and make a decision.`,
      invalid: 'The complaint is missing a description. Please state what happened, where and when, the player’s nickname, and attach evidence.',
      payment: 'Your request has been passed to the payments specialist. Please reply with the date, time, method and amount. Do not send card details or SMS codes.',
      account: 'Your request has been passed to the account security specialist. Never share your password or verification codes.',
      help: 'An administrator will help you shortly. Please stay in the game.', question: 'An administrator will confirm the current procedure and reply here.',
      offtopic: 'Please describe what happened and an administrator will help you.' },
  };

  function demoTriage(input, rules) {
    const kind = input.kind;
    const raw = input.text || '';
    const norm = normalizeKk(raw, input.server_lang).text;
    let lang = detectLang(norm);
    if (lang === 'und' && /[а-яё]/i.test(norm)) lang = 'ru';
    if (lang === 'und') lang = input.server_lang || 'ru';
    let category = null;
    for (const [code, re] of KW) {
      if (!re.test(norm)) continue;
      if (kind === 'complaint' && code.startsWith('report.')) continue;
      if (kind === 'report' && code.startsWith('complaint.') && code !== 'complaint.admin') { category = 'report.complaint'; break; }
      if (kind === 'report' && code === 'complaint.admin') { category = 'report.complaint'; break; }
      category = code; break;
    }
    const words = norm.split(/\s+/).filter(Boolean).length;
    if (!category) category = kind === 'complaint' ? (words < 4 ? 'complaint.invalid' : 'complaint.other') : 'report.offtopic';
    const priority = ({ 'report.payment': 'p0', 'report.account': 'p0', 'complaint.cheat': 'p1', 'complaint.scam': 'p1', 'complaint.rmt_ads': 'p1',
      'report.question': 'p3', 'report.offtopic': 'p3', 'complaint.invalid': 'p3' })[category] || 'p2';
    const nickM = norm.match(/(?<![\w])([A-Z][a-z]+_[A-Z][a-z]+\d*)(?![\w])/);
    const refs = Array.from(new Set((norm.match(/(?<![\d.])\d{1,2}\.\d{1,2}(?:\.\d{1,2})?(?![\d])/g) || [])));
    const attachments = Number(input.attachments) || 0;
    const evidence = attachments > 0 || new RegExp(EVIDENCE_RE.source, 'iu').test(norm);
    const srv = norm.match(/(?:сервер\p{L}*|server)\s*[№#:]?\s*(\d{1,3})(?!\d)/iu);
    const known = (CATEGORY_RULES[category] || []).filter((c) => rules.has(c));
    const cited = known.slice(0, 1);
    const t = T[lang] || T.en;
    const nick = nickM ? nickM[1] : null;
    let body;
    if (category === 'report.payment') body = t.payment;
    else if (category === 'report.account') body = t.account;
    else if (category === 'report.help') body = t.help;
    else if (category === 'report.question') body = t.question;
    else if (category === 'report.offtopic') body = t.offtopic;
    else if (category === 'complaint.invalid') body = t.invalid;
    else body = t.complaint(nick);
    const ruleSentence = cited.length && category !== 'report.account' && category !== 'complaint.invalid' ? ' ' + t.rule(cited[0]) : '';
    const reasons = [];
    if (MANDATORY_HUMAN.has(category)) reasons.push('Категория всегда идёт человеку по таксономии');
    if (kind === 'complaint' && category !== 'complaint.invalid') reasons.push('Решение о наказании принимает администратор');
    if (evidence && attachments) reasons.push(`Вложения не проверены: известно только их количество (${attachments})`);
    if (/разбан|верн\p{L}* деньг|refund|unban/iu.test(norm)) reasons.push('Игрок просит то, что сервис не может обещать');
    if (category === 'report.question') reasons.push('В базе знаний нет проверенной инструкции');
    const needsHuman = reasons.length > 0;
    return {
      lang, category, priority, is_spam_or_duplicate: false,
      extracted: { nickname: nick, rule_refs: refs, has_evidence: evidence, server: srv ? srv[1] : null },
      draft_reply: { lang, text: (t.hi + ' ' + body + ruleSentence).trim(), cited },
      needs_human: needsHuman, confidence: needsHuman ? 0.74 : 0.81, reasons,
      _normalized: norm,
    };
  }

  SC.logic = { CATEGORIES, MANDATORY_HUMAN, CATEGORY_RULES, PRIORITIES, LANGS, STATUSES,
    normalizeKk, detectLang, factSources, lintDraft, wordDiff, demoTriage, refCode };
})();
