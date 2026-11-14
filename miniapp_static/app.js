
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
let adminSession = sessionStorage.getItem('murrly_admin_session') || '';

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

function nav() {
  return `
    <div class="nav">
      ${navBtn('home','🏠','Главная')}
      ${navBtn('farm','🐝','Ферма')}
      ${navBtn('shop','🎁','Магазин')}
      ${navBtn('profile','👤','Профиль')}
    </div>`;
}
function navBtn(key, ico, title) {
  return `<button data-tab="${key}" class="${currentTab===key?'active':''}">
    <span class="ico">${ico}</span>${title}
  </button>`;
}

function userName() {
  const u = state.user;
  return [u.first_name, u.last_name].filter(Boolean).join(' ') || u.username || 'Пользователь';
}

function avatar() {
  if (state.user.photo_url) return `<img class="avatar" src="${esc(state.user.photo_url)}" alt="">`;
  return `<div class="avatar">🐝</div>`;
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
    <div class="balance"><span class="num">${state.wallet.balance}</span><span class="unit">🍯 мёдика</span></div>
  </div>`;
}

function render() {
  if (!state) return;
  let content = '';
  if (currentTab === 'home') content = homeView();
  if (currentTab === 'farm') content = farmView();
  if (currentTab === 'shop') content = shopView();
  if (currentTab === 'profile') content = profileView();

  appEl.innerHTML = `<div class="shell">${header()}${content}</div>${nav()}`;
  document.querySelectorAll('[data-tab]').forEach(btn => btn.onclick = () => {
    haptic();
    currentTab = btn.dataset.tab;
    render();
    if (currentTab === 'shop') refreshShop();
  });
  bindActions();
}

function homeView() {
  const f = state.farm;
  const vip = state.vip;
  const marriage = state.marriage;
  return `
    <div class="grid2">
      <div class="card" data-go="farm">
        <span class="badge">🐝 Ферма L${f.level}</span>
        <div class="big" style="margin-top:10px">${Math.floor(f.stored)} / ${f.capacity} 🍯</div>
        <div class="muted">${f.production} 🍯 в сутки</div>
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
        <h3>💍 Брак</h3>
        <div class="big">${marriage ? `${marriage.health}%` : '—'}</div>
        <div class="muted">${marriage ? esc(marriage.partner_name) : 'Пока не заключён'}</div>
      </div>
    </div>

    <div class="section-title"><h2>Информация</h2></div>
    <button class="btn secondary" data-open="rules">📜 Правила</button>
  `;
}

function farmView() {
  const f = state.farm;
  const pct = Math.max(0, Math.min(100, Math.floor((Number(f.stored)/Number(f.capacity))*100)));
  const full = Number(f.stored) >= Number(f.capacity);
  return `
    <div class="section-title"><h2>🐝 Медовая ферма</h2><span class="badge">L${f.level}</span></div>
    <div class="card">
      <div class="farm-visual">${f.level >= 5 ? '🏰' : f.level >= 3 ? '🏡' : '🍯'}</div>
      <div class="progress"><div style="width:${pct}%"></div></div>
      <div style="display:flex;justify-content:space-between;font-size:13px">
        <span>${Math.floor(f.stored)} 🍯</span><span class="muted">${f.capacity} 🍯</span>
      </div>
      <div class="stats-row">
        <div class="stat"><b>${f.production}</b><span>🍯 / сутки</span></div>
        <div class="stat"><b>${f.capacity}</b><span>вместимость</span></div>
        <div class="stat"><b>${pct}%</b><span>заполнено</span></div>
      </div>
      ${f.vip_active ? `<p class="badge" style="margin-top:12px">👑 VIP усиливает ферму</p>` : ''}
      ${full ? `<p class="muted">Соты заполнены — производство остановлено до сбора.</p>` : ''}
      <button class="btn" id="farm-collect" style="margin-top:14px">🍯 Собрать мёдик</button>
      ${f.upgrade_cost == null
        ? `<button class="btn secondary" disabled>👑 Максимальный уровень</button>`
        : `<button class="btn secondary" id="farm-upgrade">⬆️ Улучшить за ${f.upgrade_cost} 🍯</button>`}
    </div>
  `;
}

function shopView() {
  const catalog = state.shop?.catalog || {};
  const inv = state.shop?.inventory?.items || [];
  const owned = Object.fromEntries(inv.map(i => [i.key, i.count]));
  return `
    <div class="section-title"><h2>🎁 Магазин</h2><span class="badge">${state.wallet.balance} 🍯</span></div>
    <div class="shop-grid">
      ${Object.entries(catalog).map(([key,p]) => `
        <div class="product">
          <div class="emoji">${p.emoji}</div>
          <h3>${esc(p.name)}</h3>
          <div class="price">${p.price} 🍯</div>
          <div class="owned">У тебя: ${owned[key] || 0}</div>
          <button class="btn buy-gift" data-gift="${key}">Купить</button>
        </div>`).join('')}
    </div>
  `;
}

function profileView() {
  const p = state.profile || {};
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
    </div>

    <div class="section-title"><h2>Дополнительно</h2></div>
    <button class="btn secondary" data-open="vip">👑 VIP</button>
    <button class="btn secondary" data-open="rules">📜 Правила</button>
    ${state.admin_eligible ? `<button class="btn" id="open-admin">🛠 Панель управления</button>` : ''}
  `;
}
function profileItem(label, value) {
  return `<div class="profile-item"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;
}

async function refreshAll() {
  state = await api('/api/bootstrap');
  render();
}
async function refreshShop() {
  try {
    const shop = await api('/api/shop');
    state.shop = shop;
    state.wallet = shop.wallet;
    render();
  } catch (e) { toast(e.message, true); }
}

function bindActions() {
  document.querySelectorAll('[data-go]').forEach(el => el.onclick = () => {
    currentTab = el.dataset.go;
    render();
  });
  document.querySelectorAll('[data-open="rules"]').forEach(el => el.onclick = showRules);
  document.querySelectorAll('[data-open="vip"]').forEach(el => el.onclick = showVip);

  const collect = document.getElementById('farm-collect');
  if (collect) collect.onclick = farmCollect;
  const upgrade = document.getElementById('farm-upgrade');
  if (upgrade) upgrade.onclick = farmUpgrade;

  document.querySelectorAll('.buy-gift').forEach(btn => btn.onclick = () => buyGift(btn.dataset.gift));

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
        </div>
        <button class="btn vip-buy" data-plan="7" style="margin-top:12px">👑 ${data.plans['7'].days} дней · ${data.plans['7'].price} 🍯</button>
        <button class="btn secondary vip-buy" data-plan="30">💎 ${data.plans['30'].days} дней · ${data.plans['30'].price} 🍯</button>
      </div>`);
    document.querySelectorAll('.vip-buy').forEach(b => b.onclick = () => buyVip(Number(b.dataset.plan)));
  } catch(e) { toast(e.message, true); }
}

