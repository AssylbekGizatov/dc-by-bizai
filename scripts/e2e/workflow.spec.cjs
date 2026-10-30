const {test,expect}=require('@playwright/test');
const path=require('path');
const fs=require('fs');
const AxeBuilder=require('@axe-core/playwright').default;
const token=process.env.API_TOKEN;
const text='[Синтетический тест] Alex_Test оскорблял меня в чате на сервере 12. Указан пункт 2.1, есть два скриншота.';
const auth={Authorization:'Bearer '+token};
async function connect(page){
  await page.locator('#connection-open').click();
  await page.locator('#api-token').fill(token);
  await page.locator('#connection-form button[type=submit]').click();
  await expect(page.locator('#connection-status')).toContainText('Доступ подтверждён');
  await page.locator('#connection-close').click();
  await expect(page.locator('#mode')).toHaveText('API подключён');
}
async function create(page,suffix=''){
  await page.goto('/'); await connect(page);
  await page.locator('#text').fill(text+suffix); await page.locator('#player').fill('synthetic-e2e-'+Date.now()+suffix);
  await page.locator('#att').fill('2');
  const response=page.waitForResponse(r=>r.url().endsWith('/api/tickets')&&r.request().method()==='POST');
  await page.locator('#go').dblclick();
  const r=await response;expect(r.status()).toBe(201);const ticket=await r.json();
  await expect(page.locator('#out .draft')).toHaveValue(ticket.draft_reply);
  return ticket;
}
async function openQueue(page,ticket){
  await page.locator('#out').getByRole('link',{name:'Открыть в очереди'}).click();
  await expect(page.locator('#q-detail .draft')).toHaveValue(ticket.draft_reply);
}
async function save(page){
  const response=page.waitForResponse(r=>r.url().endsWith('/review')&&r.request().method()==='PATCH');
  await page.getByRole('button',{name:'Сохранить правку',exact:true}).click();return await response;
}
async function capture(page,name){
  if(process.env.E2E_SCREENSHOTS){fs.mkdirSync(process.env.E2E_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.E2E_SCREENSHOTS,name+'.png'),fullPage:true});}
}

test('real API create → compare → save → 409 fresh fetch → escalation → confirmed simulation → reload',async({page,context,request})=>{
  test.setTimeout(90000);
  let creates=0;page.on('request',r=>{if(r.url().endsWith('/api/tickets')&&r.method()==='POST')creates++;});
  const t=await create(page); expect(creates).toBe(1);expect(t.result.lang).toBe('ru');expect(t.citations.length).toBeGreaterThan(0);
  await expect(page.locator('#out')).toContainText('не проверены');
  await capture(page,'after-desktop');
  await page.locator('#out .draft').fill('Только для копирования, не сохранено');
  expect((await (await request.get('/api/tickets/'+t.id,{headers:auth})).json()).draft_reply).toBe(t.draft_reply);
  await openQueue(page,t);
  await page.getByRole('button',{name:'Править',exact:true}).click();
  await page.locator('#q-detail .draft').fill('Здравствуйте! Обращение требует проверки администратором.');
  await page.locator('#q-admin-note').fill('Первичная заметка');
  expect((await save(page)).status()).toBe(200);
  await expect(page.locator('#q-msg')).toContainText('сохранены');
  console.log('workflow: created and saved');
  const other=await context.newPage();await other.goto('/#queue/'+t.id);await connect(other);
  await other.getByRole('button',{name:'Править',exact:true}).click();
  await other.locator('#q-detail .draft').fill('Свежий ответ второго администратора.');
  await other.locator('#q-admin-note').fill('Заметка второго администратора');
  await page.getByRole('button',{name:'Править',exact:true}).click();
  await page.locator('#q-detail .draft').fill('Мой несохранённый ответ.');await page.locator('#q-admin-note').fill('Моя несохранённая заметка');
  expect((await save(other)).status()).toBe(200);
  expect((await save(page)).status()).toBe(409);
  await expect(page.locator('#q-detail .draft')).toHaveValue('Свежий ответ второго администратора.');
  await expect(page.getByLabel('Несохранённый вариант черновика')).toHaveValue('Мой несохранённый ответ.');
  await expect(page.getByLabel('Несохранённая заметка')).toHaveValue('Моя несохранённая заметка');
  await page.getByRole('button',{name:'Вернуть мой вариант в редактор'}).click();
  expect((await save(page)).status()).toBe(200);
  console.log('workflow: conflict recovered');
  await page.getByRole('button',{name:'Эскалировать',exact:true}).click();await page.locator('#q-note').fill('Проверить доказательства отдельно');
  const escalation=page.waitForResponse(r=>r.url().endsWith('/review'));await page.locator('.escalate').getByRole('button',{name:'Эскалировать',exact:true}).click();
  const escalated=await (await escalation).json();expect(escalated.status).toBe('escalated');expect(escalated.reviewer_note).toContain('Моя несохранённая заметка');
  page.once('dialog',d=>d.dismiss());await page.getByRole('button',{name:'Симулировать отправку'}).click();
  expect((await (await request.get('/api/tickets/'+t.id,{headers:auth})).json()).status).toBe('escalated');
  page.once('dialog',d=>d.accept());const simulation=page.waitForResponse(r=>r.url().endsWith('/review'));await page.getByRole('button',{name:'Симулировать отправку'}).click();
  expect((await (await simulation).json()).status).toBe('simulated_sent');await expect(page.locator('#q-detail')).toContainText('Реальное сообщение не отправлялось');
  console.log('workflow: simulation recorded');
  await capture(page,'after-queue-desktop');
  page.once('dialog',d=>d.accept());await page.reload();await expect(page.locator('#mode')).toContainText('нужен токен');
  await connect(page);
  await expect(page.locator('#q-detail')).toContainText('Реальное сообщение не отправлялось');
  console.log('workflow: reloaded with reauthentication');
  const stored=await (await request.get('/api/tickets/'+t.id,{headers:auth,timeout:10000})).json();expect(stored.revision).toBe(6);
  expect((await (await request.get('/api/tickets/'+t.id+'/feedback',{headers:auth,timeout:10000})).json()).items).toHaveLength(5);
  await other.close();
});

