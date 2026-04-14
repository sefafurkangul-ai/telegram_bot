import os
import asyncio
import aiohttp
import requests
import urllib3
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

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
    """Son fiyat, günlük değişim (kapanış bazlı) ve % değişim döndür."""
    try:
        t    = yf.Ticker(ticker_str, session=_YF_SESSION)
        hist = t.history(period="5d")
        if not hist.empty:
            fiyat  = float(hist["Close"].iloc[-1])
            onceki = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
            degisim = (fiyat - onceki) if onceki else None
            pct     = (degisim / onceki * 100) if (onceki and degisim is not None) else None
            return fiyat, degisim, pct
        # history gelmezse fast_info + info dict dene
        fi     = t.fast_info
        fiyat  = fi.last_price
        if not fiyat:
            return None, None, None
        onceki = fi.previous_close
        if onceki is None:
            info   = t.info
            onceki = info.get("regularMarketPreviousClose") or info.get("previousClose")
        degisim = (fiyat - onceki) if onceki else None
        pct     = (degisim / onceki * 100) if (onceki and degisim is not None) else None
        return float(fiyat), degisim, pct
    except Exception:
        return None, None, None



PIYASALAR = [
    ("Brent M+2", lambda: _brent_ticker(2)),
    ("TTF M+1",   "TTF=F"),
    ("API2 Kömür", "MTF=F"),
    ("EUR/USD",   "EURUSD=X"),
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

    satirlar = []
    for isim, tkr, f, d, p in sonuclar:
        if f is not None:
            d_str = (f"{'+'if d >= 0 else ''}{d:.2f}" if d is not None else "N/A")
            p_str = (f"{'+'if p >= 0 else ''}{p:.1f}%"  if p is not None else "")
            satirlar.append(f"{isim:<12} {f:>9.2f}  {d_str:>8} {p_str:>7}")
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


def ilker_handlerlari_ekle(app):
    app.add_handler(CommandHandler("gaztoplu", gaztoplu))
    app.add_handler(CommandHandler("piyasa",   piyasa))
