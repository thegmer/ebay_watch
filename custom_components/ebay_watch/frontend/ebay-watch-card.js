const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const money = (v, cur) => (v == null ? "" : new Intl.NumberFormat(undefined, { style: "currency", currency: cur || "USD" }).format(v));
const shortDate = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "");
const timeLeft = (iso) => {
  if (!iso) return ["", ""];
  const ms = new Date(iso) - Date.now();
  if (ms <= 0) return ["Ended", "ended"];
  const m = Math.floor(ms / 60000), d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60);
  return [d ? `${d}d ${h}h` : h ? `${h}h ${m % 60}m` : `${m}m`, ms < 3600000 ? "urgent" : ms < 86400000 ? "soon" : ""];
};
const orderState = (o) => (o.status === "Cancelled" ? "cancelled" : o.delivered ? "delivered" : o.tracking?.length ? "transit" : "awaiting");
const STATES = { all: "All", transit: "In transit", awaiting: "Awaiting", delivered: "Delivered", cancelled: "Cancelled" };

const CSS = `
  ha-card { overflow: hidden; }
  .head { display: flex; align-items: center; padding: 12px 16px 0; }
  .title { flex: 1; font-size: 1.25em; font-weight: 500; }
  .tabs { display: flex; gap: 4px; padding: 8px 16px 0; border-bottom: 1px solid var(--divider-color); }
  .tabs button { background: none; border: none; border-bottom: 2px solid transparent; padding: 8px 12px; cursor: pointer;
    color: var(--secondary-text-color); font: inherit; font-weight: 500; }
  .tabs button.on { color: var(--primary-color); border-bottom-color: var(--primary-color); }
  .tools { display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 16px; align-items: center; }
  input { flex: 1; min-width: 140px; padding: 7px 10px; border-radius: 8px; border: 1px solid var(--divider-color);
    background: var(--secondary-background-color); color: var(--primary-text-color); font: inherit; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .chips button { border: 1px solid var(--divider-color); background: none; color: var(--primary-text-color);
    border-radius: 14px; padding: 3px 10px; cursor: pointer; font: inherit; font-size: .85em; }
  .chips button.on { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .list { max-height: var(--ebay-card-max-height, 560px); overflow-y: auto; padding: 0 8px 8px; }
  .row { display: flex; align-items: center; gap: 12px; padding: 8px; border-radius: 10px; transition: opacity .3s; }
  .row:hover { background: var(--secondary-background-color); }
  .row.removing { opacity: .35; pointer-events: none; }
  img, .img { width: 56px; height: 56px; border-radius: 8px; object-fit: cover; flex: none; background: var(--secondary-background-color); }
  .main { flex: 1; min-width: 0; }
  .main a { color: var(--primary-text-color); text-decoration: none; display: -webkit-box; -webkit-line-clamp: 2;
    -webkit-box-orient: vertical; overflow: hidden; line-height: 1.3; }
  .main a:hover { color: var(--primary-color); }
  .meta { color: var(--secondary-text-color); font-size: .85em; margin-top: 3px; }
  .meta b { color: var(--primary-text-color); }
  .chip { flex: none; font-size: .8em; padding: 2px 8px; border-radius: 10px; background: var(--secondary-background-color);
    color: var(--secondary-text-color); white-space: nowrap; }
  .chip.soon { color: var(--warning-color); } .chip.urgent { background: var(--error-color); color: #fff; }
  .chip.transit { color: var(--info-color, var(--primary-color)); } .chip.delivered { color: var(--success-color); }
  .chip.awaiting { color: var(--warning-color); } .chip.cancelled, .chip.ended { text-decoration: line-through; }
  button.icon { background: none; border: none; cursor: pointer; color: var(--secondary-text-color); padding: 6px;
    border-radius: 50%; display: inline-flex; flex: none; }
  button.icon:hover { color: var(--primary-color); background: var(--secondary-background-color); }
  button.icon.sm { padding: 2px; --mdc-icon-size: 16px; }
  button.icon.done { color: var(--success-color); }
  .trk { display: flex; align-items: center; gap: 4px; font-size: .85em; margin-top: 3px; }
  .trk a { color: var(--primary-color); font-family: var(--code-font-family, monospace); -webkit-line-clamp: 1; }
  .side { text-align: right; flex: none; display: flex; flex-direction: column; gap: 4px; align-items: flex-end; }
  .empty { padding: 24px; text-align: center; color: var(--secondary-text-color); }
  .muted { color: var(--secondary-text-color); }
`;

