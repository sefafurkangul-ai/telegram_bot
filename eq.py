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


RL_ACTUAL_CURVE = {
    "DE": "DE Residual Load MWh/h 15min Actual",
    "FR": "FR Residual Load MWh/h 30min Actual",
    "BE": "BE Residual Load MWh/h 15min Actual",
    "GB": "GB Residual Load MWh/h 30min Actual",
    "NL": "NL Residual Load MWh/h 15min Actual",
}

RL_FORECAST_CURVE = {
    "DE": "DE Residual Load MWh/h 15min Forecast",
    "FR": "FR Residual Load MWh/h 15min Forecast",
    "BE": "BE Residual Load MWh/h 15min Forecast",
    "GB": "GB Residual Load MWh/h 15min Forecast",
    "NL": "NL Residual Load MWh/h 15min Forecast",
}


def _rl_veri_cek(kod):
    from energyquantified import EnergyQuantified
    eq = EnergyQuantified(api_key=EQ_API_KEY)

    simdi  = datetime.now(timezone.utc)
    bugun  = simdi.date()
    begin  = bugun - timedelta(days=10)
    end    = bugun + timedelta(days=15)

    actual_curve   = RL_ACTUAL_CURVE.get(kod, f"{kod} Residual Load MWh/h 15min Actual")
    forecast_curve = RL_FORECAST_CURVE.get(kod, f"{kod} Residual Load MWh/h 15min Forecast")

    actual = eq.timeseries.load(
        curve=actual_curve,
        begin=str(begin), end=str(end),
    ).to_pandas_dataframe().iloc[:, 0].resample("h").mean()

    ec = eq.instances.latest(
        curve=forecast_curve,
        tags="ec-ens", ensembles=True,
    ).to_pandas_dataframe()
    ec.columns = [c[2] if c[2] else "mean" for c in ec.columns]
    ec = ec.resample("h").mean()

    gfs = eq.instances.latest(
        curve=forecast_curve,
        tags="gfs-ens", ensembles=True,
    ).to_pandas_dataframe()
    gfs.columns = [c[2] if c[2] else "mean" for c in gfs.columns]
    gfs = gfs.resample("h").mean()

    return actual, ec, gfs, begin, end, simdi


def _rl_grafik_olustur(kod, actual, ec, gfs, begin, end, simdi):
    fig, axes = plt.subplots(1, 2, figsize=(16, 5), sharey=True)
    fig.patch.set_facecolor("#1a1a2e")

    xlim = (pd.Timestamp(begin, tz="UTC"), pd.Timestamp(end, tz="UTC"))
    now_line = pd.Timestamp(simdi)

    for ax, df, baslik, renk in [
        (axes[0], ec,  f"EC ensemble – Residual load – MWh/h – {kod}", "#00bfff"),
        (axes[1], gfs, f"GFS ensemble – Residual load – MWh/h – {kod}", "#9370db"),
    ]:
        ax.set_facecolor("#1a1a2e")
        ax.tick_params(colors="white")
        ax.xaxis.label.set_color("white")
        ax.yaxis.label.set_color("white")
        for spine in ax.spines.values():
            spine.set_edgecolor("#444")
        ax.grid(True, linestyle="--", alpha=0.25, color="gray")

        # Ensemble üyeleri (e00..eNN)
        uyeler = [c for c in df.columns if c.startswith("e")]
        ens_df = df[uyeler]

        p10 = ens_df.quantile(0.10, axis=1)
        p25 = ens_df.quantile(0.25, axis=1)
        p75 = ens_df.quantile(0.75, axis=1)
        p90 = ens_df.quantile(0.90, axis=1)
        median = ens_df.median(axis=1)

        ax.fill_between(p10.index, p10, p90, alpha=0.25, color=renk, linewidth=0)
        ax.fill_between(p25.index, p25, p75, alpha=0.40, color=renk, linewidth=0)
        ax.plot(median.index, median, color=renk, linewidth=1.5, label="Median")

        # Gerçekleşen
        ax.plot(actual.index, actual, color="#f0c040", linewidth=1.5, label="Actual")

        # Şimdiki zaman çizgisi
        ax.axvline(now_line, color="white", linewidth=0.8, linestyle="--", alpha=0.6)

        ax.set_xlim(xlim)
        ax.set_title(baslik, color="white", fontsize=9, pad=6)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
        ax.legend(fontsize=8, facecolor="#1a1a2e", labelcolor="white")

    axes[0].set_ylabel("MWh/h", color="white")
    fig.suptitle(
        f"Last refreshed: {simdi.strftime('%Y-%m-%d %H:%M')} UTC",
        color="white", fontsize=9, y=1.01,
    )
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf


async def eqrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    ulke = args[0].lower() if args else "de"
    kod  = ULKE_KODLARI.get(ulke)

    if not kod:
        await update.message.reply_text(
            f"Bilinmeyen ülke: {ulke}\n"
            f"Desteklenen: {', '.join(sorted(set(ULKE_KODLARI.values())))}"
        )
        return

    await update.message.reply_text(f"⏳ {kod} residual load grafik hazırlanıyor...")

    try:
        actual, ec, gfs, begin, end, simdi = await asyncio.to_thread(_rl_veri_cek, kod)
        buf = await asyncio.to_thread(_rl_grafik_olustur, kod, actual, ec, gfs, begin, end, simdi)
        await update.message.reply_photo(photo=buf)
    except Exception as e:
        await update.message.reply_text(f"Hata: {e}")


def eq_handlerlari_ekle(app):
    app.add_handler(CommandHandler("eqnukleer", eqnukleer))
    app.add_handler(CommandHandler("eqrl", eqrl))
