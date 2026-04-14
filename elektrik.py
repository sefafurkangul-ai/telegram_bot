import os
import asyncio
import requests
import urllib3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

try:
    from eptr2 import EPTR2 as _EPTR2
except ImportError:
    _EPTR2 = None

CET = ZoneInfo("Europe/Berlin")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PIYASALAR = [
    ("DE-LU",    "DE-LU   "),
    ("FR",       "FR      "),
    ("AT",       "AT      "),
    ("BE",       "BE      "),
    ("NL",       "NL      "),
    ("HU",       "HU      "),
    ("IT-North", "IT-North"),
    ("GR",       "GR      "),
    ("BG",       "BG      "),
    ("RO",       "RO      "),
    ("ES",       "ES      "),
]

EC_URL    = "https://api.energy-charts.info/price"
_EPIAS_USER   = os.environ.get("EPIAS_USERNAME")
_EPIAS_PASS   = os.environ.get("EPIAS_PASSWORD")
_EPIAS_SSL    = not bool(os.environ.get("LOCAL_PROXY"))


def _epias_ptf(tarih: str):
    """EPİAŞ'tan gün öncesi piyasa takas fiyatı (TRY/MWh)."""
    if not _EPTR2 or not _EPIAS_USER or not _EPIAS_PASS:
        return None
    try:
        eptr = _EPTR2(username=_EPIAS_USER, password=_EPIAS_PASS, ssl_verify=_EPIAS_SSL)
        df   = eptr.call("ptf", start_date=tarih, end_date=tarih)
        if df is None or df.empty:
            return None

        prices = df["price"].dropna().tolist()
        if not prices:
            return None

        base = round(sum(prices) / len(prices), 1)

        # Peak: 08:00–20:00 TRT
        peak_df     = df[df["hour"].apply(lambda h: 8 <= int(h.split(":")[0]) < 20)]
        peak_prices = peak_df["price"].dropna().tolist()
        peak = round(sum(peak_prices) / len(peak_prices), 1) if peak_prices else None

        return {"base": base, "peak": peak}
    except Exception:
        return None


def _da_fiyat(bzn: str, tarih: str):
    """Energy Charts'tan bir piyasanın gün öncesi fiyat özeti."""
    try:
        r = requests.get(f"{EC_URL}?bzn={bzn}&start={tarih}&end={tarih}",
                         verify=False, timeout=10)
        d = r.json()
        prices = d.get("price", [])
        unix   = d.get("unix_seconds", [])
        if not prices or not unix:
            return None

        pairs = [(ts, p) for ts, p in zip(unix, prices) if p is not None]
        if not pairs:
            return None

        base = round(sum(p for _, p in pairs) / len(pairs), 1)

        # Peak: 07:00–19:00 UTC ≈ 08:00–20:00 CET
        peak_vals = [p for ts, p in pairs
                     if 7 <= (ts % 86400) // 3600 < 19]
        peak = round(sum(peak_vals) / len(peak_vals), 1) if peak_vals else None

        return {"base": base, "peak": peak}
    except Exception:
        return None


async def dayahead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fiyatlar aliniyor...")
    loop = asyncio.get_running_loop()

    simdi = datetime.now(CET)
    kesim = simdi.replace(hour=13, minute=30, second=0, microsecond=0)
    yarin = (simdi + timedelta(days=1)).strftime("%Y-%m-%d")
    bugun = simdi.strftime("%Y-%m-%d")

    async def _cek(tarih: str):
        gorevler = [
            loop.run_in_executor(None, _da_fiyat, bzn, tarih)
            for bzn, _ in PIYASALAR
        ]
        gorevler.append(loop.run_in_executor(None, _epias_ptf, tarih))
        return await asyncio.gather(*gorevler)

    if simdi >= kesim:
        sonuclar = await _cek(yarin)
        tarih = yarin
        # D+1 veri yoksa bugüne düş
        if not any(s for s in sonuclar[:-1]):
            sonuclar = await _cek(bugun)
            tarih = bugun
    else:
        sonuclar = await _cek(bugun)
        tarih = bugun

    tr_fiyat    = sonuclar[-1]
    eu_sonuclar = sonuclar[:-1]

    ayrac = "─" * 30
    satirlar = [
        f"{'Piyasa':<10} {'Base':>7} {'Peak':>7}",
        ayrac,
    ]

    for (_, etiket), fiyat in zip(PIYASALAR, eu_sonuclar):
        if fiyat:
            base_str = f"{fiyat['base']:>7.1f}"
            peak_str = f"{fiyat['peak']:>7.1f}" if fiyat["peak"] else "    N/A"
        else:
            base_str = "    N/A"
            peak_str = "    N/A"
        satirlar.append(f"{etiket:<10} {base_str} {peak_str}")

    satirlar.append(ayrac)
    if tr_fiyat:
        base_str = f"{tr_fiyat['base']:>7.1f}"
        peak_str = f"{tr_fiyat['peak']:>7.1f}" if tr_fiyat["peak"] else "    N/A"
    else:
        base_str = "    N/A"
        peak_str = "    N/A"
    satirlar.append(f"{'TR(TRY)':<10} {base_str} {peak_str}")

    mesaj = "\n".join([
        f"*Gun Oncesi Elektrik — {tarih}*",
        f"_(EUR/MWh, TR: TRY/MWh)_",
        "```",
        *satirlar,
        "```",
    ])
    await update.message.reply_text(mesaj, parse_mode="Markdown")


def elektrik_handlerlari_ekle(app):
    app.add_handler(CommandHandler("dayahead", dayahead))