class EbayWatchCard extends HTMLElement {
  setConfig(config) {
    this._config = {
      title: "eBay",
      watchlist_entity: "sensor.ebay_watchlist",
      orders_entity: "sensor.ebay_packages_in_transit",
      confirm_remove: true,
      ...config,
    };
    this._tab ??= "watch";
    this._chip ??= "all";
    this._filter ??= "";
  }

  set hass(hass) {
    this._hass = hass;
    const w = hass.states[this._config.watchlist_entity], o = hass.states[this._config.orders_entity];
    if (w === this._w && o === this._o && this.shadowRoot) return;
    this._w = w;
    this._o = o;
    this._render();
  }

  connectedCallback() { this._timer = setInterval(() => this._tick(), 30000); }
  disconnectedCallback() { clearInterval(this._timer); }
  getCardSize() { return 8; }
  static getStubConfig() { return {}; }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `<style>${CSS}</style><ha-card>
      <div class="head"><div class="title"></div>
        <button class="icon" data-action="refresh" title="Refresh now"><ha-icon icon="mdi:refresh"></ha-icon></button></div>
      <div class="tabs"><button data-tab="watch"></button><button data-tab="orders"></button></div>
      <div class="tools"><input type="search" placeholder="Filter…"><div class="chips"></div></div>
      <div class="list"></div></ha-card>`;
    root.addEventListener("click", (e) => this._click(e));
    root.querySelector("input").addEventListener("input", (e) => {
      this._filter = e.target.value.toLowerCase();
      this._renderList();
    });
  }

  get _items() { return this._w?.attributes.items ?? []; }
  get _orders() { return this._o?.attributes.orders ?? []; }

  _render() {
    if (!this.shadowRoot) this._build();
    const r = this.shadowRoot;
    r.querySelector(".title").textContent = this._config.title;
    const [wt, ot] = r.querySelectorAll(".tabs button");
    wt.textContent = `Watchlist (${this._items.length})`;
    ot.textContent = `Purchases (${this._orders.length})`;
    wt.classList.toggle("on", this._tab === "watch");
    ot.classList.toggle("on", this._tab === "orders");
    const counts = this._orders.reduce((a, o) => ((a[orderState(o)] = (a[orderState(o)] || 0) + 1), a), {});
    r.querySelector(".chips").innerHTML = this._tab !== "orders" ? "" : Object.entries(STATES)
      .filter(([k]) => k === "all" || counts[k])
      .map(([k, v]) => `<button data-chip="${k}" class="${this._chip === k ? "on" : ""}">${v}${k === "all" ? "" : ` ${counts[k]}`}</button>`)
      .join("");
    this._renderList();
  }

  _renderList() {
    const list = this.shadowRoot.querySelector(".list");
    const f = this._filter;
    if (this._tab === "watch") {
      if (!this._w) return (list.innerHTML = `<div class="empty">Entity ${esc(this._config.watchlist_entity)} not found</div>`);
      const rows = this._items.filter((i) => !f || `${i.title} ${i.seller} ${i.item_id}`.toLowerCase().includes(f));
      list.innerHTML = rows.map((i) => this._watchRow(i)).join("") || `<div class="empty">Nothing here</div>`;
    } else {
      if (!this._o) return (list.innerHTML = `<div class="empty">Entity ${esc(this._config.orders_entity)} not found</div>`);
      const rows = this._orders.filter((o) => (this._chip === "all" || orderState(o) === this._chip) &&
        (!f || `${o.items.map((i) => i.title).join(" ")} ${o.seller} ${o.tracking.map((t) => t.number).join(" ")}`.toLowerCase().includes(f)));
      list.innerHTML = rows.map((o) => this._orderRow(o)).join("") || `<div class="empty">Nothing here</div>`;
    }
  }

  _watchRow(i) {
    const [left, cls] = timeLeft(i.end_time);
    const auction = i.listing_type === "Chinese" || /auction/i.test(i.listing_type || "");
    const ship = i.shipping > 0 ? ` + ${money(i.shipping, i.currency)} ship` : i.shipping === 0 ? " · free ship" : "";
    const bids = auction ? ` · ${i.bids} bid${i.bids === 1 ? "" : "s"}` : "";
    const variant = i.variation ? ` · ${esc(Object.values(i.variation).join(" / "))}` : "";
    return `<div class="row">
      ${i.image ? `<img src="${esc(i.image)}" loading="lazy" referrerpolicy="no-referrer">` : `<div class="img"></div>`}
      <div class="main"><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a>
        <div class="meta"><b>${money(i.price, i.currency)}</b>${ship}${bids}${variant}</div></div>
      <span class="chip ${cls}" data-end="${esc(i.end_time)}">${left}</span>
      <button class="icon" data-action="remove" data-id="${esc(i.item_id)}" data-title="${esc(i.title)}" title="Stop watching">
        <ha-icon icon="mdi:eye-off-outline"></ha-icon></button></div>`;
  }

  _orderRow(o) {
    const st = orderState(o);
    const first = o.items[0] || { title: `Order ${o.order_id}` };
    const more = o.items.length > 1 ? ` <span class="muted">+${o.items.length - 1} more</span>` : "";
    const when = st === "delivered" ? `Delivered ${shortDate(o.delivered)}`
      : st === "transit" && o.est_delivery ? `ETA ${shortDate(o.est_delivery)}` : `Ordered ${shortDate(o.created)}`;
    const trk = o.tracking.map((t) => `<div class="trk"><ha-icon icon="mdi:package-variant-closed" style="--mdc-icon-size:14px"></ha-icon>
      <a href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.carrier)} ${esc(t.number)}</a>
      <button class="icon sm" data-action="copy" data-num="${esc(t.number)}" title="Copy tracking number"><ha-icon icon="mdi:content-copy"></ha-icon></button></div>`).join("");
    return `<div class="row">
      <div class="main"><a href="https://www.ebay.com/itm/${esc(first.item_id)}" target="_blank" rel="noopener">${esc(first.title)}</a>${more}
        <div class="meta">${esc(o.seller || "")} · ${when}</div>${trk}</div>
      <div class="side"><span class="chip ${st}">${STATES[st]}</span><span class="meta"><b>${money(o.total, o.currency)}</b></span></div></div>`;
  }

  _tick() {
    this.shadowRoot?.querySelectorAll("[data-end]").forEach((el) => {
      const [txt, cls] = timeLeft(el.dataset.end);
      el.textContent = txt;
      el.className = `chip ${cls}`;
    });
  }

  async _click(e) {
    const el = e.target.closest("[data-action],[data-tab],[data-chip]");
    if (!el) return;
    if (el.dataset.tab) { this._tab = el.dataset.tab; return this._render(); }
    if (el.dataset.chip) { this._chip = el.dataset.chip; return this._render(); }
    const action = el.dataset.action;
    if (action === "refresh") {
      el.classList.add("done");
      await this._hass.callService("ebay_watch", "refresh", {}).finally(() => el.classList.remove("done"));
    } else if (action === "remove") {
      if (this._config.confirm_remove && !confirm(`Stop watching "${el.dataset.title}"?`)) return;
      const row = el.closest(".row");
      row.classList.add("removing");
      try {
        await this._hass.callService("ebay_watch", "remove_from_watchlist", { item_id: el.dataset.id });
      } catch (err) {
        row.classList.remove("removing");
        alert(`Remove failed: ${err.message || err}`);
      }
    } else if (action === "copy") {
      try { await navigator.clipboard.writeText(el.dataset.num); } catch { prompt("Tracking number", el.dataset.num); return; }
      el.classList.add("done");
      setTimeout(() => el.classList.remove("done"), 1200);
    }
  }
}

if (!customElements.get("ebay-watch-card")) {
  customElements.define("ebay-watch-card", EbayWatchCard);
  (window.customCards ||= []).push({ type: "ebay-watch-card", name: "eBay Watch", description: "eBay watchlist, unwatch, and purchase tracking" });
}