test('late real history response and canceled escalation preserve editor; Back/Forward works',async({page})=>{
  const t=await create(page,' navigation');
  await page.route('**/feedback',async route=>{const response=await route.fetch();const body=await response.body();const status=response.status(),headers=response.headers();await new Promise(r=>setTimeout(r,800));await route.fulfill({body,status,headers});},{times:1});
  await openQueue(page,t);await page.getByRole('button',{name:'Править',exact:true}).click();
  await page.locator('#q-detail .draft').fill('Не терять поздним ответом истории');await page.locator('#q-admin-note').fill('Не терять при отмене');
  await expect(page.locator('#q-history')).toContainText('Пока без правок');
  await expect(page.locator('#q-detail .draft')).toHaveValue('Не терять поздним ответом истории');
  await page.getByRole('button',{name:'Эскалировать',exact:true}).click();await page.locator('.escalate').getByRole('button',{name:'Отмена',exact:true}).click();
  await expect(page.locator('#q-admin-note')).toHaveValue('Не терять при отмене');
  page.once('dialog',d=>d.dismiss());await page.locator('.nav a[data-view=analyze]').click();
  await expect(page.locator('#q-detail .draft')).toHaveValue('Не терять поздним ответом истории');
  expect((await save(page)).status()).toBe(200);
  await page.locator('.detail-back').click();await page.goBack();await expect(page.locator('#q-detail .draft')).toHaveValue('Не терять поздним ответом истории');
  await page.goForward();await expect(page.locator('#q-detail')).toBeEmpty();
});

test('offline and real 401 keep input and never activate demo',async({page,context})=>{
  await page.goto('/');await connect(page);await page.locator('#text').fill(text);
  await context.setOffline(true);await page.locator('#go').click();await expect(page.locator('#form-error')).toContainText('Нет связи');
  await expect(page.locator('#text')).toHaveValue(text);await expect(page.locator('#mode')).toHaveText('API недоступен');
  await context.setOffline(false);
  await page.locator('#connection-open').click();await page.locator('#api-token').fill('invalid-synthetic-token');await page.locator('#connection-form button[type=submit]').click();
  await expect(page.locator('#connection-status')).toContainText('Нужен действующий токен');await page.locator('#connection-close').click();
  await expect(page.locator('#text')).toHaveValue(text);await expect(page.locator('#mode')).toContainText('нужен токен');
});

test('mobile, reduced motion, empty/long input, labels and keyboard focus',async({page})=>{
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});
  const t=await create(page,' mobile');await capture(page,'after-mobile');
  const accessibility=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa','wcag22aa']).analyze();
  expect(accessibility.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))).toEqual([]);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await openQueue(page,t);await capture(page,'after-queue-mobile');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.getByRole('button',{name:'Править',exact:true}).focus();
  await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
  expect(await page.getByRole('button',{name:'Править',exact:true}).evaluate(el=>getComputedStyle(el).outlineStyle)).not.toBe('none');
  await page.goto('/');await connect(page);await page.locator('#go').click();await expect(page.locator('#form-error')).toBeVisible();
  await page.locator('#text').fill('а'.repeat(5000));await page.locator('#go').click();
  // Browser input maxlength and backend bounds are separate; long but allowed content must remain responsive.
  await expect(page.locator('#go')).toBeEnabled();
});

test('real HTTP 429 is explained in browser without replacing input',async({page})=>{
  test.skip(!process.env.E2E_RATE_URL,'separate low-limit real API required');
  await page.goto(process.env.E2E_RATE_URL);await connect(page);
  for(let i=0;i<5;i++){
    await page.locator('#text').fill(text+' rate '+i);const response=page.waitForResponse(r=>r.url().endsWith('/api/tickets')&&r.request().method()==='POST');
    await page.locator('#go').click();const status=(await response).status();
    if(status===429){await expect(page.locator('#form-error')).toContainText('Лимит запросов');await expect(page.locator('#text')).toHaveValue(text+' rate '+i);return;}
    expect(status).toBe(201);await expect(page.locator('#go')).toBeEnabled();
  }
  throw Error('Expected a real server rate limit');
});

test('real API with mock provider failure saves safe fallback and labels it honestly',async({page,request})=>{
  test.skip(!process.env.E2E_MODEL_ERROR_URL,'fault-injection API required');
  await page.goto(process.env.E2E_MODEL_ERROR_URL);await connect(page);
  await page.locator('input[name=kind][value=report]').check();
  await page.locator('#text').fill('Здравствуйте! Как выбрать работу в игре? Нужна инструкция.');
  const response=page.waitForResponse(r=>r.url().endsWith('/api/tickets')&&r.request().method()==='POST');
  await page.locator('#go').click();const created=await response;expect(created.status()).toBe(201);
  const ticket=await created.json();expect(ticket.diagnostics.generation_mode).toBe('local_template');
  expect(ticket.diagnostics.warnings).toContain('groq_unavailable_or_invalid_safe_fallback');
  await expect(page.locator('.generation-source')).toContainText('генерация API недоступна');
  await expect(page.locator('#mode')).toHaveText('API подключён');
  const stored=await request.get(process.env.E2E_MODEL_ERROR_URL+'/api/tickets/'+ticket.id,{headers:auth});
  expect(stored.status()).toBe(200);expect((await stored.json()).draft_reply).toBe(ticket.draft_reply);
});
