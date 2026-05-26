import os
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

try:
    from eptr2 import EPTR2 as _EPTR2
except ImportError:
    _EPTR2 = None

CET = ZoneInfo("Europe/Berlin")

_EQ_API_KEY   = os.environ.get("EQ_API_KEY")
_EPIAS_USER   = os.environ.get("EPIAS_USERNAME")
_EPIAS_PASS   = os.environ.get("EPIAS_PASSWORD")
_EPIAS_SSL    = not bool(os.environ.get("LOCAL_PROXY"))

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

DAYAHEAD_CURVE = {
    "DE-LU":    "DE Price Spot EUR/MWh EPEX 15min Actual",
    "FR":       "FR Price Spot EUR/MWh EPEX 15min Actual",
    "AT":       "AT Price Spot EUR/MWh EPEX 15min Actual",
    "BE":       "BE Price Spot EUR/MWh EPEX 15min Actual",
    "NL":       "NL Price Spot EUR/MWh EPEX 15min Actual",
    "HU":       "HU Price Spot EUR/MWh HUPX 15min Actual",
    "IT-North": "IT Price Spot EUR/MWh GME 15min Actual",
    "GR":       "GR Price Spot EUR/MWh HEnEx 15min Actual",
    "BG":       "BG Price Spot EUR/MWh IBEX 15min Actual",
    "RO":       "RO Price Spot EUR/MWh OPCOM 15min Actual",
    "ES":       "ES Price Spot EUR/MWh OMIE 15min Actual",
}


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
    """EQ'dan bir piyasanın gün öncesi fiyat özeti."""
    curve = DAYAHEAD_CURVE.get(bzn)
    if not curve:
        return None
    try:
        from energyquantified import EnergyQuantified
        eq  = EnergyQuantified(api_key=_EQ_API_KEY)
        end = (datetime.strptime(tarih, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        df  = eq.timeseries.load(curve=curve, begin=tarih, end=end).to_pandas_dataframe()
        if df.empty:
            return None
        series = df.iloc[:, 0].resample("h").mean().dropna()
        if series.empty:
            return None

        base = round(float(series.mean()), 1)

        # Peak: 07:00–19:00 UTC ≈ 08:00–20:00 CET
        peak_vals = series[series.index.hour.isin(range(7, 19))]
        peak = round(float(peak_vals.mean()), 1) if not peak_vals.empty else None

        return {"base": base, "peak": peak}
    except Exception:
        return None


async def dayahead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fiyatlar aliniyor...")
    loop = asyncio.get_running_loop()

    async def _cek(tarih: str):
        gorevler = [
            loop.run_in_executor(None, _da_fiyat, bzn, tarih)
            for bzn, _ in PIYASALAR
        ]
        gorevler.append(loop.run_in_executor(None, _epias_ptf, tarih))
        return await asyncio.gather(*gorevler)

    # ── Tarih argümanı var mı? ────────────────────────────────────────────────
    if context.args:
        arg = context.args[0].strip()
        # DD.MM.YYYY veya YYYY-MM-DD formatlarını kabul et
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                tarih = datetime.strptime(arg, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        else:
            await update.message.reply_text(
                "Geçersiz tarih formatı. Örnek: /dayahead 15.01.2025 veya /dayahead 2025-01-15"
            )
            return
        sonuclar = await _cek(tarih)
    else:
        # ── Mevcut mantık: 13:30 CET kesim saatine göre bugün/yarın ──────────
        simdi = datetime.now(CET)
        kesim = simdi.replace(hour=13, minute=30, second=0, microsecond=0)
        yarin = (simdi + timedelta(days=1)).strftime("%Y-%m-%d")
        bugun = simdi.strftime("%Y-%m-%d")

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
