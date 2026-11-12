import './style.css'
import {
  createChart, CandlestickSeries, LineSeries, AreaSeries, createSeriesMarkers, CrosshairMode,
} from 'lightweight-charts'

const $ = (id) => document.getElementById(id)
const form = $('form')
const STORE_KEY = 'crypto-signals-form'

const idr = (v) => (v == null ? '—' : 'Rp ' + Math.round(v).toLocaleString('id-ID'))
const pct = (v) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`)
const price = (v) => (v == null ? '—' : v.toLocaleString('en-US', { maximumFractionDigits: v < 10 ? 6 : 2 }))
const date = (t) => new Date(t * 1000).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })
const sign = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : '')
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

// ---------------------------------------------------------------- charts
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

function chartOptions() {
  return {
    autoSize: true,
    layout: { background: { type: 'solid', color: css('--panel') }, textColor: css('--muted'), fontSize: 12 },
    grid: { vertLines: { color: css('--border') }, horzLines: { color: css('--border') } },
    rightPriceScale: { borderColor: css('--border') },
    timeScale: { borderColor: css('--border'), timeVisible: true },
    crosshair: { mode: CrosshairMode.Normal },
  }
}

const priceChart = createChart($('priceChart'), chartOptions())
const equityChart = createChart($('equityChart'), chartOptions())
const candles = priceChart.addSeries(CandlestickSeries, {
  upColor: css('--up'), downColor: css('--down'), wickUpColor: css('--up'), wickDownColor: css('--down'), borderVisible: false,
})
const emaSeries = Object.fromEntries(['ema21', 'ema50', 'ema200'].map((k) => [
  k, priceChart.addSeries(LineSeries, { color: css('--' + k), lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }),
]))
const markers = createSeriesMarkers(candles, [])
const equity = equityChart.addSeries(AreaSeries, {
  lineColor: css('--accent'), topColor: css('--accent') + '55', bottomColor: css('--accent') + '05', lineWidth: 2,
  priceFormat: { type: 'custom', formatter: (v) => idr(v) },
})

// keep both charts scrolled/zoomed together (same number of bars)
let syncing = false
const sync = (src, dst) => src.timeScale().subscribeVisibleLogicalRangeChange((r) => {
  if (syncing || !r) return
  syncing = true; dst.timeScale().setVisibleLogicalRange(r); syncing = false
})
sync(priceChart, equityChart); sync(equityChart, priceChart)

matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  ;[priceChart, equityChart].forEach((c) => c.applyOptions(chartOptions()))
})

// ---------------------------------------------------------------- form state
function formParams() {
  const f = new FormData(form)
  return {
    exchange: f.get('exchange'),
    symbol: f.get('symbol').trim().toUpperCase(),
    timeframe: f.get('timeframe'),
    strategy: f.get('strategy'),
    days: f.get('days'),
    stop_atr: f.get('stop_atr'),
    tp_atr: f.get('tp_atr'),
    capital_idr: f.get('capital_idr'),
    usd_idr: f.get('usd_idr'),
    fee: (parseFloat(f.get('fee_pct')) || 0) / 100,
    demo: f.get('demo') ? 'true' : 'false',
  }
}
const target = () => parseFloat(form.target_idr.value) || 0

function saveForm() {
  try {
    const data = Object.fromEntries([...form.elements].filter((e) => e.name).map((e) => [e.name, e.type === 'checkbox' ? e.checked : e.value]))
    localStorage.setItem(STORE_KEY, JSON.stringify(data))
  } catch { /* storage unavailable */ }
}
function restoreForm() {
  try {
    const data = JSON.parse(localStorage.getItem(STORE_KEY) || '{}')
    for (const [k, v] of Object.entries(data)) {
      const el = form.elements[k]
      if (!el) continue
      if (el.type === 'checkbox') el.checked = v
      else if (el.tagName !== 'SELECT' || [...el.options].some((o) => o.value === v)) el.value = v
    }
  } catch { /* ignore */ }
}

// ---------------------------------------------------------------- API
async function api(path, params) {
  const res = await fetch(`/api/${path}?` + new URLSearchParams(params))
  let body
  try { body = await res.json() } catch { throw new Error(`Server error (${res.status})`) }
  if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`)
  return body
}

function busy(on) {
  $('loading').hidden = !on
  $('btnBacktest').disabled = on
  $('btnCompare').disabled = on
}
function showError(msg) {
  $('error').hidden = !msg
  $('error').textContent = msg || ''
}

