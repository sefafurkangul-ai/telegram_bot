import os
import asyncio
import aiohttp
import requests
import urllib3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

CET    = ZoneInfo("Europe/Berlin")
EC_URL = "https://api.energy-charts.info/price"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# yfinance SSL bypass — sadece kurumsal proxy ortamında (.env'de LOCAL_PROXY=1)
if os.environ.get("LOCAL_PROXY"):
    os.environ.setdefault("CURL_CA_BUNDLE", "")
    os.environ.setdefault("REQUESTS_CA_BUNDLE", "")

import yfinance as yf

# yfinance için SSL doğrulamasız session
def _yf_session():
    try:
        from curl_cffi import requests as cr
        return cr.Session(verify=False, impersonate="chrome110")
    except ImportError:
        s = requests.Session()
        s.verify = False
        return s

_YF_SESSION = _yf_session()

AGSI_API_KEY = os.environ.get("AGSI_API_KEY")

DE_LAT, DE_LON = 51.17, 10.45   # Almanya merkezi
FR_LAT, FR_LON = 46.23,  2.21   # Fransa merkezi


# ── Veri çekme ────────────────────────────────────────────────────────────────

async def _gie_son_n_gun(host: str, n: int = 10) -> dict:
    """AGSI veya ALSI'dan EU için son N günlük ham veri."""
    bugun    = datetime.today()
    tarihler = [(bugun - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n + 1)]
    sema     = asyncio.Semaphore(10)

    async def tek(session, tarih):
        url = f"https://{host}/api?country=eu&date={tarih}"
        async with sema:
            try:
                async with session.get(url, headers={"x-key": AGSI_API_KEY},
                                       ssl=False,
                                       timeout=aiohttp.ClientTimeout(total=10)) as r:
                    rows = (await r.json()).get("data", [])
                    return tarih, rows[0] if rows else None
            except Exception:
                return tarih, None

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        sonuclar = await asyncio.gather(*[tek(session, t) for t in tarihler])
    return {t: d for t, d in sonuclar if d}


def _sicaklik_gunluk(lat: float, lon: float) -> dict:
    """Open-Meteo'dan son 8 günlük günlük ortalama sıcaklık {tarih: °C}."""
    url = (f"https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat}&longitude={lon}"
           f"&daily=temperature_2m_max,temperature_2m_min"
           f"&timezone=auto&past_days=7&forecast_days=1")
    try:
        d = requests.get(url, timeout=10, verify=False).json().get("daily", {})
        return {
            t: round((d["temperature_2m_min"][i] + d["temperature_2m_max"][i]) / 2, 1)
            for i, t in enumerate(d.get("time", []))
            if d["temperature_2m_min"][i] is not None
            and d["temperature_2m_max"][i] is not None
        }
    except Exception:
        return {}


# ── İstatistik hesaplama ──────────────────────────────────────────────────────

def _istatistik(veriler: dict, bugun_str: str):
    """Güncel değer, 7 günlük delta ve 7 günlük ortalama."""
    if not veriler:
        return None, None, None

    sirali = sorted(veriler.keys(), reverse=True)
    guncel = next((veriler[g] for g in sirali if g <= bugun_str), None)
    if guncel is None:
        return None, None, None

    hedef_str = (datetime.strptime(bugun_str, "%Y-%m-%d")
                 - timedelta(days=7)).strftime("%Y-%m-%d")
    onceki = next((veriler[g] for g in sorted(veriler.keys()) if g >= hedef_str), None)
    delta  = round(guncel - onceki, 1) if onceki is not None else None

    vals = [v for k, v in veriler.items() if hedef_str <= k <= bugun_str]
    avg  = round(sum(vals) / len(vals), 1) if vals else None

    return guncel, delta, avg


def _satir(isim: str, veriler: dict, bugun_str: str, ondalik: int = 0) -> str:
    guncel, delta, avg = _istatistik(veriler, bugun_str)
    if guncel is None:
        return f"{isim:<9} {'N/A':>5} {'N/A':>5} {'N/A':>5}"

    def f(v):
        return format(round(v, ondalik), f",.{ondalik}f") if v is not None else "N/A"

    isaret    = "+" if delta is not None and delta > 0 else ""
    delta_str = f"{isaret}{f(delta)}" if delta is not None else "N/A"
    return f"{isim:<9} {f(guncel):>5} {delta_str:>5} {f(avg):>5}"


# ── Handler ───────────────────────────────────────────────────────────────────