async function buyVip(plan) {
  try {
    haptic('medium');
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
    if (d.result.status === 'empty') toast('В сотах пока меньше 1 🍯');
    else { notify('success'); toast(`+${d.result.amount} 🍯 в копилку`); }
    await refreshAll();
    currentTab = 'farm'; render();
  } catch(e) { toast(e.message, true); }
}
async function farmUpgrade() {
  try {
    const d = await api('/api/farm/upgrade', {method:'POST'});
    if (d.result.status === 'insufficient') throw new Error(`Не хватает ${d.result.need} 🍯`);
    if (d.result.status === 'max') throw new Error('Ферма уже максимального уровня');
    notify('success'); toast(`Ферма улучшена до L${d.result.farm.level}`);
    await refreshAll();
    currentTab = 'farm'; render();
  } catch(e) { notify('error'); toast(e.message, true); }
}
async function buyGift(key) {
  try {
    const d = await api(`/api/shop/buy/${encodeURIComponent(key)}`, {method:'POST'});
    if (d.result.status === 'insufficient') throw new Error(`Не хватает ${d.result.need} 🍯`);
    if (d.result.status !== 'ok') throw new Error('Не удалось купить подарок');
    notify('success'); toast(`${d.result.gift.emoji} Куплено`);
    state.shop.inventory = d.inventory;
    state.shop.wallet = d.wallet;
    state.wallet = d.wallet;
    render();
  } catch(e) { notify('error'); toast(e.message, true); }
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
  farm:'🐝 Ферма',
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
        <div><div class="admin-title">🛠 Админ-панель</div><div class="sub">Доступна только твоему Telegram ID</div></div>
        <button class="icon-btn" id="admin-close">✕</button>
      </div>

      <div class="grid2">
        <div class="card"><h3>👥 Пользователи</h3><div class="big">${d.stats.users}</div></div>
        <div class="card"><h3>🍯 В экономике</h3><div class="big">${d.stats.honey_total}</div></div>
        <div class="card"><h3>🐝 Ферм</h3><div class="big">${d.stats.farms}</div></div>
        <div class="card"><h3>👑 Активных VIP</h3><div class="big">${d.stats.active_vips}</div></div>
      </div>

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
        ${d.audit.length ? d.audit.map(a => `<div class="log-row"><b>${esc(a.created_at)}</b><br>${esc(a.action)}${a.new_value != null ? `<br><span class="muted">${esc(a.old_value ?? '—')} → ${esc(a.new_value)}</span>`:''}</div>`).join('') : '<span class="muted">Пока пусто</span>'}
      </div>
      <button class="btn danger" id="admin-logout" style="margin-top:14px">🚪 Выйти из админки</button>
    </div>`;

    document.getElementById('admin-close').onclick = () => { currentTab='profile'; render(); };
    document.getElementById('admin-logout').onclick = adminLogout;
    document.getElementById('admin-giveaway').onclick = adminGiveaway;
    document.getElementById('admin-backup').onclick = adminBackup;

    document.querySelectorAll('.mini-save').forEach(btn => btn.onclick = () => saveSetting(btn.dataset.key));
  } catch(e) {
    if (!adminSession) {
      currentTab='profile'; render(); openAdmin();
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
    input = `<input class="input admin-input" data-key="${esc(s.key)}" value="${esc(s.value)}" ${s.kind==='time'?'placeholder="HH:MM"':'inputmode="decimal"'}>`;
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
    notify('success'); toast('Настройка сохранена');
    if (key === 'rules.text') state.rules = input.value;
  } catch(e) { notify('error'); toast(e.message, true); }
}

async function adminGiveaway() {
  try {
    const d = await api('/api/admin/honey/launch', {method:'POST'});
    notify('success'); toast(`Раздача отправлена в ${d.sent} чатов`);
  } catch(e) { toast(e.message, true); }
}

async function adminBackup() {
  try {
    // fetch нужен, чтобы сохранить защищённость endpoint.
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
  adminSession='';
  sessionStorage.removeItem('murrly_admin_session');
  currentTab='profile';
  render();
  toast('Админ-сессия завершена');
}

async function boot() {
  if (!tg || !initData) {
    appEl.innerHTML = `<div class="splash"><div class="bee">🐝</div><h1>MurrlyBot</h1><p>Открой Mini App через Telegram.</p></div>`;
    return;
  }
  try {
    state = await api('/api/bootstrap');
    currentTab='home';
    render();
    refreshShop();
  } catch(e) {
    appEl.innerHTML = `<div class="splash"><div class="bee">⚠️</div><h1>Не удалось открыть</h1><p>${esc(e.message)}</p></div>`;
  }
}

boot();
