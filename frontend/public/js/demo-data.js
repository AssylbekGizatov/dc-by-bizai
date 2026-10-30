/* Синтетические демо-данные. Не из датасета Grand Mobile.
 * Тексты правил — короткие демо-формулировки, а не официальные правила игры. */
(function () {
  'use strict';
  const SC = (window.SC = window.SC || {});

  const OP = 'Общие правила (ОП)', ZB = 'Правила жалоб (ЖБ)', GZ = 'Зелёная зона (GZ)';
  const RULES = [
    { code: '1.4', section: OP, title: 'Безопасность аккаунта', text: 'Игрок сам отвечает за доступ к своему аккаунту. Не передавайте пароль и коды подтверждения другим людям, в том числе тем, кто называет себя администрацией.' },
    { code: '2.1', section: OP, title: 'Оскорбления', text: 'Запрещено оскорблять игроков и их близких в любом чате, в том числе завуалированно.' },
    { code: '2.3', section: OP, title: 'Реклама', text: 'Запрещена реклама сторонних проектов, сайтов и каналов.' },
    { code: '2.4', section: OP, title: 'Дискриминация', text: 'Запрещены высказывания, унижающие игроков по национальности, религии и другим признакам.' },
    { code: '2.6', section: OP, title: 'Провокации', text: 'Запрещены намеренные провокации конфликта и травля игрока.' },
    { code: '3.1', section: OP, title: 'Репорт не по назначению', text: 'Репорт предназначен для вопросов к администрации. Флуд и пустые сообщения в репорт запрещены.' },
    { code: '3.4', section: OP, title: 'Споры с администрацией', text: 'Решения администратора обжалуются через раздел жалоб, а не в игровом чате.' },
    { code: '4.1', section: OP, title: 'Обман при сделках', text: 'Запрещено обманывать игроков при обмене, продаже и аренде имущества.' },
    { code: '4.2', section: OP, title: 'Вымогательство', text: 'Запрещено требовать деньги или имущество за возврат вещей или прекращение действий.' },
    { code: '4.4', section: OP, title: 'Реальные деньги', text: 'Запрещена продажа и покупка игрового имущества и аккаунтов за реальные деньги.' },
    { code: '5.2', section: OP, title: 'Стороннее ПО', text: 'Запрещено использовать программы и модификации, которые дают преимущество в игре.' },
    { code: '5.3', section: OP, title: 'Урон без причины', text: 'Запрещено убивать или наносить урон без игровой причины.' },
    { code: '5.4', section: OP, title: 'Нарушение ролевой игры', text: 'Запрещены действия, невозможные или нелогичные для персонажа в реальной жизни.' },
    { code: 'GZ 1.1', section: GZ, title: 'Нападения в зелёной зоне', text: 'В зелёной зоне запрещено нападать на игроков и применять оружие.' },
    { code: 'GZ 1.2', section: GZ, title: 'Помехи в зелёной зоне', text: 'В зелёной зоне запрещено мешать игрокам: перекрывать проходы, таранить транспорт.' },
    { code: 'ЖБ 1.1.2', section: ZB, title: 'Назначение раздела жалоб', text: 'Раздел жалоб не предназначен для вопросов и технических проблем. Для них есть репорт и поддержка.' },
    { code: 'ЖБ 1.2.7', section: ZB, title: 'Тон жалобы', text: 'Жалоба с оскорблениями в тексте отклоняется.' },
    { code: 'ЖБ 1.3.3', section: ZB, title: 'Описание жалобы', text: 'Опишите, что произошло, где и когда, укажите ник нарушителя и приложите доказательства.' },
  ].map((r) => Object.assign({ label: /^\d/.test(r.code) ? r.code + ' ОП' : r.code, synthetic: true }, r));

  const ago = (min) => new Date(Date.now() - min * 60000).toISOString();
  const diag = (nlp, ret, gen, chk, inp, out) => ({
    timings_ms: { nlp, retrieval: ret, generation: gen, checks: chk, total: +(nlp + ret + gen + chk).toFixed(1) },
    tokens: { input: inp, output: out },
    // Демо-тариф для иллюстрации расчёта: не замер и не цена провайдера.
    cost_usd: inp || out ? +((inp * 0.10 + out * 0.50) / 1e6).toFixed(6) : 0,
    generation_mode: inp ? 'модель' : 'шаблон',
  });
  const R = (lang, category, priority, extracted, draft, cited, needs_human, confidence, reasons, dup) => ({
    lang, category, priority, is_spam_or_duplicate: !!dup,
    extracted: Object.assign({ nickname: null, rule_refs: [], has_evidence: false, server: null }, extracted),
    draft_reply: { lang, text: draft, cited }, needs_human, confidence, reasons,
  });

  function tickets() {
    const list = [
      { id: 'T-1042', kind: 'complaint', created_at: ago(6), status: 'new', revision: 1, server_lang: 'ru', region: 'cis', reporter: 'pl-a91c', reported_nick: 'Arman_Petrov', rule_refs_raw: '2.1', images_count: 2,
        messages: [{ role: 'player', text: 'Arman_Petrov оскорблял меня и мою семью в чате, скрины есть, 2.1 ОП', attachments: 2 }],
        result: R('ru', 'complaint.insult', 'p2', { nickname: 'Arman_Petrov', rule_refs: ['2.1'], has_evidence: true },
          'Здравствуйте! Вы сообщили, что Arman_Petrov оскорблял вас и вашу семью в чате. Такие действия запрещает пункт 2.1 общих правил. Администратор проверит приложенные скриншоты и примет решение по жалобе.',
          ['2.1'], true, 0.82, ['Решение о наказании принимает администратор', 'Вложения не проверены: известно только их количество (2)']),
        citations: ['2.1', '2.6'], diagnostics: diag(4.1, 11.8, 812, 3.2, 640, 118) },

      { id: 'T-1043', kind: 'report', created_at: ago(9), status: 'reviewed', revision: 2, server_lang: 'ru', region: 'cis', reporter: 'pl-0b7e',
        messages: [{ role: 'player', text: 'Оплатил донат 900 тенге, деньги списались, а голды не пришли уже 2 часа. Что делать?' }],
        result: R('ru', 'report.payment', 'p0', {},
          'Здравствуйте! Передали обращение специалисту по платежам. Чтобы ускорить проверку, ответьте на это сообщение: дата и время оплаты, способ оплаты и сумма. Не отправляйте данные карты и коды из SMS.',
          [], true, 0.93, ['Платежи всегда проверяет человек', 'Нельзя обещать зачисление или возврат средств']),
        citations: [], diagnostics: diag(3.6, 0, 0, 1.9, 0, 0),
        history: [{ minAgo: 4, author: 'Айгерим', action: 'reviewed', note: 'Добавила про чек, остальное ок',
          after: 'Здравствуйте! Передали обращение специалисту по платежам. Чтобы ускорить проверку, ответьте на это сообщение: дата и время оплаты, способ оплаты, сумма и скриншот чека из банка. Не отправляйте данные карты и коды из SMS.' }] },

      { id: 'T-1044', kind: 'report', created_at: ago(12), status: 'new', revision: 1, server_lang: 'kk', region: 'kz', reporter: 'pl-4d22',
        messages: [{ role: 'player', text: 'Сєлеметсіз бе, аккаунтымды бўзып кетті, кіре алмаймын. Машинам да жоќ. Кјмектесіѕізші' }],
        result: R('kk', 'report.account', 'p0', {},
          'Сәлеметсіз бе! Өтінішіңізді аккаунт қауіпсіздігі жөніндегі маманға жібердік. Құпиясөзді және растау кодтарын ешкімге бермеңіз, тіпті әкімшімін деген адамға да. Маман осы өтініш арқылы хабарласады.',
          ['1.4'], true, 0.88, ['Подозрение на взлом аккаунта всегда идёт человеку', 'Текст набран с заменами cp1251 и нормализован']),
        citations: ['1.4'], diagnostics: diag(5.2, 9.4, 905, 3.0, 702, 141) },

      { id: 'T-1045', kind: 'report', created_at: ago(15), status: 'new', revision: 1, server_lang: 'uz', region: 'uz', reporter: 'pl-77aa',
        messages: [{ role: 'player', text: 'Salom, men uy yonida tekstura ichida qotib qoldim, chiqa olmayapman' }],
        result: R('uz', 'report.help', 'p2', {},
          'Salom! Murojaatingizni oldik. Administrator tez orada yordam beradi, iltimos, o‘yindan chiqmang.',
          [], false, 0.79, []),
        citations: [], diagnostics: diag(3.3, 0, 0, 1.4, 0, 0) },

      { id: 'T-1046', kind: 'complaint', created_at: ago(19), status: 'new', revision: 1, server_lang: 'ru', region: 'cis', reporter: 'pl-c310', reported_nick: 'Ivan_Sokolov', rule_refs_raw: '5.2', images_count: 1,
        messages: [{ role: 'player', text: 'Ivan_Sokolov летает на машине по воздуху и стреляет через стены. Видео приложил, 5.2', attachments: 1 }],
        result: R('ru', 'complaint.cheat', 'p1', { nickname: 'Ivan_Sokolov', rule_refs: ['5.2'], has_evidence: true },
          'Здравствуйте! Спасибо за жалобу на Ivan_Sokolov. Использование стороннего ПО запрещает пункт 5.2 общих правил. Администратор изучит видео и примет решение.',
          ['5.2'], true, 0.86, ['Решение о наказании принимает администратор', 'Вложения не проверены: известно только их количество (1)']),
        citations: ['5.2'], diagnostics: diag(4.0, 10.2, 774, 2.8, 598, 96) },

      { id: 'T-1047', kind: 'complaint', created_at: ago(23), status: 'new', revision: 1, server_lang: 'ru', region: 'cis', reporter: 'pl-19e4', reported_nick: 'Lena_Morozova', rule_refs_raw: 'дм', images_count: 2,
        messages: [
          { role: 'player', text: 'Lena_Morozova убила меня у больницы в зелёной зоне без причины, скрины есть', attachments: 2 },
          { role: 'reported_player', text: 'Он первый ударил меня, это была самооборона' }],
        result: R('ru', 'complaint.dm', 'p2', { nickname: 'Lena_Morozova', has_evidence: true },
          'Здравствуйте! Вы сообщили, что Lena_Morozova напала на вас в зелёной зоне. Нападения в зелёной зоне запрещает пункт GZ 1.1. Обвиняемый игрок указал, что защищался, поэтому администратор сверит доказательства обеих сторон.',
          ['GZ 1.1'], true, 0.74, ['Стороны дают разные версии событий', 'Решение о наказании принимает администратор']),
        citations: ['GZ 1.1', '5.3'], diagnostics: diag(4.6, 12.5, 1104, 3.5, 811, 152) },

      { id: 'T-1048', kind: 'complaint', created_at: ago(28), status: 'new', revision: 1, server_lang: 'ru', region: 'cis', reporter: 'pl-5f61', reported_nick: 'Timur_Akhmetov', rule_refs_raw: '4.1', images_count: 3,
        messages: [{ role: 'player', text: 'Договорились с Timur_Akhmetov продать ему машину, он забрал авто и не перевёл деньги. Есть скрины переписки', attachments: 3 }],
        result: R('ru', 'complaint.scam', 'p1', { nickname: 'Timur_Akhmetov', rule_refs: ['4.1'], has_evidence: true },
          'Здравствуйте! Обман при сделках запрещает пункт 4.1 общих правил. Администратор проверит переписку и историю сделки, после чего примет решение по жалобе.',
          ['4.1'], true, 0.84, ['Решение о наказании принимает администратор', 'Вложения не проверены: известно только их количество (3)']),
        citations: ['4.1'], diagnostics: diag(4.2, 9.9, 690, 2.6, 570, 88) },

      { id: 'T-1049', kind: 'complaint', created_at: ago(34), status: 'escalated', revision: 2, server_lang: 'ru', region: 'cis', reporter: 'pl-e0d9', images_count: 1,
        messages: [{ role: 'player', text: 'Меня забанили на 7 дней ни за что! Разбаньте пожалуйста, я ничего не нарушал', attachments: 1 }],
        result: R('ru', 'complaint.admin', 'p2', { has_evidence: true },
          'Здравствуйте! Обращение по поводу блокировки передано старшему администратору. Он проверит основание наказания и сообщит решение в этом обращении.',
          [], true, 0.80, ['Апелляция бана: решение только за человеком', 'Игрок просит разблокировку, черновик её не обещает']),
        citations: ['3.4'], diagnostics: diag(3.9, 8.7, 655, 2.4, 540, 80),
        history: [{ minAgo: 20, author: 'Тимур', action: 'escalated', note: 'Бан выдавал я, пусть смотрит старший' }] },

      { id: 'T-1050', kind: 'complaint', created_at: ago(39), status: 'new', revision: 1, server_lang: 'ru', region: 'cis', reporter: 'pl-2a8b', reported_nick: 'Sergey_Kim', images_count: 1,
        messages: [{ role: 'player', text: 'Sergey_Kim в чате продаёт аккаунт с домом за реальные деньги, пишет писать ему в <handle>', attachments: 1 }],
        result: R('ru', 'complaint.rmt_ads', 'p1', { nickname: 'Sergey_Kim', has_evidence: true },
          'Здравствуйте! Продажа аккаунтов за реальные деньги запрещена пунктом 4.4 общих правил. Администратор проверит сообщения игрока в чате и примет решение.',
          ['4.4'], true, 0.83, ['Решение о наказании принимает администратор']),
        citations: ['4.4', '2.3'], diagnostics: diag(3.8, 10.1, 702, 2.7, 566, 84) },

      { id: 'T-1051', kind: 'complaint', created_at: ago(44), status: 'new', revision: 1, server_lang: 'ru', region: 'cis', reporter: 'pl-63c7', rule_refs_raw: 'жб', images_count: 1,
        messages: [{ role: 'player', text: 'жб', attachments: 1 }],
        result: R('ru', 'complaint.invalid', 'p3', { has_evidence: true },
          'Здравствуйте! В жалобе не хватает описания. По пункту ЖБ 1.3.3 укажите, что произошло, где и когда, ник нарушителя, и приложите доказательства. Подайте жалобу заново с этими данными.',
          ['ЖБ 1.3.3'], false, 0.71, []),
        citations: ['ЖБ 1.3.3'], diagnostics: diag(2.1, 6.3, 0, 1.2, 0, 0) },

      { id: 'T-1052', kind: 'report', created_at: ago(52), status: 'sent', revision: 2, server_lang: 'ru', region: 'cis', reporter: 'pl-9910',
        messages: [{ role: 'player', text: 'ау' }],
        result: R('ru', 'report.offtopic', 'p3', {}, 'Здравствуйте! Опишите, пожалуйста, что случилось, и администратор вам поможет.', [], false, 0.68, []),
        citations: [], diagnostics: diag(1.7, 0, 0, 0.9, 0, 0),
        history: [{ minAgo: 50, author: 'Айгерим', action: 'sent', note: '' }] },

      { id: 'T-1053', kind: 'report', created_at: ago(58), status: 'new', revision: 1, server_lang: 'ru', region: 'cis', reporter: 'pl-3e3e',
        messages: [{ role: 'player', text: 'Как устроиться в полицию? Где взять лицензию?' }],
        result: R('ru', 'report.question', 'p3', {},
          'Здравствуйте! Порядок вступления во фракцию может отличаться на разных серверах. Администратор уточнит актуальные требования и ответит в этом обращении.',
          [], true, 0.55, ['В базе знаний нет проверенной инструкции по трудоустройству']),
        citations: [], diagnostics: diag(2.9, 0, 488, 1.8, 402, 66) },

      { id: 'T-1054', kind: 'report', created_at: ago(63), status: 'new', revision: 1, server_lang: 'en', region: 'eu', reporter: 'pl-71b2',
        messages: [{ role: 'player', text: 'Player John_Miller keeps insulting me in local chat, please check' }],
        result: R('en', 'report.complaint', 'p2', { nickname: 'John_Miller' },
          'Hello! Thank you for the report. Insulting other players is prohibited by rule 2.1 of the general rules. An administrator will check the chat log and decide on next steps.',
          ['2.1'], true, 0.78, ['Решение о наказании принимает администратор']),
        citations: ['2.1'], diagnostics: diag(3.4, 9.0, 640, 2.2, 520, 77) },

      { id: 'T-1055', kind: 'complaint', created_at: ago(71), status: 'new', revision: 1, server_lang: 'kk', region: 'kz', reporter: 'pl-8c04', reported_nick: 'Dias_Volkov', rule_refs_raw: '2.1', images_count: 2,
        messages: [{ role: 'player', text: 'Dias_Volkov чатта мені және отбасымды балағаттады, скриндер бар', attachments: 2 }],
        result: R('kk', 'complaint.insult', 'p2', { nickname: 'Dias_Volkov', rule_refs: ['2.1'], has_evidence: true },
          'Сәлеметсіз бе! Сіз Dias_Volkov чатта сізді және отбасыңызды балағаттағанын хабарладыңыз. Мұндай әрекетке жалпы ережелердің 2.1-тармағы тыйым салады. Әкімші скриншоттарды тексеріп, шешім қабылдайды.',
          ['2.1'], true, 0.80, ['Решение о наказании принимает администратор', 'Вложения не проверены: известно только их количество (2)']),
        citations: ['2.1'], diagnostics: diag(4.4, 11.1, 930, 3.1, 688, 139) },

      { id: 'T-1056', kind: 'complaint', created_at: ago(80), status: 'new', revision: 1, server_lang: 'uz', region: 'uz', reporter: 'pl-d5a0', reported_nick: 'Bobur_Rakhimov', rule_refs_raw: '7.7', images_count: 1,
        messages: [{ role: 'player', text: 'Bobur_Rakhimov chatda onamni haqorat qildi, skrin bor. 7.7 band', attachments: 1 }],
        result: R('uz', 'complaint.insult', 'p2', { nickname: 'Bobur_Rakhimov', rule_refs: ['7.7'], has_evidence: true },
          'Salom! Siz Bobur_Rakhimov chatda oilangizni haqorat qilganini xabar qildingiz. Bunday harakat umumiy qoidalarning 2.1-bandi bilan taqiqlangan. Administrator skrinshotlarni tekshirib, qaror qabul qiladi.',
          ['2.1'], true, 0.77, ['Игрок указал пункт 7.7, которого нет в правилах', 'Решение о наказании принимает администратор']),
        citations: ['2.1'], diagnostics: diag(4.7, 12.0, 960, 3.3, 701, 146) },

      { id: 'T-1057', kind: 'report', created_at: ago(41), status: 'new', revision: 1, server_lang: 'ru', region: 'cis', reporter: 'pl-51c0',
        messages: [{ role: 'player', text: 'помогите застрял в машине под картой' }],
        result: R('ru', 'report.help', 'p2', {}, 'Здравствуйте! Администратор скоро поможет выбраться. Пожалуйста, оставайтесь в игре.', [], false, 0.80, []),
        citations: [], diagnostics: diag(2.2, 0, 0, 1.0, 0, 0) },
      { id: 'T-1058', kind: 'report', created_at: ago(38), status: 'new', revision: 1, server_lang: 'ru', region: 'cis', reporter: 'pl-51c0', duplicate_of: 'T-1057',
        messages: [{ role: 'player', text: 'помогите' }],
        result: R('ru', 'report.help', 'p3', {}, 'Здравствуйте! Ваше обращение T-1057 уже у администратора. Пожалуйста, оставайтесь в игре.', [], false, 0.76,
          ['Повтор: тот же игрок и та же проблема в течение часа (T-1057)'], true),
        citations: [], diagnostics: diag(1.6, 0, 0, 0.8, 0, 0) },
      { id: 'T-1059', kind: 'report', created_at: ago(35), status: 'new', revision: 1, server_lang: 'ru', region: 'cis', reporter: 'pl-51c0', duplicate_of: 'T-1057',
        messages: [{ role: 'player', text: 'ну помогите застрял же' }],
        result: R('ru', 'report.help', 'p3', {}, 'Здравствуйте! Ваше обращение T-1057 уже у администратора. Пожалуйста, оставайтесь в игре.', [], false, 0.76,
          ['Повтор: тот же игрок и та же проблема в течение часа (T-1057)'], true),
        citations: [], diagnostics: diag(1.5, 0, 0, 0.8, 0, 0) },
    ];
    list.forEach((t) => {
      t.draft_original = t.result.draft_reply.text;
      const hist = [{ at: t.created_at, author: 'Copilot', action: 'created', note: '', before: null, after: t.draft_original }];
      let current = t.draft_original;
      (t.history || []).forEach((e) => {
        const after = e.after || current;
        hist.push({ at: ago(e.minAgo), author: e.author, action: e.action, note: e.note, before: current, after });
        current = after;
      });
      t.draft_current = current;
      t.history = hist;
    });
    return list;
  }

  const SAMPLES = [
    { label: 'Жалоба · русский', kind: 'complaint', server_lang: 'ru', attachments: 2, text: 'Max_Fischer оскорбил мою семью в общем чате на сервере 3, скрины приложил. 2.1' },
    { label: 'Қазақша · cp1251', kind: 'report', server_lang: 'kk', attachments: 0, text: 'Сєлеметсіз бе! Мен картада ќатып ќалдым, ќозґала алмаймын. Кјмектесіѕізші' },
    { label: 'Oʻzbekcha', kind: 'complaint', server_lang: 'uz', attachments: 1, text: 'Aziz_Karimov meni sababsiz o‘ldirdi, yashil zonada. Video bor' },
    { label: 'Платёж · English', kind: 'report', server_lang: 'en', attachments: 0, text: 'I paid for gold yesterday but it never arrived. Please refund my money' },
  ];

  SC.demo = { RULES, tickets, SAMPLES };
})();
