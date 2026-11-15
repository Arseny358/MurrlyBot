const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  try { tg.setHeaderColor('secondary_bg_color'); } catch (_) {}
}

const initData = tg?.initData || '';
const appEl = document.getElementById('app');
const toastEl = document.getElementById('toast');
const modalEl = document.getElementById('modal');
const modalTitle = document.getElementById('modal-title');
const modalBody = document.getElementById('modal-body');
document.getElementById('modal-close').onclick = closeModal;
modalEl.addEventListener('click', e => { if (e.target === modalEl) closeModal(); });

let state = null;
let currentTab = 'home';
let marketRange = '24h';
let adminSession = sessionStorage.getItem('murrly_admin_session') || '';
let refreshTimer = null;

const esc = (v='') => String(v)
  .replaceAll('&','&amp;').replaceAll('<','&lt;')
  .replaceAll('>','&gt;').replaceAll('"','&quot;');

function haptic(type='light') {
  try { tg?.HapticFeedback?.impactOccurred(type); } catch (_) {}
}
function notify(type='success') {
  try { tg?.HapticFeedback?.notificationOccurred(type); } catch (_) {}
}
function toast(text, error=false) {
  toastEl.textContent = text;
  toastEl.className = error ? 'show error' : 'show';
  clearTimeout(toastEl._t);
  toastEl._t = setTimeout(() => toastEl.className = '', 2600);
}
function openModal(title, html) {
  modalTitle.textContent = title;
  modalBody.innerHTML = html;
  modalEl.classList.remove('hidden');
}
function closeModal() { modalEl.classList.add('hidden'); }

async function confirmAction(text) {
  if (tg?.showConfirm) {
    return new Promise(resolve => tg.showConfirm(text, resolve));
  }
  return window.confirm(text);
}

async function api(path, options={}) {
  const headers = {
    'X-Telegram-Init-Data': initData,
    ...(options.headers || {})
  };
  if (adminSession) headers['X-Admin-Session'] = adminSession;
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  const res = await fetch(path, {...options, headers});
  const type = res.headers.get('content-type') || '';

  if (!res.ok) {
    let msg = `Ошибка ${res.status}`;
    try {
      if (type.includes('json')) {
        const e = await res.json();
        msg = e.detail || msg;
      }
    } catch (_) {}

    if (res.status === 401 && path.startsWith('/api/admin')) {
      adminSession = '';
      sessionStorage.removeItem('murrly_admin_session');
    }
    throw new Error(msg);
  }

  if (type.includes('application/json')) return res.json();
  return res;
}

