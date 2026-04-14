import os
import asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

try:
    from eptr2 import EPTR2 as _EPTR2
except ImportError:
    _EPTR2 = None

_EPIAS_USER = os.environ.get("EPIAS_USERNAME")
_EPIAS_PASS = os.environ.get("EPIAS_PASSWORD")
_EPIAS_SSL  = not bool(os.environ.get("LOCAL_PROXY"))


def _eptr():
    return _EPTR2(username=_EPIAS_USER, password=_EPIAS_PASS, ssl_verify=_EPIAS_SSL)


def _gun_ort(df, col):
    """Belirli kolun günlük ortalaması → {tarih: float}."""
    if df is None or df.empty or col not in df.columns:
        return {}
    df = df.copy()
    df["_d"] = df["date"].astype(str).str[:10]
    return df.groupby("_d")[col].mean().to_dict()


def _veri_cek(dm1, d0, d1, mtd):
    e = _eptr()

    # Rüzgar: gerçek üretim (D-1, D) + tahmin (D+1)
    try:
        wdf = e.call("wind-forecast", start_date=dm1, end_date=d1)
        wind_gen  = _gun_ort(wdf, "generation")
        wind_fore = _gun_ort(wdf, "forecast")
    except Exception:
        wind_gen = wind_fore = {}

    # Güneş gerçek üretim (D-1, D)
    try:
        rdf = e.call("ren-rt-gen", start_date=dm1, end_date=d0)
        solar_act = _gun_ort(rdf, "gunes")
    except Exception:
        solar_act = {}

    # Güneş D+1 tahmini (KGUP)
    try:
        kdf = e.call("kgup", start_date=d1, end_date=d1)
        solar_d1 = _gun_ort(kdf, "gunes")
    except Exception:
        solar_d1 = {}

    # Üretim dağılımı D-1 (yakıt bazında saatlik ortalama MW)
    try:
        gdf = e.call("rt-gen", start_date=dm1, end_date=dm1)
        uretim = (
            gdf[[c for c in gdf.columns if c not in ("date", "hour")]].mean().to_dict()
            if not gdf.empty else {}
        )
    except Exception:
        uretim = {}

    # PTF fiyatları (MTD → D+1)
    try:
        pdf = e.call("ptf", start_date=mtd, end_date=d1)
        ptf = _gun_ort(pdf, "price")
    except Exception:
        ptf = {}

    return wind_gen, wind_fore, solar_act, solar_d1, uretim, ptf


def _mw(d, k):
    v = d.get(k)
    if v is None:
        return "  N/A"
    try:
        return f"{int(round(v)):>5,}"
    except Exception:
        return "  N/A"


def _tr(d, k):
    v = d.get(k)
    if v is None:
        return "    N/A"
    try:
        return f"{v:>7,.0f}"
    except Exception:
        return "    N/A"


async def epias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _EPTR2 or not _EPIAS_USER or not _EPIAS_PASS:
        await update.message.reply_text("EPİAŞ kimlik bilgisi eksik.")
        return

    await update.message.reply_text("EPİAŞ verisi alınıyor...")
    loop = asyncio.get_running_loop()

    today = datetime.today()
    d0  = today.strftime("%Y-%m-%d")
    d1  = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    dm1 = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    mtd = today.strftime("%Y-%m-01")

    wind_gen, wind_fore, solar_act, solar_d1, uretim, ptf = await loop.run_in_executor(
        None, _veri_cek, dm1, d0, d1, mtd
    )

    tarih = today.strftime("%d.%m.%Y")

    # ── 1. Yenilenebilir (Rüzgar + Güneş) ───────────────────────────────────
    ren_blok = "\n".join([
        "```",
        f"{'':7} {'D-1':>5} {'D':>5} {'D+1':>5}",
        "─" * 25,
        f"{'Ruzgar':<7} {_mw(wind_gen,  dm1)} {_mw(wind_gen,  d0)} {_mw(wind_fore, d1)}",
        f"{'Gunes':<7} {_mw(solar_act, dm1)} {_mw(solar_act, d0)} {_mw(solar_d1,  d1)}",
        "```",
    ])

    # ── 2. Üretim Dağılımı (D-1) ─────────────────────────────────────────────
    uretim_sirali = [
        ("Dogalgaz",  "naturalGas"),
        ("Barajli",   "dammedHydro"),
        ("Akarsu",    "river"),
        ("Linyit",    "lignite"),
        ("Ith.Komur", "importCoal"),
        ("Ruzgar",    "wind"),
        ("Gunes",     "sun"),
        ("Jeotermal", "geothermal"),
        ("Biyokutle", "biomass"),
        ("LNG",       "lng"),
    ]
    u_satirlar = [f"{'Kaynak':<10} {'MW':>6}", "─" * 17]
    for etiket, col in uretim_sirali:
        v = uretim.get(col, 0) or 0
        if v > 1:
            u_satirlar.append(f"{etiket:<10} {int(round(v)):>6,}")
    uretim_blok = "\n".join(["```"] + u_satirlar + ["```"])

    # ── 3. PTF Fiyatları ──────────────────────────────────────────────────────
    mtd_vals = [v for k, v in ptf.items() if k < d0 and v is not None]
    mtd_ort  = f"{sum(mtd_vals)/len(mtd_vals):>7,.0f}" if mtd_vals else "    N/A"
    ptf_blok = "\n".join([
        "```",
        f"{'Gun':<8} {'TRY/MWh':>7}",
        "─" * 16,
        f"{'MTD Ort':<8} {mtd_ort}",
        f"{'D-1':<8} {_tr(ptf, dm1)}",
        f"{'D':<8} {_tr(ptf, d0)}",
        f"{'D+1':<8} {_tr(ptf, d1)}",
        "```",
    ])

    mesaj = "\n".join([
        f"*EPİAŞ — {tarih}*",
        "",
        f"*Yenilenebilir MW ort (D+1: tahmin)*",
        ren_blok,
        "",
        f"*Uretim Dagilimi — {dm1[5:]} (MW ort)*",
        uretim_blok,
        "",
        "*Spot Elektrik PTF*",
        ptf_blok,
    ])

    await update.message.reply_text(mesaj, parse_mode="Markdown")


def epias_handlerlari_ekle(app):
    app.add_handler(CommandHandler("epias", epias))