// ---------------------------------------------------------------- backtest
async function runBacktest() {
  const p = formParams()
  saveForm(); showError(''); busy(true)
  try {
    const r = await api('backtest', p)
    $('demoFlag').hidden = p.demo !== 'true'
    renderBacktest(r, p)
  } catch (e) {
    showError(e.message)
  } finally {
    busy(false)
  }
}

function renderBacktest(r, p) {
  $('chartTitle').textContent = `${p.symbol} · ${p.timeframe} · ${p.strategy}`
  candles.setData(r.candles)
  for (const k in emaSeries) emaSeries[k].setData(r.lines[k])
  equity.setData(r.equity_idr)

  const m = []
  for (const t of r.trades) {
    m.push({ time: t.entry_time, position: 'belowBar', color: css('--up'), shape: 'arrowUp', text: 'BUY' })
    m.push({ time: t.exit_time, position: 'aboveBar', color: css('--down'), shape: 'arrowDown', text: t.reason === 'stop' ? 'STOP' : t.reason === 'take_profit' ? 'TP' : 'SELL' })
  }
  m.sort((a, b) => a.time - b.time)
  markers.setMarkers(m)

  // show the last ~200 candles by default
  const n = r.candles.length
  priceChart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 200), to: n + 3 })

  renderSignal(r.signal)
  renderTiles(r.stats)
  renderTrades(r.trades)
  showTab('trades')
}

function renderSignal(s) {
  const box = $('signal')
  box.className = `signal panel ${s.action.toLowerCase()}`
  $('sigAction').textContent = s.action
  let html = `Last closed candle <b>${date(s.time)}</b> · close <b>${price(s.close)}</b> · RSI <b>${s.rsi?.toFixed(1)}</b>
    · trend <b>${s.ema50 > s.ema200 ? 'up (EMA50 &gt; EMA200)' : 'down (EMA50 &lt; EMA200)'}</b>`
  if (s.action === 'BUY') html += `<br>Suggested stop-loss <b>${price(s.stop_loss)}</b> · take-profit <b>${price(s.take_profit)}</b>`
  if (s.previous) html += `<br>Previous signal: <b>${s.previous.action}</b> at ${date(s.previous.time)}`
  $('sigDetail').innerHTML = html
}

function renderTiles(s) {
  const goal = target()
  const hit = s.avg_idr_per_day >= goal
  const tiles = [
    ['Avg profit / day', idr(s.avg_idr_per_day), goal ? `goal ${idr(goal)} · ${hit ? 'reached ✓' : `${Math.max(0, (s.avg_idr_per_day / goal) * 100).toFixed(0)}% of goal`}` : '', sign(s.avg_idr_per_day)],
    ['Total return', pct(s['return_%']), `buy & hold ${pct(s['buy_hold_%'])}`, sign(s['return_%'])],
    ['Beats buy & hold?', s['return_%'] > s['buy_hold_%'] ? 'Yes' : 'No', `by ${(s['return_%'] - s['buy_hold_%']).toFixed(1)} pts`, s['return_%'] > s['buy_hold_%'] ? 'pos' : 'neg'],
    ['Max drawdown', pct(s['max_drawdown_%']), 'worst fall from a peak', 'neg'],
    ['Trades', s.trades, `win rate ${s['win_rate_%'].toFixed(0)}%`, ''],
    ['Worst day', idr(s.worst_day_idr), `${s['days_with_profit_%'].toFixed(0)}% of days profitable`, sign(s.worst_day_idr)],
  ]
  $('tiles').innerHTML = tiles.map(([k, v, sub, cls]) =>
    `<div class="tile"><div class="k">${k}</div><div class="v ${cls}">${v}</div><div class="s">${sub}</div></div>`).join('')
}

function renderTrades(trades) {
  if (!trades.length) { $('tab-trades').innerHTML = '<p class="empty">This strategy made no trades in the period.</p>'; return }
  const rows = [...trades].reverse().map((t) => `<tr>
      <td>${date(t.entry_time)}</td><td>${date(t.exit_time)}</td>
      <td>${price(t.entry)}</td><td>${price(t.exit)}</td>
      <td class="${sign(t.ret)}">${pct(t.ret * 100)}</td>
      <td class="${sign(t.pnl_idr)}">${idr(t.pnl_idr)}</td>
      <td class="l"><span class="badge">${esc(t.reason.replace('_', ' '))}</span></td></tr>`).join('')
  $('tab-trades').innerHTML = `<div class="scroll"><table>
    <thead><tr><th>Bought</th><th>Sold</th><th>Entry</th><th>Exit</th><th>Return</th><th>Profit</th><th class="l">Exit reason</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`
}