function fmt(v, digits=2) {
  const n = Number(v || 0);
  return n.toLocaleString('ru-RU', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits
  });
}
function fmtTime(seconds) {
  seconds = Math.max(0, Number(seconds || 0));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h) return `${h} ч. ${m} мин.`;
  return `${m} мин.`;
}
function userName() {
  const u = state.user;
  return [u.first_name, u.last_name].filter(Boolean).join(' ') || u.username || 'Пользователь';
}
function avatar() {
  if (state.user.photo_url) return `<img class="avatar" src="${esc(state.user.photo_url)}" alt="">`;
  return `<div class="avatar">🐝</div>`;
}
function profileItem(label, value) {
  return `<div class="profile-item"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;
}

function header() {
  return `<div class="hero">
    <div class="user-row">
      ${avatar()}
      <div>
        <div class="user-name">${esc(userName())}</div>
        <div class="sub">${state.vip.active ? '👑 VIP активен' : 'Добро пожаловать в MurrlyBot'}</div>
      </div>
    </div>
    <div class="balance">
      <span class="num">${state.wallet.balance}</span>
      <span class="unit">🍯 мёдика</span>
    </div>
  </div>`;
}

function nav() {
  return `<div class="nav">
    ${navBtn('home','🏠','Главная')}
    ${navBtn('farm','🐝','Ферма')}
    ${navBtn('shop','🎁','Магазин')}
    ${navBtn('exchange','📈','Биржа')}
    ${navBtn('profile','👤','Профиль')}
  </div>`;
}
function navBtn(key, ico, title) {
  return `<button data-tab="${key}" class="${currentTab===key?'active':''}">
    <span class="ico">${ico}</span>${title}
  </button>`;
}

function render() {
  if (!state) return;
  let content = '';
  if (currentTab === 'home') content = homeView();
  if (currentTab === 'farm') content = farmView();
  if (currentTab === 'shop') content = shopView();
  if (currentTab === 'exchange') content = exchangeView();
  if (currentTab === 'profile') content = profileView();

  appEl.innerHTML = `<div class="shell">${header()}${content}</div>${nav()}`;

  document.querySelectorAll('[data-tab]').forEach(btn => btn.onclick = async () => {
    haptic();
    currentTab = btn.dataset.tab;
    render();
    if (currentTab === 'shop') await refreshShop();
    if (currentTab === 'exchange') await refreshMarket();
    if (currentTab === 'farm') await refreshFarm();
  });

  bindActions();
  if (currentTab === 'exchange' && state.market) {
    requestAnimationFrame(drawMarketChart);
  }
}

function homeView() {
  const f = state.farm;
  const vip = state.vip;
  const marriage = state.marriage;
  const golden = state.farm_extra?.golden?.balance || 0;

  return `
    <div class="grid2">
      <div class="card" data-go="farm">
        <span class="badge">${f.emoji || '🐝'} Ферма L${f.level}</span>
        <div class="big" style="margin-top:10px">${Math.floor(f.stored)} / ${f.capacity} 🍯</div>
        <div class="muted">${esc(f.stage_name || '')}</div>
      </div>
      <div class="card" data-open="vip">
        <span class="badge">👑 VIP</span>
        <div class="big" style="margin-top:10px">${vip.active ? 'Активен' : 'Не активен'}</div>
        <div class="muted">${vip.active ? `${vip.remaining_days} дн. ${vip.remaining_hours} ч.` : 'Открыть тарифы'}</div>
      </div>
    </div>

    <div class="section-title"><h2>Твой мир</h2></div>
    <div class="grid2">
      <div class="card">
        <h3>🎁 Коллекция</h3>
        <div class="big">${state.gifts_total}</div>
        <div class="muted">подарков</div>
      </div>
      <div class="card">
        <h3>✨ Золотой мёд</h3>
        <div class="big">${golden}</div>
        <div class="muted">редкий ресурс</div>
      </div>
      <div class="card">
        <h3>💍 Брак</h3>
        <div class="big">${marriage ? `${marriage.health}%` : '—'}</div>
        <div class="muted">${marriage ? esc(marriage.partner_name) : 'Пока не заключён'}</div>
      </div>
      <div class="card" data-go="exchange">
        <h3>📈 Медовая биржа</h3>
        <div class="big">HNY</div>
        <div class="muted">игровой рынок</div>
      </div>
    </div>

    <div class="section-title"><h2>Информация</h2></div>
    <button class="btn secondary" data-open="rules">📜 Правила</button>
  `;
}

function farmView() {
  const f = state.farm;
  const extra = state.farm_extra || {};
  const pct = Math.max(0, Math.min(100, Math.floor((Number(f.stored) / Number(f.capacity)) * 100)));
  const full = Number(f.stored) >= Number(f.capacity);
  const event = extra.event;
  const boost = extra.boost || {active:false};
  const golden = extra.golden || {balance:0,total_found:0};
  const improvements = extra.improvements || [];
  const tasks = state.tasks || [];

  return `
    <div class="section-title">
      <h2>🐝 Медовая ферма</h2>
      <span class="badge">L${f.level}/${f.max_level}</span>
    </div>

    <div class="card">
      <div class="farm-scene">
        <div>
          <div class="stage-emoji">${f.emoji || '🐝'}</div>
          <div class="farm-stage-name">${esc(f.stage_name || `Ферма L${f.level}`)}</div>
        </div>
        <div class="mascot">${full ? '🐱🍯' : event ? '🐱✨' : '🐱🐝'}</div>
      </div>

      <div class="progress"><div style="width:${pct}%"></div></div>
      <div style="display:flex;justify-content:space-between;font-size:13px">
        <span>${Math.floor(f.stored)} 🍯</span>
        <span class="muted">${f.capacity} 🍯</span>
      </div>

      <div class="stats-row">
        <div class="stat"><b>${f.production}</b><span>🍯 / сутки</span></div>
        <div class="stat"><b>${f.capacity}</b><span>вместимость</span></div>
        <div class="stat"><b>${pct}%</b><span>заполнено</span></div>
      </div>

      ${f.vip_active ? `<p class="badge" style="margin-top:12px">👑 VIP усиливает ферму</p>` : ''}
      ${full ? `<p class="muted">⚠️ Соты заполнены — производство остановлено до сбора.</p>` : ''}

      <button class="btn" id="farm-collect" style="margin-top:14px">🍯 Собрать мёдик</button>
      ${f.upgrade_cost == null
        ? `<button class="btn secondary" disabled>🌟 Максимальный уровень фермы</button>`
        : `<button class="btn secondary" id="farm-upgrade">⬆️ Улучшить до L${Number(f.level)+1} за ${f.upgrade_cost} 🍯</button>`}
    </div>

    <div class="section-title"><h2>⚡ Состояние пасеки</h2></div>
    ${event ? `
      <div class="card event-card">
        <span class="badge green">${event.emoji} Событие</span>
        <h3 style="margin-top:10px">${esc(event.name)}</h3>
        <div>${esc(event.description)}</div>
        <div class="muted" style="margin-top:5px">Осталось: ${fmtTime(event.remaining_seconds)}</div>
      </div>` : `
      <div class="card"><div class="muted">Сейчас на пасеке спокойно. Случайное событие может появиться позже.</div></div>`}

    <div class="card" style="margin-top:10px">
      <div class="task-top">
        <div>
          <b>🍬 Покормить пчёл</b>
          <div class="muted">+${boost.bonus_pct || 20}% к производству на ${boost.duration_minutes || 180} мин.</div>
        </div>
        <span class="badge">${boost.cost || 10} 🍯</span>
      </div>
      ${boost.active
        ? `<button class="btn success" disabled style="margin-top:10px">✅ Буст активен · ${fmtTime(boost.remaining_seconds)}</button>`
        : `<button class="btn secondary" id="farm-boost" style="margin-top:10px">Активировать буст</button>`}
    </div>

    <div class="grid2">
      <div class="card">
        <h3>✨ Золотой мёд</h3>
        <div class="big">${golden.balance || 0}</div>
        <div class="muted">Найдено всего: ${golden.total_found || 0}</div>
      </div>
      <div class="card">
        <h3>🧰 Улучшения</h3>
        <div class="big">${improvements.reduce((a,x)=>a+Number(x.level||0),0)}</div>
        <div class="muted">суммарных уровней</div>
      </div>
    </div>

    <div class="section-title"><h2>🧰 Улучшения пасеки</h2></div>
    <div class="improvement-grid">
      ${improvements.map(imp => `
        <div class="improvement">
          <div class="imp-icon">${imp.emoji}</div>
          <h3>${esc(imp.name)} · L${imp.level}/${imp.max_level}</h3>
          <p>${imp.effect === 'capacity' ? '📦 Вместимость' : '🍯 Производство'}:
             +${fmt(imp.total_bonus_pct,1)}%</p>
          ${imp.upgrade_cost == null
            ? `<button class="btn small secondary" disabled>Максимум</button>`
            : `<button class="btn small secondary farm-improve" data-key="${imp.key}">
                 ⬆️ ${imp.upgrade_cost} 🍯
               </button>`}
        </div>`).join('')}
    </div>

    <div class="section-title"><h2>📋 Задания на сегодня</h2></div>
    <div class="card">
      ${tasks.map(taskRow).join('')}
    </div>
  `;
}

function taskRow(t) {
  const p = Math.min(Number(t.progress || 0), Number(t.goal || 1));
  return `<div class="task">
    <div class="task-top">
      <div class="task-title">${t.emoji} ${esc(t.title)}</div>
      <div class="task-reward">+${t.reward} 🍯</div>
    </div>
    <div class="task-progress">${fmt(p,0)} / ${t.goal}</div>
    ${t.claimed
      ? `<button class="btn small success" disabled>✅ Получено</button>`
      : t.complete
        ? `<button class="btn small task-claim" data-key="${t.key}">🎁 Забрать награду</button>`
        : `<button class="btn small secondary" disabled>В процессе</button>`}
  </div>`;
}

function shopView() {
  const catalog = state.shop?.catalog || {};
  const inv = state.shop?.inventory?.items || [];
  const owned = Object.fromEntries(inv.map(i => [i.key, i.count]));
  const resale = state.shop?.resale_pct ?? 60;

  return `
    <div class="section-title">
      <h2>🎁 Магазин</h2>
      <span class="badge">${state.wallet.balance} 🍯</span>
    </div>
    <div class="card" style="margin-bottom:12px">
      <div class="muted">Продажа возвращает <b>${fmt(resale,1)}%</b> текущей цены подарка.</div>
    </div>

    <div class="shop-grid">
      ${Object.entries(catalog).map(([key,p]) => `
        <div class="product">
          <div class="emoji">${p.emoji}</div>
          <h3>${esc(p.name)}</h3>
          <div class="price">Купить: ${p.price} 🍯</div>
          <div class="sell-price">Продать: ${p.resale_price} 🍯</div>
          <div class="owned">У тебя: ${owned[key] || 0}</div>
          <div class="product-actions">
            <button class="btn small buy-gift" data-gift="${key}">Купить</button>
            <button class="btn small secondary sell-gift" data-gift="${key}" ${owned[key] ? '' : 'disabled'}>Продать</button>
          </div>
        </div>`).join('')}
    </div>
  `;
}

function exchangeView() {
  const m = state.market;
  if (!m) {
    return `<div class="section-title"><h2>📈 Медовая биржа</h2></div>
      <div class="card"><div class="muted">Загружаем рынок HNY…</div></div>`;
  }

  const p = m.portfolio;
  const changeClass = Number(m.change_24h_pct) >= 0 ? 'positive' : 'negative';
  const changeSign = Number(m.change_24h_pct) >= 0 ? '+' : '';

  return `
    <div class="section-title"><h2>📈 Медовая биржа</h2><span class="badge green">HNY</span></div>

    <div class="card market-hero">
      <div class="muted">1 HNY</div>
      <div>
        <span class="market-price">${fmt(m.price,4)} 🍯</span>
        <span class="market-change ${changeClass}">${changeSign}${fmt(m.change_24h_pct,2)}%</span>
      </div>
      <div class="muted">24ч: ${fmt(m.min_24h,4)} — ${fmt(m.max_24h,4)} 🍯</div>

      <div class="chart-wrap"><canvas id="market-chart"></canvas></div>
      <div class="range-row">
        ${['1h','6h','24h','7d'].map(r => `
          <button class="range-btn ${marketRange===r?'active':''}" data-range="${r}">${r}</button>
        `).join('')}
      </div>
    </div>

    <div class="section-title"><h2>💼 Портфель</h2></div>
    <div class="grid2">
      <div class="card">
        <h3>HNY</h3>
        <div class="big">${fmt(p.shares,6)}</div>
        <div class="muted">≈ ${fmt(p.current_value,2)} 🍯</div>
      </div>
      <div class="card">
        <h3>Результат</h3>
        <div class="big ${Number(p.unrealized_profit)>=0?'positive':'negative'}">
          ${Number(p.unrealized_profit)>=0?'+':''}${fmt(p.unrealized_profit,2)} 🍯
        </div>
        <div class="muted">${Number(p.return_pct)>=0?'+':''}${fmt(p.return_pct,2)}%</div>
      </div>
    </div>

    <div class="trade-grid" style="margin-top:12px">
      <div class="trade-box">
        <h3>🟢 Купить HNY</h3>
        <input class="input" id="buy-honey" inputmode="numeric" placeholder="Сколько 🍯 вложить">
        <div class="muted" style="font-size:11px;margin-bottom:8px">Комиссия: ${fmt(m.fees.buy_pct,2)}%</div>
        <button class="btn" id="market-buy" ${m.enabled?'':'disabled'}>Купить</button>
      </div>
      <div class="trade-box">
        <h3>🔴 Продать HNY</h3>
        <input class="input" id="sell-shares" inputmode="decimal" placeholder="Сколько HNY">
        <div class="muted" style="font-size:11px;margin-bottom:8px">Комиссия: ${fmt(m.fees.sell_pct,2)}%</div>
        <button class="btn secondary" id="market-sell" ${m.enabled?'':'disabled'}>Продать</button>
      </div>
    </div>

    <div class="section-title"><h2>📜 Последние сделки</h2></div>
    <div class="card">
      ${m.trades.length ? m.trades.map(tradeRow).join('') : '<div class="muted">Сделок пока нет.</div>'}
    </div>

    <div class="card" style="margin-top:12px">
      <div class="muted">${esc(m.disclaimer)}</div>
    </div>
  `;
}

function tradeRow(t) {
  const buy = t.side === 'buy';
  const result = t.realized_profit == null ? '' :
    ` · <span class="${Number(t.realized_profit)>=0?'positive':'negative'}">${Number(t.realized_profit)>=0?'+':''}${fmt(t.realized_profit,2)} 🍯</span>`;
  return `<div class="trade-row">
    <b>${buy ? '🟢 Покупка' : '🔴 Продажа'}</b>
    · ${fmt(t.shares,6)} HNY по ${fmt(t.price,4)} 🍯
    ${result}
  </div>`;
}

function profileView() {
  const p = state.profile || {};
  const golden = state.farm_extra?.golden?.balance || 0;

  return `
    <div class="section-title"><h2>👤 Профиль</h2></div>
    <div class="profile-list">
      ${profileItem('Имя / ник', p.display_name || userName())}
      ${profileItem('Возраст', p.age ?? 'не указано')}
      ${profileItem('Город', p.city || 'не указан')}
      ${profileItem('Пол', p.gender || 'не указан')}
      ${profileItem('О себе', p.bio || 'не заполнено')}
      ${profileItem('Всего заработано', `${state.wallet.total_earned} 🍯`)}
      ${profileItem('Поймано раздач', state.wallet.giveaways_claimed)}
      ${profileItem('Золотой мёд', `${golden} ✨`)}
    </div>

    <div class="section-title"><h2>Дополнительно</h2></div>
    <button class="btn secondary" data-open="vip">👑 VIP</button>
    <button class="btn secondary" data-open="rules">📜 Правила</button>
    ${state.admin_eligible ? `<button class="btn" id="open-admin">🛠 Панель управления</button>` : ''}
  `;
}

async function refreshAll() {
  state = await api('/api/bootstrap');
  render();
}

async function refreshFarm() {
  try {
    const d = await api('/api/farm');
    state.farm = d.farm;
    state.farm_extra = {
      improvements: d.improvements,
      boost: d.boost,
      event: d.event,
      golden: d.golden
    };
    state.tasks = d.tasks;
    state.wallet = d.wallet;
    render();
  } catch (e) { toast(e.message, true); }
}

async function refreshShop() {
  try {
    const shop = await api('/api/shop');
    state.shop = shop;
    state.wallet = shop.wallet;
    render();
  } catch (e) { toast(e.message, true); }
}

async function refreshMarket() {
  try {
    const market = await api(`/api/exchange?range=${encodeURIComponent(marketRange)}`);
    state.market = market;
    state.wallet.balance = market.wallet_balance;
    render();
    requestAnimationFrame(drawMarketChart);
  } catch (e) { toast(e.message, true); }
}

function bindActions() {
  document.querySelectorAll('[data-go]').forEach(el => el.onclick = async () => {
    currentTab = el.dataset.go;
    render();
    if (currentTab === 'exchange') await refreshMarket();
    if (currentTab === 'shop') await refreshShop();
    if (currentTab === 'farm') await refreshFarm();
  });

  document.querySelectorAll('[data-open="rules"]').forEach(el => el.onclick = showRules);
  document.querySelectorAll('[data-open="vip"]').forEach(el => el.onclick = showVip);

  const collect = document.getElementById('farm-collect');
  if (collect) collect.onclick = farmCollect;
  const upgrade = document.getElementById('farm-upgrade');
  if (upgrade) upgrade.onclick = farmUpgrade;
  const boost = document.getElementById('farm-boost');
  if (boost) boost.onclick = farmBoost;

  document.querySelectorAll('.farm-improve').forEach(btn =>
    btn.onclick = () => farmImprove(btn.dataset.key)
  );
  document.querySelectorAll('.task-claim').forEach(btn =>
    btn.onclick = () => claimTask(btn.dataset.key)
  );

  document.querySelectorAll('.buy-gift').forEach(btn =>
    btn.onclick = () => buyGift(btn.dataset.gift)
  );
  document.querySelectorAll('.sell-gift').forEach(btn =>
    btn.onclick = () => sellGift(btn.dataset.gift)
  );

  document.querySelectorAll('.range-btn').forEach(btn =>
    btn.onclick = async () => {
      marketRange = btn.dataset.range;
      await refreshMarket();
    }
  );

  const marketBuy = document.getElementById('market-buy');
  if (marketBuy) marketBuy.onclick = marketBuyHny;
  const marketSell = document.getElementById('market-sell');
  if (marketSell) marketSell.onclick = marketSellHny;

  const admin = document.getElementById('open-admin');
  if (admin) admin.onclick = openAdmin;
}

function showRules() {
  openModal('📜 Правила', `<div class="rules-text">${esc(state.rules)}</div>`);
}

async function showVip() {
  try {
    const data = await api('/api/vip');
    const s = data.status;
    openModal('👑 VIP', `
      <div class="card">
        <div class="big">${s.active ? '✅ Активен' : 'Не активен'}</div>
        <p class="muted">${s.active ? `Осталось ${s.remaining_days} дн. ${s.remaining_hours} ч.` : 'Выбери срок VIP'}</p>
        <div class="profile-list">
          ${profileItem('🐝 Производство фермы', `+${data.bonuses.farm_production_pct}%`)}
          ${profileItem('📦 Вместимость фермы', `+${data.bonuses.farm_capacity_pct}%`)}
          ${profileItem('🍯 Порция раздачи', `+${data.bonuses.giveaway_pct}%`)}
          ${profileItem('✨ Шанс золотого мёда', `+${data.bonuses.golden_chance_pct}%`)}
        </div>
        <button class="btn vip-buy" data-plan="7" style="margin-top:12px">👑 ${data.plans['7'].days} дней · ${data.plans['7'].price} 🍯</button>
        <button class="btn secondary vip-buy" data-plan="30">💎 ${data.plans['30'].days} дней · ${data.plans['30'].price} 🍯</button>
      </div>`);
    document.querySelectorAll('.vip-buy').forEach(b => b.onclick = () => buyVip(Number(b.dataset.plan)));
  } catch(e) { toast(e.message, true); }
}

async function buyVip(plan) {
  try {
    const data = await api(`/api/vip/buy/${plan}`, {method:'POST'});
    if (data.result.status === 'insufficient') throw new Error(`Не хватает ${data.result.need} 🍯`);
    if (data.result.status !== 'ok') throw new Error('Не удалось купить VIP');
    notify('success');
    toast(`VIP продлён на ${data.result.days} дней`);
    closeModal();
    await refreshAll();
  } catch(e) { notify('error'); toast(e.message, true); }
}

async function farmCollect() {
  try {
    const d = await api('/api/farm/collect', {method:'POST'});
    if (d.result.status === 'empty') {
      toast('В сотах пока меньше 1 🍯');
    } else {
      let msg = `+${d.result.amount} 🍯 в копилку`;
      if (d.result.golden?.found) msg += ' · ✨ найден золотой мёд!';
      notify('success');
      toast(msg);
    }
    applyFarmData(d.farm_data);
  } catch(e) { toast(e.message, true); }
}

async function farmUpgrade() {
  try {
    const d = await api('/api/farm/upgrade', {method:'POST'});
    if (d.result.status === 'insufficient') throw new Error(`Не хватает ${d.result.need} 🍯`);
    if (d.result.status === 'max') throw new Error('Ферма уже максимального уровня');
    notify('success');
    toast(`Ферма улучшена до L${d.result.farm.level}`);
    applyFarmData(d.farm_data);
  } catch(e) { notify('error'); toast(e.message, true); }
}

async function farmImprove(key) {
  try {
    const d = await api(`/api/farm/improvement/${encodeURIComponent(key)}`, {method:'POST'});
    if (d.result.status === 'insufficient') throw new Error(`Не хватает ${d.result.need} 🍯`);
    if (d.result.status === 'max') throw new Error('Улучшение уже максимального уровня');
    if (d.result.status !== 'ok') throw new Error('Не удалось улучшить пасеку');
    notify('success');
    toast('Улучшение куплено');
    applyFarmData(d.farm_data);
  } catch(e) { notify('error'); toast(e.message, true); }
}

async function farmBoost() {
  try {
    const d = await api('/api/farm/boost', {method:'POST'});
    if (d.result.status === 'insufficient') throw new Error(`Не хватает ${d.result.need} 🍯`);
    if (d.result.status === 'active') throw new Error(`Буст уже активен ещё ${fmtTime(d.result.remaining_seconds)}`);
    if (d.result.status !== 'ok') throw new Error('Не удалось активировать буст');
    notify('success');
    toast('Пчёлы накормлены — производство ускорено');
    applyFarmData(d.farm_data);
  } catch(e) { notify('error'); toast(e.message, true); }
}

function applyFarmData(d) {
  state.farm = d.farm;
  state.farm_extra = {
    improvements: d.improvements,
    boost: d.boost,
    event: d.event,
    golden: d.golden
  };
  state.tasks = d.tasks;
  state.wallet = d.wallet;
  currentTab = 'farm';
  render();
}

async function claimTask(key) {
  try {
    const d = await api(`/api/tasks/claim/${encodeURIComponent(key)}`, {method:'POST'});
    if (d.result.status === 'not_ready') throw new Error('Задание ещё не выполнено');
    if (d.result.status === 'claimed') throw new Error('Награда уже получена');
    if (d.result.status !== 'ok') throw new Error('Не удалось получить награду');
    state.tasks = d.tasks;
    state.wallet = d.wallet;
    notify('success');
    toast(`+${d.result.reward} 🍯 за задание`);
    render();
  } catch(e) { toast(e.message, true); }
}

async function buyGift(key) {
  try {
    const d = await api(`/api/shop/buy/${encodeURIComponent(key)}`, {method:'POST'});
    if (d.result.status === 'insufficient') throw new Error(`Не хватает ${d.result.need} 🍯`);
    if (d.result.status !== 'ok') throw new Error('Не удалось купить подарок');
    notify('success');
    toast(`${d.result.gift.emoji} Куплено`);
    state.shop.inventory = d.inventory;
    state.shop.wallet = d.wallet;
    state.wallet = d.wallet;
    state.tasks = d.tasks;
    render();
  } catch(e) { notify('error'); toast(e.message, true); }
}

async function sellGift(key) {
  const p = state.shop?.catalog?.[key];
  if (!p) return;
  const ok = await confirmAction(`Продать ${p.emoji} ${p.name} за ${p.resale_price} 🍯?`);
  if (!ok) return;

  try {
    const d = await api(`/api/shop/sell/${encodeURIComponent(key)}`, {method:'POST'});
    if (d.result.status === 'not_owned') throw new Error('Такого подарка уже нет в инвентаре');
    if (d.result.status !== 'ok') throw new Error('Не удалось продать подарок');
    notify('success');
    toast(`Продано · +${d.result.received} 🍯`);
    state.shop.inventory = d.inventory;
    state.shop.wallet = d.wallet;
    state.wallet = d.wallet;
    render();
  } catch(e) { notify('error'); toast(e.message, true); }
}

async function marketBuyHny() {
  const input = document.getElementById('buy-honey');
  const amount = Number(input?.value || 0);
  if (!Number.isFinite(amount) || amount <= 0) {
    toast('Укажи количество мёдика', true);
    return;
  }
  try {
    const d = await api('/api/exchange/buy', {
      method:'POST',
      body:JSON.stringify({honey_amount:amount})
    });
    if (d.result.status === 'insufficient') throw new Error(`Не хватает ${d.result.need} 🍯`);
    if (d.result.status === 'disabled') throw new Error('Биржа сейчас отключена');
    if (d.result.status !== 'ok') throw new Error('Не удалось купить HNY');
    notify('success');
    toast(`Куплено ${fmt(d.result.shares,6)} HNY`);
    state.market = d.market;
    state.wallet.balance = d.market.wallet_balance;
    state.tasks = d.tasks;
    render();
    requestAnimationFrame(drawMarketChart);
  } catch(e) { notify('error'); toast(e.message, true); }
}

async function marketSellHny() {
  const input = document.getElementById('sell-shares');
  const shares = Number(String(input?.value || '').replace(',','.'));
  if (!Number.isFinite(shares) || shares <= 0) {
    toast('Укажи количество HNY', true);
    return;
  }
  try {
    const d = await api('/api/exchange/sell', {
      method:'POST',
      body:JSON.stringify({shares})
    });
    if (d.result.status === 'insufficient_shares') throw new Error(`У тебя только ${fmt(d.result.held,6)} HNY`);
    if (d.result.status === 'disabled') throw new Error('Биржа сейчас отключена');
    if (d.result.status !== 'ok') throw new Error('Не удалось продать HNY');
    notify('success');
    toast(`Получено ${d.result.received} 🍯`);
    state.market = d.market;
    state.wallet.balance = d.market.wallet_balance;
    state.tasks = d.tasks;
    render();
    requestAnimationFrame(drawMarketChart);
  } catch(e) { notify('error'); toast(e.message, true); }
}

function drawMarketChart() {
  const canvas = document.getElementById('market-chart');
  const history = state.market?.history || [];
  if (!canvas || history.length < 1) return;

  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;
  const pad = 10;
  const vals = history.map(x => Number(x.price));
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = Math.max(0.0001, max - min);

  ctx.clearRect(0,0,w,h);

  ctx.strokeStyle = 'rgba(255,255,255,.06)';
  ctx.lineWidth = 1;
  for (let i=1;i<4;i++) {
    const y = (h/4)*i;
    ctx.beginPath();
    ctx.moveTo(0,y);
    ctx.lineTo(w,y);
    ctx.stroke();
  }

  const points = vals.map((v,i) => ({
    x: pad + (w - pad*2) * (vals.length === 1 ? 0.5 : i / (vals.length - 1)),
    y: pad + (h - pad*2) * (1 - (v - min) / span)
  }));

  const grad = ctx.createLinearGradient(0,0,0,h);
  grad.addColorStop(0,'rgba(78,203,113,.28)');
  grad.addColorStop(1,'rgba(78,203,113,0)');

  ctx.beginPath();
  ctx.moveTo(points[0].x,h-pad);
  points.forEach(p => ctx.lineTo(p.x,p.y));
  ctx.lineTo(points[points.length-1].x,h-pad);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.beginPath();
  points.forEach((p,i) => i ? ctx.lineTo(p.x,p.y) : ctx.moveTo(p.x,p.y));
  ctx.strokeStyle = '#70df91';
  ctx.lineWidth = 2.2;
  ctx.stroke();
}

// ---------------- ADMIN UI ----------------

async function openAdmin() {
  if (!state.admin_eligible) return;
  if (!adminSession) {
    openModal('🛠 Вход администратора', `
      <p class="muted">Telegram ID уже проверен. Для второго уровня защиты введи админ-пароль.</p>
      <input class="input" id="admin-password" type="password" placeholder="Пароль" autocomplete="current-password">
      <button class="btn" id="admin-login" style="margin-top:10px">Войти</button>
    `);
    document.getElementById('admin-login').onclick = adminLogin;
    return;
  }
  await renderAdmin();
}

async function adminLogin() {
  const password = document.getElementById('admin-password').value;
  try {
    const d = await api('/api/admin/login', {
      method:'POST',
      body:JSON.stringify({password})
    });
    adminSession = d.session;
    sessionStorage.setItem('murrly_admin_session', adminSession);
    closeModal();
    notify('success');
    await renderAdmin();
  } catch(e) { notify('error'); toast(e.message, true); }
}

const groupNames = {
  farm_levels:'🐝 Ферма — 12 уровней',
  farm_extras:'🌻 Ферма — улучшения и события',
  exchange:'📈 Медовая биржа HNY',
  honey:'🎉 Раздачи',
  gifts:'🎁 Подарки',
  vip:'👑 VIP',
  backup:'💾 Бэкапы',
  rules:'📜 Правила',
};

async function renderAdmin() {
  try {
    const d = await api('/api/admin/dashboard');
    appEl.innerHTML = `<div class="shell">
      <div class="admin-top">
        <div>
          <div class="admin-title">🛠 Админ-панель</div>
          <div class="sub">Доступна только твоему Telegram ID</div>
        </div>
        <button class="icon-btn" id="admin-close">✕</button>
      </div>

      <div class="grid2">
        <div class="card"><h3>👥 Пользователи</h3><div class="big">${d.stats.users}</div></div>
        <div class="card"><h3>🍯 В экономике</h3><div class="big">${d.stats.honey_total}</div></div>
        <div class="card"><h3>📈 Инвесторов HNY</h3><div class="big">${d.stats.exchange_players || 0}</div></div>
        <div class="card"><h3>✨ Золотой мёд</h3><div class="big">${d.stats.golden_players || 0}</div><div class="muted">владельцев</div></div>
      </div>

      ${d.market ? `
        <div class="section-title"><h2>📈 HNY сейчас</h2></div>
        <div class="card">
          <div class="big">${fmt(d.market.price,4)} 🍯</div>
          <div class="${Number(d.market.change_24h_pct)>=0?'positive':'negative'}">
            ${Number(d.market.change_24h_pct)>=0?'+':''}${fmt(d.market.change_24h_pct,2)}% за 24ч
          </div>
          <div class="admin-actions" style="margin-top:12px">
            <button class="btn success" id="admin-market-up">📈 Поднять</button>
            <button class="btn danger" id="admin-market-down">📉 Опустить</button>
          </div>
          <button class="btn secondary" id="admin-market-reset" style="margin-top:8px">♻️ Перезапустить рынок</button>
        </div>` : ''}

      <div class="section-title"><h2>Быстрые действия</h2></div>
      <div class="admin-actions">
        <button class="btn" id="admin-giveaway">🚀 Раздача сейчас</button>
        <button class="btn secondary" id="admin-backup">💾 Скачать бэкап</button>
      </div>

      <div class="section-title"><h2>Настройки</h2></div>
      ${Object.entries(d.settings).map(([group, rows]) => `
        <details class="admin-group">
          <summary>${groupNames[group] || group}</summary>
          ${rows.map(adminSettingRow).join('')}
        </details>`).join('')}

      <div class="section-title"><h2>Журнал</h2></div>
      <div class="card">
        ${d.audit.length ? d.audit.map(a => `
          <div class="log-row">
            <b>${esc(a.created_at)}</b><br>${esc(a.action)}
            ${a.new_value != null ? `<br><span class="muted">${esc(a.old_value ?? '—')} → ${esc(a.new_value)}</span>` : ''}
          </div>`).join('') : '<span class="muted">Пока пусто</span>'}
      </div>

      <button class="btn danger" id="admin-logout" style="margin-top:14px">🚪 Выйти из админки</button>
    </div>`;

    document.getElementById('admin-close').onclick = () => { currentTab='profile'; render(); };
    document.getElementById('admin-logout').onclick = adminLogout;
    document.getElementById('admin-giveaway').onclick = adminGiveaway;
    document.getElementById('admin-backup').onclick = adminBackup;

    const up = document.getElementById('admin-market-up');
    const down = document.getElementById('admin-market-down');
    const reset = document.getElementById('admin-market-reset');
    if (up) up.onclick = () => adminMarketNudge('up');
    if (down) down.onclick = () => adminMarketNudge('down');
    if (reset) reset.onclick = adminMarketReset;

    document.querySelectorAll('.mini-save').forEach(btn =>
      btn.onclick = () => saveSetting(btn.dataset.key)
    );
  } catch(e) {
    if (!adminSession) {
      currentTab='profile';
      render();
      openAdmin();
    } else {
      toast(e.message, true);
    }
  }
}

function adminSettingRow(s) {
  let input;
  if (s.kind === 'bool') {
    input = `<select class="input admin-input" data-key="${esc(s.key)}">
      <option value="1" ${String(s.value)==='1'?'selected':''}>Включено</option>
      <option value="0" ${String(s.value)!=='1'?'selected':''}>Выключено</option>
    </select>`;
  } else if (s.kind === 'text') {
    input = `<textarea class="input admin-input" data-key="${esc(s.key)}">${esc(s.value)}</textarea>`;
  } else {
    input = `<input class="input admin-input" data-key="${esc(s.key)}" value="${esc(s.value)}"
      ${s.kind==='time'?'placeholder="HH:MM"':'inputmode="decimal"'}>`;
  }
  return `<div class="setting-row">
    <label>${esc(s.label)}</label>
    ${input}
    <button class="mini-save" data-key="${esc(s.key)}">✓</button>
  </div>`;
}

async function saveSetting(key) {
  const input = document.querySelector(`.admin-input[data-key="${CSS.escape(key)}"]`);
  if (!input) return;
  try {
    await api(`/api/admin/settings/${encodeURIComponent(key)}`, {
      method:'PUT',
      body:JSON.stringify({value:input.value})
    });
    notify('success');
    toast('Настройка сохранена');
    if (key === 'rules.text') state.rules = input.value;
  } catch(e) { notify('error'); toast(e.message, true); }
}

async function adminGiveaway() {
  try {
    const d = await api('/api/admin/honey/launch', {method:'POST'});
    notify('success');
    toast(`Раздача отправлена в ${d.sent} чатов`);
  } catch(e) { toast(e.message, true); }
}

async function adminMarketNudge(direction) {
  try {
    const d = await api(`/api/admin/exchange/nudge/${direction}`, {method:'POST'});
    notify('success');
    toast(`HNY: ${fmt(d.old,4)} → ${fmt(d.new,4)} 🍯`);
    await renderAdmin();
  } catch(e) { toast(e.message, true); }
}

async function adminMarketReset() {
  const ok = await confirmAction('Перезапустить график HNY со стартовой цены? Портфели пользователей сохранятся.');
  if (!ok) return;
  try {
    const d = await api('/api/admin/exchange/reset', {method:'POST'});
    notify('success');
    toast(`Рынок перезапущен: ${fmt(d.price,4)} 🍯`);
    await renderAdmin();
  } catch(e) { toast(e.message, true); }
}

async function adminBackup() {
  try {
    const res = await api('/api/admin/backup');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'murrlybot_backup.zip';
    a.click();
    URL.revokeObjectURL(url);
    toast('Бэкап подготовлен');
  } catch(e) { toast(e.message, true); }
}

async function adminLogout() {
  try { await api('/api/admin/logout', {method:'POST'}); } catch(_) {}
  adminSession = '';
  sessionStorage.removeItem('murrly_admin_session');
  currentTab = 'profile';
  render();
  toast('Админ-сессия завершена');
}

async function boot() {
  if (!tg || !initData) {
    appEl.innerHTML = `<div class="splash">
      <div class="bee">🐝</div>
      <h1>MurrlyBot</h1>
      <p>Открой Mini App через Telegram.</p>
    </div>`;
    return;
  }

  try {
    state = await api('/api/bootstrap');
    currentTab = 'home';
    render();
    await refreshShop();

    refreshTimer = setInterval(async () => {
      if (currentTab === 'exchange') {
        try { await refreshMarket(); } catch (_) {}
      }
    }, 30000);
  } catch(e) {
    appEl.innerHTML = `<div class="splash">
      <div class="bee">⚠️</div>
      <h1>Не удалось открыть</h1>
      <p>${esc(e.message)}</p>
    </div>`;
  }
}

boot();