async def gaztoplu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Veri toplanıyor...")

    bugun = datetime.today().strftime("%Y-%m-%d")
    loop  = asyncio.get_running_loop()

    agsi_raw, alsi_raw, de_temp, fr_temp = await asyncio.gather(
        _gie_son_n_gun("agsi.gie.eu", 10),
        _gie_son_n_gun("alsi.gie.eu", 10),
        loop.run_in_executor(None, _sicaklik_gunluk, DE_LAT, DE_LON),
        loop.run_in_executor(None, _sicaklik_gunluk, FR_LAT, FR_LON),
    )

    # AGSI → Gas Stocks (TWh), Net Injection (GWh/d), Doluluk (%)
    stocks, net_inj, doluluk = {}, {}, {}
    for tarih, d in agsi_raw.items():
        try:
            stocks[tarih] = float(d.get("gasInStorage", 0) or 0)
        except Exception:
            pass
        try:
            inj   = float(d.get("injection",  0) or 0)
            wdraw = float(d.get("withdrawal", 0) or 0)
            net_inj[tarih] = round(inj - wdraw, 1)
        except Exception:
            pass
        try:
            depo     = float(d.get("gasInStorage",    0) or 0)
            kapasite = float(d.get("workingGasVolume", 1) or 1)
            doluluk[tarih] = round(depo / kapasite * 100, 1)
        except Exception:
            pass

    # ALSI → LNG Sendout (GWh/d)
    lng = {}
    for tarih, d in alsi_raw.items():
        for alan in ("sendOut", "dtrs", "lngInventory"):
            val = d.get(alan)
            if val is not None:
                try:
                    lng[tarih] = float(val)
                    break
                except Exception:
                    pass

    # Tablo
    ayrac = "─" * 27
    tablo = "\n".join([
        "```",
        f"{'Gösterge':<9} {'Şimdi':>5} {'D-7G':>5} {'Ort':>5}",
        ayrac,
        _satir("Stok TWh", stocks,  bugun, ondalik=0),
        _satir("Doluluk%", doluluk, bugun, ondalik=1),
        _satir("Inj GWh",  net_inj, bugun, ondalik=0),
        _satir("LNG GWh",  lng,     bugun, ondalik=0),
        ayrac,
        _satir("DE (C)",   de_temp, bugun, ondalik=1),
        _satir("FR (C)",   fr_temp, bugun, ondalik=1),
        "```",
    ])

    await update.message.reply_text(tablo, parse_mode="Markdown")


# ── Piyasa tablosu ───────────────────────────────────────────────────────────

_AYLAR = {1:'F',2:'G',3:'H',4:'J',5:'K',6:'M',7:'N',8:'Q',9:'U',10:'V',11:'X',12:'Z'}


def _brent_ticker(n: int = 2) -> str:
    """N ay sonrasının Brent futures ticker'ı (Yahoo NYMEX formatı)."""
    dt = datetime.today()
    m, y = dt.month + n, dt.year
    while m > 12:
        m -= 12
        y += 1
    return f"BZ{_AYLAR[m]}{str(y)[-2:]}.NYM"



def _fiyat_al(ticker_str: str):
    """Son fiyat, günlük değişim, % değişim ve veri tarihi döndür."""
    try:
        t    = yf.Ticker(ticker_str, session=_YF_SESSION)
        hist = t.history(period="5d")
        if not hist.empty:
            fiyat  = float(hist["Close"].iloc[-1])
            onceki = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
            degisim     = (fiyat - onceki) if onceki else None
            pct         = (degisim / onceki * 100) if (onceki and degisim is not None) else None
            # Kaç gündür aynı fiyat?
            esit_gun = sum(1 for c in hist["Close"] if round(c, 4) == round(fiyat, 4))
            stale_not = f"={esit_gun}g" if esit_gun >= 2 else None
            return fiyat, degisim, pct, stale_not
        # history gelmezse fast_info + info dict dene
        fi     = t.fast_info
        fiyat  = fi.last_price
        if not fiyat:
            return None, None, None, None
        onceki = fi.previous_close
        if onceki is None:
            info   = t.info
            onceki = info.get("regularMarketPreviousClose") or info.get("previousClose")
        degisim = (fiyat - onceki) if onceki else None
        pct     = (degisim / onceki * 100) if (onceki and degisim is not None) else None
        return float(fiyat), degisim, pct, None
    except Exception:
        return None, None, None, None



PIYASALAR = [
    ("Brent M+2",  lambda: _brent_ticker(2)),
    ("TTF M+1",    "TTF=F"),
    ("HenryHub M1","NG=F"),
    ("EUR/USD",    "EURUSD=X"),
]


async def piyasa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Veri alınıyor...")
    loop = asyncio.get_running_loop()

    def _topla():
        sonuclar = []
        for isim, ticker in PIYASALAR:
            tkr = ticker() if callable(ticker) else ticker
            sonuclar.append((isim, tkr, *_fiyat_al(tkr)))
        return sonuclar

    sonuclar = await loop.run_in_executor(None, _topla)

    bugun = datetime.today().strftime("%d.%m")
    satirlar = []
    for isim, tkr, f, d, p, vt in sonuclar:
        if f is not None:
            d_str = (f"{'+'if d >= 0 else ''}{d:.2f}" if d is not None else "N/A")
            p_str = (f"{'+'if p >= 0 else ''}{p:.1f}%"  if p is not None else "")
            stale = f" ({vt})" if vt and vt != bugun else ""
            satirlar.append(f"{isim:<12} {f:>9.2f}  {d_str:>8} {p_str:>7}{stale}")
        else:
            satirlar.append(f"{isim:<12} {'N/A':>9}  (ticker: {tkr})")

    tarih = datetime.today().strftime("%d.%m.%Y %H:%M")
    ayrac = "─" * 44
    mesaj = "\n".join([
        f"*Piyasa — {tarih}*",
        "```",
        f"{'Enstrüman':<12} {'Fiyat':>9}  {'Değ.':>8} {'%Değ.':>7}",
        ayrac,
        *satirlar,
        "```",
    ])
    await update.message.reply_text(mesaj, parse_mode="Markdown")