// ---------------------------------------------------------------- compare
async function runCompare() {
  const p = formParams()
  p.timeframes = '1h,4h,1d'
  saveForm(); showError(''); busy(true)
  $('tab-compare').innerHTML = '<p class="empty">Testing every strategy on 1h, 4h and 1d… the first run downloads history and can take a minute.</p>'
  showTab('compare')
  try {
    const r = await api('compare', p)
    $('demoFlag').hidden = p.demo !== 'true'
    renderCompare(r.rows)
  } catch (e) {
    showError(e.message)
    $('tab-compare').innerHTML = '<p class="empty">Comparison failed.</p>'
  } finally {
    busy(false)
  }
}

function renderCompare(rows) {
  const goal = target()
  const body = rows.map((r) => {
    const lucky = r['return_%'] > 0 && r['test_return_%'] <= 0
    const beats = r['return_%'] > r['buy_hold_%']
    return `<tr class="clickable" data-tf="${esc(r.timeframe)}" data-strategy="${esc(r.strategy)}">
      <td>${esc(r.strategy)}</td><td class="l">${esc(r.timeframe)}</td>
      <td class="${sign(r.avg_idr_per_day)}">${idr(r.avg_idr_per_day)} ${goal && r.avg_idr_per_day >= goal ? '<span class="badge goal">goal</span>' : ''}</td>
      <td class="${sign(r['return_%'])}">${pct(r['return_%'])}</td>
      <td>${pct(r['buy_hold_%'])} ${beats ? '<span class="badge goal">beats</span>' : ''}</td>
      <td class="neg">${pct(r['max_drawdown_%'])}</td>
      <td>${r.trades}</td><td>${r['win_rate_%'].toFixed(0)}%</td>
      <td class="${sign(r['test_return_%'])}">${pct(r['test_return_%'])} ${lucky ? '<span class="badge">luck?</span>' : ''}</td>
      <td class="${sign(r.test_idr_per_day)}">${idr(r.test_idr_per_day)}</td></tr>`
  }).join('')
  $('tab-compare').innerHTML = `<div class="scroll"><table>
    <thead><tr><th>Strategy</th><th class="l">TF</th><th>Avg / day</th><th>Return</th><th>Buy &amp; hold</th><th>Max DD</th><th>Trades</th><th>Win</th><th>Recent 30% return</th><th>Recent / day</th></tr></thead>
    <tbody>${body}</tbody></table></div>
    <p class="hint" style="margin-top:10px">“Recent 30%” = only the newest part of history. Good overall but bad recently usually means it was luck. Click a row to open it.</p>`
  $('tab-compare').querySelectorAll('tr.clickable').forEach((tr) => tr.addEventListener('click', () => {
    form.strategy.value = tr.dataset.strategy
    form.timeframe.value = tr.dataset.tf
    updateDesc()
    runBacktest()
  }))
}

// ---------------------------------------------------------------- tabs & init
function showTab(name) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name))
  document.querySelectorAll('.tab-body').forEach((b) => (b.hidden = b.id !== `tab-${name}`))
}
document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => showTab(t.dataset.tab)))

let meta = { strategies: [] }
function updateDesc() {
  const s = meta.strategies.find((x) => x.id === form.strategy.value)
  $('stratDesc').textContent = s ? s.description : ''
}

form.addEventListener('submit', (e) => { e.preventDefault(); runBacktest() })
$('btnCompare').addEventListener('click', runCompare)
form.strategy.addEventListener('change', updateDesc)
form.exchange.addEventListener('change', () => {
  // Indodax trades in rupiah and charges more
  if (form.exchange.value === 'indodax' && form.symbol.value.endsWith('/USDT')) form.symbol.value = form.symbol.value.replace('/USDT', '/IDR')
})

async function init() {
  try {
    meta = await api('meta', {})
  } catch (e) {
    showError('Cannot reach the API: ' + e.message)
    return
  }
  const opts = (list, label = (x) => x) => list.map((x) => `<option value="${esc(x.id ?? x)}">${esc(label(x))}</option>`).join('')
  form.exchange.innerHTML = opts(meta.exchanges)
  form.timeframe.innerHTML = opts(meta.timeframes)
  form.strategy.innerHTML = opts(meta.strategies, (s) => s.id)
  form.timeframe.value = '4h'
  form.strategy.value = 'combo'
  restoreForm()
  updateDesc()
}
init()
