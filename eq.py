import os
import io
import asyncio
from datetime import datetime, timedelta, timezone
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

EQ_API_KEY = os.environ.get("EQ_API_KEY")

ULKE_KODLARI = {
    "fr": "FR", "fransa": "FR",
    "de": "DE", "almanya": "DE",
    "be": "BE", "belcika": "BE",
    "gb": "GB", "uk": "GB", "ingiltere": "GB",
    "fi": "FI", "finlandiya": "FI",
    "se": "SE", "isvec": "SE",
    "es": "ES", "ispanya": "ES",
    "ch": "CH", "isvicre": "CH",
    "nl": "NL", "hollanda": "NL",
    "cz": "CZ", "cekya": "CZ",
    "sk": "SK", "slovakya": "SK",
    "hu": "HU", "macaristan": "HU",
    "ro": "RO", "romanya": "RO",
    "si": "SI", "slovenya": "SI",
    "bg": "BG", "bulgaristan": "BG",
}

VERSIYONLAR = {
    "M-1": timedelta(days=30),
    "W-1": timedelta(days=7),
    "D-1": timedelta(days=1),
    "D":   None,
}

RENKLER = {"M-1": "red", "W-1": "blue", "D-1": "orange", "D": "green"}


def _period_to_xy(data):
    xs, ys = [], []
    for d in data:
        xs.append(pd.Timestamp(d.begin))
        ys.append(d.value)
    if data:
        xs.append(pd.Timestamp(data[-1].end))
        ys.append(data[-1].value)
    return xs, ys


def _nukleer_cek(kod):
    from energyquantified import EnergyQuantified
    eq = EnergyQuantified(api_key=EQ_API_KEY)

    simdi  = datetime.now(timezone.utc)
    bugun  = simdi.date()
    begin  = bugun - timedelta(days=14)
    end    = bugun + timedelta(days=90)
    curve  = f"{kod} Nuclear Capacity Available MW REMIT"

    sonuclar = {}
    for etiket, delta in VERSIYONLAR.items():
        kwargs = dict(curve=curve, begin=str(begin), end=str(end))
        if delta:
            kwargs["issued_at_latest"] = simdi - delta
        inst = eq.period_instances.latest(**kwargs)
        sonuclar[etiket] = inst

    return sonuclar, begin, end, simdi


def _grafik_olustur(kod, sonuclar, begin, end, simdi):
    fig, ax = plt.subplots(figsize=(14, 5))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.grid(True, linestyle="--", alpha=0.4, color="gray")

    versiyon_str = []
    for etiket, inst in sonuclar.items():
        if not inst or not inst.data:
            continue
        xs, ys = _period_to_xy(inst.data)
        ax.step(xs, ys, where="post", label=etiket,
                color=RENKLER[etiket], linewidth=1.5)
        issued = inst.instance.issued
        versiyon_str.append(issued.strftime("%Y-%m-%d %H:%M"))

    ax.set_xlabel("Date")
    ax.set_ylabel("Capacity (MW)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=2))
    plt.xticks(rotation=45, ha="right")
    ax.legend(loc="upper left")
    ax.set_xlim(pd.Timestamp(begin), pd.Timestamp(end))

    baslik  = f"Last refreshed: {simdi.strftime('%Y-%m-%d %H:%M:%S')}"
    altyazi = f"Nuclear REMIT versions: {' | '.join(versiyon_str)}"
    ax.set_title(f"{baslik}\n{altyazi}", fontsize=9)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf


async def eqnukleer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    ulke = args[0].lower() if args else "fr"
    kod  = ULKE_KODLARI.get(ulke)

    if not kod:
        await update.message.reply_text(
            f"Bilinmeyen ülke: {ulke}\n"
            f"Desteklenen: {', '.join(sorted(set(ULKE_KODLARI.values())))}"
        )
        return

    await update.message.reply_text(f"⏳ {kod} nükleer REMIT grafik hazırlanıyor...")

    try:
        sonuclar, begin, end, simdi = await asyncio.to_thread(_nukleer_cek, kod)
        buf = await asyncio.to_thread(_grafik_olustur, kod, sonuclar, begin, end, simdi)
        await update.message.reply_photo(photo=buf)
    except Exception as e:
        await update.message.reply_text(f"Hata: {e}")


def eq_handlerlari_ekle(app):
    app.add_handler(CommandHandler("eqnukleer", eqnukleer))