# ── BG/RO/GR saatlik fiyat ───────────────────────────────────────────────────

def _saatlik_fiyat(bzn: str, tarih: str) -> dict:
    """Energy Charts'tan saatlik ortalama fiyatlar {cet_saat: fiyat}.
    15-dakikalık aralıkları CET saatine göre gruplar ve ortalar."""
    try:
        r = requests.get(f"{EC_URL}?bzn={bzn}&start={tarih}&end={tarih}",
                         verify=False, timeout=10)
        d = r.json()
        prices = d.get("price", [])
        unix   = d.get("unix_seconds", [])
        if not prices or not unix:
            return {}
        buckets = defaultdict(list)
        for ts, p in zip(unix, prices):
            if p is not None:
                saat = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(CET).hour
                buckets[saat].append(p)
        return {h: round(sum(v) / len(v), 2) for h, v in buckets.items()}
    except Exception:
        return {}


async def eufiyatfark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Kullanım: /eufiyatfark BG RO [15.04.2026]
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Kullanım: /eufiyatfark <ülke1> <ülke2> [tarih]\n"
            "Örnek: /eufiyatfark BG RO\n"
            "Örnek: /eufiyatfark BG RO 15.04.2026"
        )
        return

    ulke1 = args[0].upper()
    ulke2 = args[1].upper()

    tarih_fixe = None
    if len(args) >= 3:
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                tarih_fixe = datetime.strptime(args[2], fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                pass
        if not tarih_fixe:
            await update.message.reply_text("Tarih formatı hatalı. Örnek: 15.04.2026 veya 2026-04-15")
            return

    await update.message.reply_text("Fiyatlar alınıyor...")
    loop = asyncio.get_running_loop()

    async def _cek(tarih):
        r1, r2 = await asyncio.gather(
            loop.run_in_executor(None, _saatlik_fiyat, ulke1, tarih),
            loop.run_in_executor(None, _saatlik_fiyat, ulke2, tarih),
        )
        return r1, r2

    if tarih_fixe:
        h1, h2 = await _cek(tarih_fixe)
        tarih = tarih_fixe
    else:
        simdi = datetime.now(CET)
        kesim = simdi.replace(hour=13, minute=30, second=0, microsecond=0)
        yarin = (simdi + timedelta(days=1)).strftime("%Y-%m-%d")
        bugun = simdi.strftime("%Y-%m-%d")
        if simdi >= kesim:
            h1, h2 = await _cek(yarin)
            tarih = yarin
            if not h1 and not h2:
                h1, h2 = await _cek(bugun)
                tarih = bugun
        else:
            h1, h2 = await _cek(bugun)
            tarih = bugun

    saatler = sorted(set(h1) | set(h2))
    if not saatler:
        await update.message.reply_text("Veri bulunamadı.")
        return

    def p(d, h):
        v = d.get(h)
        return f"{v:>6.1f}" if v is not None else "   N/A"

    def fark(h):
        v1, v2 = h1.get(h), h2.get(h)
        if v1 is None or v2 is None:
            return "   N/A"
        return f"{v1 - v2:>+7.1f}"

    def ort(d):
        vals = [v for v in d.values() if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def ort_fark():
        vals = [h1[h] - h2[h] for h in saatler if h in h1 and h in h2]
        return round(sum(vals) / len(vals), 1) if vals else None

    fark_baslik = f"{ulke1}-{ulke2}"
    ayrac = "─" * (24 + len(fark_baslik))

    o1, o2, of = ort(h1), ort(h2), ort_fark()
    satirlar = [
        f"{'Sa':>2}  {ulke1:>6} {ulke2:>6} {fark_baslik:>7}",
        ayrac,
        f"{'Ort':>2}  "
        f"{f'{o1:>6.1f}' if o1 is not None else '   N/A'}  "
        f"{f'{o2:>6.1f}' if o2 is not None else '   N/A'}  "
        f"{f'{of:>+7.1f}' if of is not None else '   N/A'}",
        ayrac,
    ]
    for h in saatler:
        satirlar.append(f"{h+1:02d}  {p(h1,h)} {p(h2,h)} {fark(h)}")

    mesaj = "\n".join([
        f"*{ulke1} / {ulke2} — {tarih}*",
        "```",
        *satirlar,
        "```",
    ])
    await update.message.reply_text(mesaj, parse_mode="Markdown")


def ilker_handlerlari_ekle(app):
    app.add_handler(CommandHandler("gaztoplu",    gaztoplu))
    app.add_handler(CommandHandler("piyasa",      piyasa))
    app.add_handler(CommandHandler("eufiyatfark", eufiyatfark))
