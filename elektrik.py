import asyncio
import requests
import urllib3
from datetime import datetime
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

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

EC_URL = "https://api.energy-charts.info/price"


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

    tarih = datetime.today().strftime("%Y-%m-%d")

    gorevler = [
        loop.run_in_executor(None, _da_fiyat, bzn, tarih)
        for bzn, _ in PIYASALAR
    ]
    sonuclar = await asyncio.gather(*gorevler)

    ayrac = "─" * 30
    satirlar = [
        f"{'Piyasa':<10} {'Base':>7} {'Peak':>7}",
        ayrac,
    ]

    for (_, etiket), fiyat in zip(PIYASALAR, sonuclar):
        if fiyat:
            base_str = f"{fiyat['base']:>7.1f}"
            peak_str = f"{fiyat['peak']:>7.1f}" if fiyat["peak"] else "    N/A"
        else:
            base_str = "    N/A"
            peak_str = "    N/A"
        satirlar.append(f"{etiket:<10} {base_str} {peak_str}")

    mesaj = "\n".join([
        f"*Gun Oncesi Elektrik — {tarih} (EUR/MWh)*",
        "```",
        *satirlar,
        "```",
    ])
    await update.message.reply_text(mesaj, parse_mode="Markdown")


def elektrik_handlerlari_ekle(app):
    app.add_handler(CommandHandler("dayahead", dayahead))
