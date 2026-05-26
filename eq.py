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

# ── Residual Load curves ──────────────────────────────────────────────────────

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

RL_NORMAL_CURVE = {
    "DE": "DE Residual Load MWh/h 15min Normal",
    "FR": "FR Residual Load MWh/h 15min Normal",
    "BE": "BE Residual Load MWh/h 15min Normal",
    "GB": "GB Residual Load MWh/h 15min Normal",
    "NL": "NL Residual Load MWh/h 15min Normal",
}

# ── Wind Power curves ─────────────────────────────────────────────────────────

WIND_ACTUAL_CURVE = {
    "DE": "DE Wind Power Production MWh/h 15min Actual",
    "FR": "FR Wind Power Production MWh/h 30min Actual",
    "BE": "BE Wind Power Production MWh/h H Actual",
    "GB": "GB Wind Power Production MWh/h 30min Actual",
    "NL": "NL Wind Power Production MWh/h 15min Actual",
}

WIND_FORECAST_CURVE = {
    "DE": "DE Wind Power Production MWh/h 15min Forecast",
    "FR": "FR Wind Power Production MWh/h 15min Forecast",
    "BE": "BE Wind Power Production MWh/h 15min Forecast",
    "GB": "GB Wind Power Production MWh/h 15min Forecast",
    "NL": "NL Wind Power Production MWh/h 15min Forecast",
}

WIND_NORMAL_CURVE = {
    "DE": "DE Wind Power Production MWh/h 15min Normal",
    "FR": "FR Wind Power Production MWh/h 15min Normal",
    "BE": "BE Wind Power Production MWh/h 15min Normal",
    "GB": "GB Wind Power Production MWh/h 15min Normal",
    "NL": "NL Wind Power Production MWh/h 15min Normal",
}

# ── Solar Power curves ────────────────────────────────────────────────────────

SOLAR_ACTUAL_CURVE = {
    "DE": "DE Solar Photovoltaic Production MWh/h 15min Actual",
    "FR": "FR Solar Photovoltaic Production MWh/h 30min Actual",
    "BE": "BE Solar Photovoltaic Production MWh/h H Actual",
    "GB": "GB Solar Photovoltaic Production MWh/h 30min Actual",
    "NL": "NL Solar Photovoltaic Production MWh/h 15min Actual",
}

SOLAR_FORECAST_CURVE = {
    "DE": "DE Solar Photovoltaic Production MWh/h 15min Forecast",
    "FR": "FR Solar Photovoltaic Production MWh/h 15min Forecast",
    "BE": "BE Solar Photovoltaic Production MWh/h 15min Forecast",
    "GB": "GB Solar Photovoltaic Production MWh/h 15min Forecast",
    "NL": "NL Solar Photovoltaic Production MWh/h 15min Forecast",
}

SOLAR_NORMAL_CURVE = {
    "DE": "DE Solar Photovoltaic Production MWh/h 15min Normal",
    "FR": "FR Solar Photovoltaic Production MWh/h 15min Normal",
    "BE": "BE Solar Photovoltaic Production MWh/h 15min Normal",
    "GB": "GB Solar Photovoltaic Production MWh/h 15min Normal",
    "NL": "NL Solar Photovoltaic Production MWh/h 15min Normal",
}

# ── Temperature curves ───────────────────────────────────────────────────────

TEMP_ACTUAL_CURVE = {
    "DE": "DE Consumption Temperature °C H Actual",
    "FR": "FR Consumption Temperature °C H Actual",
    "BE": "BE Consumption Temperature °C H Actual",
    "GB": "GB Consumption Temperature °C H Actual",
    "NL": "NL Consumption Temperature °C H Actual",
}

TEMP_FORECAST_CURVE = {
    "DE": "DE Consumption Temperature °C 15min Forecast",
    "FR": "FR Consumption Temperature °C 15min Forecast",
    "BE": "BE Consumption Temperature °C 15min Forecast",
    "GB": "GB Consumption Temperature °C 15min Forecast",
    "NL": "NL Consumption Temperature °C 15min Forecast",
}

TEMP_NORMAL_CURVE = {
    "DE": "DE Consumption Temperature °C 15min Normal",
    "FR": "FR Consumption Temperature °C 15min Normal",
    "BE": "BE Consumption Temperature °C 15min Normal",
    "GB": "GB Consumption Temperature °C 15min Normal",
    "NL": "NL Consumption Temperature °C 15min Normal",
}

# ── Spot Price curves ─────────────────────────────────────────────────────────

FIYAT_ACTUAL_CURVE = {
    "DE": "DE Price Spot EUR/MWh EPEX 15min Actual",
    "FR": "FR Price Spot EUR/MWh EPEX 15min Actual",
    "BE": "BE Price Spot EUR/MWh EPEX 15min Actual",
    "GB": "GB Price Spot EUR/MWh EPEX H Actual",
    "NL": "NL Price Spot EUR/MWh EPEX 15min Actual",
}

FIYAT_ENSEMBLE_CURVE = {
    "DE": "DE Price Spot Ensemble EUR/MWh H Forecast",
    "FR": "FR Price Spot Ensemble EUR/MWh H Forecast",
    "BE": "BE Price Spot Ensemble EUR/MWh H Forecast",
    "GB": "GB Price Spot Ensemble EUR/MWh H Forecast",
    "NL": "NL Price Spot Ensemble EUR/MWh H Forecast",
}


# ── Nuclear REMIT ─────────────────────────────────────────────────────────────

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


# ── Generic data fetch & charts ───────────────────────────────────────────────

def _veri_cek(kod, actual_dict, forecast_dict, normal_dict=None):
    from energyquantified import EnergyQuantified
    from datetime import time as dtime
    eq = EnergyQuantified(api_key=EQ_API_KEY)

    simdi  = datetime.now(timezone.utc)
    bugun  = simdi.date()
    begin  = bugun - timedelta(days=10)
    end    = bugun + timedelta(days=15)

    actual_curve   = actual_dict[kod]
    forecast_curve = forecast_dict[kod]

    actual = eq.timeseries.load(
        curve=actual_curve,
        begin=str(begin), end=str(end),
    ).to_pandas_dataframe().iloc[:, 0].resample("h").mean()

    normal = None
    if normal_dict and kod in normal_dict:
        try:
            normal = eq.timeseries.load(
                curve=normal_dict[kod],
                begin=str(begin), end=str(end),
            ).to_pandas_dataframe().iloc[:, 0].resample("h").mean()
        except Exception:
            pass

    ec = eq.instances.latest(
        curve=forecast_curve, tags="ec-ens", ensembles=True,
        issued_time_of_day=dtime(0, 0),
    ).to_pandas_dataframe()
    ec.columns = [c[2] if c[2] else "mean" for c in ec.columns]
    ec = ec.resample("h").mean()

    gfs = eq.instances.latest(
        curve=forecast_curve, tags="gfs-ens", ensembles=True,
        issued_time_of_day=dtime(0, 0),
    ).to_pandas_dataframe()
    gfs.columns = [c[2] if c[2] else "mean" for c in gfs.columns]
    gfs = gfs.resample("h").mean()

    return actual, normal, ec, gfs, begin, end, simdi


def _ax_stil(ax):
    ax.set_facecolor("#1a1a2e")
    ax.tick_params(colors="white")
    ax.xaxis.label.set_color("white")
    ax.yaxis.label.set_color("white")
    for spine in ax.spines.values():
        spine.set_edgecolor("#444")
    ax.grid(True, linestyle="--", alpha=0.25, color="gray")


def _ensemble_plot(ax, df, renk, etiket):
    uyeler = [c for c in df.columns if c.startswith("e")]
    ens_df = df[uyeler]
    p10    = ens_df.quantile(0.10, axis=1)
    p25    = ens_df.quantile(0.25, axis=1)
    p75    = ens_df.quantile(0.75, axis=1)
    p90    = ens_df.quantile(0.90, axis=1)
    median = ens_df.median(axis=1)
    ax.fill_between(p10.index, p10, p90, alpha=0.20, color=renk, linewidth=0)
    ax.fill_between(p25.index, p25, p75, alpha=0.35, color=renk, linewidth=0)
    ax.plot(median.index, median, color=renk, linewidth=1.5, label=etiket)


def _grafik_saatlik(kod, actual, ec, gfs, begin, end, simdi, baslik, ybirim="MWh/h"):
    fig, ax = plt.subplots(figsize=(14, 5))
    fig.patch.set_facecolor("#1a1a2e")
    _ax_stil(ax)

    xlim     = (pd.Timestamp(begin, tz="UTC"), pd.Timestamp(end, tz="UTC"))
    now_line = pd.Timestamp(simdi)

    _ensemble_plot(ax, ec,  "#00bfff", "EC ensemble")
    _ensemble_plot(ax, gfs, "#c084fc", "GFS ensemble")
    ax.plot(actual.index, actual, color="#f0c040", linewidth=1.5, label="Actual", zorder=5)
    ax.axvline(now_line, color="white", linewidth=0.8, linestyle="--", alpha=0.6)

    ax.set_xlim(xlim)
    ax.set_ylabel(ybirim, color="white")
    ax.set_title(f"{baslik} – {ybirim} – {kod}  |  EC & GFS ensemble",
                 color="white", fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
    ax.legend(fontsize=8, facecolor="#1a1a2e", labelcolor="white")
    fig.suptitle(f"Last refreshed: {simdi.strftime('%Y-%m-%d %H:%M')} UTC",
                 color="white", fontsize=8, y=1.01)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf


def _grafik_gunluk(kod, actual, normal, ec, gfs, begin, end, simdi, baslik, ybirim="MWh/h"):
    actual_d = actual.resample("D").mean()
    ec_d     = ec.resample("D").mean()
    gfs_d    = gfs.resample("D").mean()

    fig, ax = plt.subplots(figsize=(14, 5))
    fig.patch.set_facecolor("#1a1a2e")
    _ax_stil(ax)

    xlim     = (pd.Timestamp(begin, tz="UTC"), pd.Timestamp(end, tz="UTC"))
    now_line = pd.Timestamp(simdi)

    saatlik_sayim = actual.resample("D").count()
    tam_gunler    = saatlik_sayim[saatlik_sayim >= 20].index
    gecmis        = actual_d[actual_d.index.isin(tam_gunler)]

    ec_med  = ec_d[[c for c in ec_d.columns if c.startswith("e")]].median(axis=1)
    gfs_med = gfs_d[[c for c in gfs_d.columns if c.startswith("e")]].median(axis=1)

    bugun_ts = pd.Timestamp(simdi.date(), tz=gecmis.index.tz)
    bugun_ec = ec_med[ec_med.index.normalize() == bugun_ts]
    if not bugun_ec.empty:
        ax.bar([bugun_ts], [bugun_ec.mean()], width=0.8,
               color="#2a4a6a", alpha=0.8, edgecolor="#00bfff",
               linewidth=1.2, label="Today (EC forecast)")

    ax.bar(gecmis.index, gecmis.values, width=0.8, color="#4a4a6a", alpha=0.8, label="Actual (daily avg)")
    ax.plot(ec_med.index,  ec_med.values,  color="#00bfff", linewidth=1.8, label="EC median")
    ax.plot(gfs_med.index, gfs_med.values, color="#c084fc", linewidth=1.8, label="GFS median")

    if normal is not None:
        normal_d = normal.resample("D").mean()
        ax.plot(normal_d.index, normal_d.values, color="#a0a0a0",
                linewidth=1.2, linestyle="--", label="Normal")

    ax.axvline(now_line, color="white", linewidth=0.8, linestyle="--", alpha=0.6)

    ax.set_xlim(xlim)
    ax.set_ylabel(ybirim, color="white")
    ax.set_title(f"{baslik} – Daily – {ybirim} – {kod}",
                 color="white", fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
    ax.legend(fontsize=8, facecolor="#1a1a2e", labelcolor="white")
    fig.suptitle(f"Last refreshed: {simdi.strftime('%Y-%m-%d %H:%M')} UTC",
                 color="white", fontsize=8, y=1.01)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf


async def _komut(update, context, saatlik, actual_dict, forecast_dict, normal_dict, baslik, ybirim="MWh/h"):
    args = context.args
    ulke = args[0].lower() if args else "de"
    kod  = ULKE_KODLARI.get(ulke)

    if not kod:
        await update.message.reply_text(
            f"Bilinmeyen ulke: {ulke}\n"
            f"Desteklenen: {', '.join(sorted(set(ULKE_KODLARI.values())))}"
        )
        return

    if kod not in actual_dict:
        await update.message.reply_text(
            f"{kod} bu komut için henüz desteklenmiyor.\n"
            f"Desteklenen: {', '.join(sorted(actual_dict.keys()))}"
        )
        return

    await update.message.reply_text("Hazırlanıyor...")

    try:
        actual, normal, ec, gfs, begin, end, simdi = await asyncio.to_thread(
            _veri_cek, kod, actual_dict, forecast_dict, normal_dict
        )
        if saatlik:
            buf = await asyncio.to_thread(
                _grafik_saatlik, kod, actual, ec, gfs, begin, end, simdi, baslik, ybirim
            )
        else:
            buf = await asyncio.to_thread(
                _grafik_gunluk, kod, actual, normal, ec, gfs, begin, end, simdi, baslik, ybirim
            )
        await update.message.reply_photo(photo=buf)
    except Exception as e:
        await update.message.reply_text(f"Hata: {e}")


# ── Spot Price data fetch & charts ───────────────────────────────────────────

def _fiyat_veri_cek(kod):
    from energyquantified import EnergyQuantified
    eq = EnergyQuantified(api_key=EQ_API_KEY)

    simdi  = datetime.now(timezone.utc)
    bugun  = simdi.date()
    begin  = bugun - timedelta(days=10)
    end    = bugun + timedelta(days=15)

    actual = eq.timeseries.load(
        curve=FIYAT_ACTUAL_CURVE[kod],
        begin=str(begin), end=str(end),
    ).to_pandas_dataframe().iloc[:, 0].resample("h").mean()

    ens = eq.instances.latest(
        curve=FIYAT_ENSEMBLE_CURVE[kod], ensembles=True,
    ).to_pandas_dataframe()
    ens.columns = [c[2] if c[2] else "mean" for c in ens.columns]
    ens = ens.resample("h").mean()

    return actual, ens, begin, end, simdi


def _fiyat_grafik_saatlik(kod, actual, ens, begin, end, simdi):
    fig, ax = plt.subplots(figsize=(14, 5))
    fig.patch.set_facecolor("#1a1a2e")
    _ax_stil(ax)

    xlim     = (pd.Timestamp(begin, tz="UTC"), pd.Timestamp(end, tz="UTC"))
    now_line = pd.Timestamp(simdi)

    _ensemble_plot(ax, ens, "#ff9f40", "Price ensemble")
    ax.plot(actual.index, actual, color="#f0c040", linewidth=1.5, label="Actual", zorder=5)
    ax.axvline(now_line, color="white", linewidth=0.8, linestyle="--", alpha=0.6)

    ax.set_xlim(xlim)
    ax.set_ylabel("EUR/MWh", color="white")
    ax.set_title(f"Spot Price – EUR/MWh – {kod}  |  Price ensemble",
                 color="white", fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
    ax.legend(fontsize=8, facecolor="#1a1a2e", labelcolor="white")
    fig.suptitle(f"Last refreshed: {simdi.strftime('%Y-%m-%d %H:%M')} UTC",
                 color="white", fontsize=8, y=1.01)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf


def _fiyat_grafik_gunluk(kod, actual, ens, begin, end, simdi):
    actual_d = actual.resample("D").mean()
    ens_d    = ens.resample("D").mean()

    fig, ax = plt.subplots(figsize=(14, 5))
    fig.patch.set_facecolor("#1a1a2e")
    _ax_stil(ax)

    xlim     = (pd.Timestamp(begin, tz="UTC"), pd.Timestamp(end, tz="UTC"))
    now_line = pd.Timestamp(simdi)

    saatlik_sayim = actual.resample("D").count()
    tam_gunler    = saatlik_sayim[saatlik_sayim >= 20].index
    gecmis        = actual_d[actual_d.index.isin(tam_gunler)]

    ens_med = ens_d[[c for c in ens_d.columns if c.startswith("e")]].median(axis=1)

    bugun_ts = pd.Timestamp(simdi.date(), tz=gecmis.index.tz)
    bugun_ens = ens_med[ens_med.index.normalize() == bugun_ts]
    if not bugun_ens.empty:
        ax.bar([bugun_ts], [bugun_ens.mean()], width=0.8,
               color="#3a2a1a", alpha=0.8, edgecolor="#ff9f40",
               linewidth=1.2, label="Today (forecast)")

    ax.bar(gecmis.index, gecmis.values, width=0.8, color="#4a4a6a", alpha=0.8, label="Actual (daily avg)")
    ax.plot(ens_med.index, ens_med.values, color="#ff9f40", linewidth=1.8, label="Ensemble median")

    ax.axvline(now_line, color="white", linewidth=0.8, linestyle="--", alpha=0.6)
    ax.axhline(0, color="#555", linewidth=0.6, linestyle="-")

    ax.set_xlim(xlim)
    ax.set_ylabel("EUR/MWh", color="white")
    ax.set_title(f"Spot Price – Daily avg – EUR/MWh – {kod}",
                 color="white", fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
    ax.legend(fontsize=8, facecolor="#1a1a2e", labelcolor="white")
    fig.suptitle(f"Last refreshed: {simdi.strftime('%Y-%m-%d %H:%M')} UTC",
                 color="white", fontsize=8, y=1.01)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf


async def _fiyat_komut(update, context, saatlik):
    args = context.args
    ulke = args[0].lower() if args else "de"
    kod  = ULKE_KODLARI.get(ulke)

    if not kod:
        await update.message.reply_text(
            f"Bilinmeyen ulke: {ulke}\n"
            f"Desteklenen: {', '.join(sorted(set(ULKE_KODLARI.values())))}"
        )
        return

    if kod not in FIYAT_ACTUAL_CURVE:
        await update.message.reply_text(
            f"{kod} bu komut için henüz desteklenmiyor.\n"
            f"Desteklenen: {', '.join(sorted(FIYAT_ACTUAL_CURVE.keys()))}"
        )
        return

    await update.message.reply_text("Hazırlanıyor...")

    try:
        actual, ens, begin, end, simdi = await asyncio.to_thread(_fiyat_veri_cek, kod)
        if saatlik:
            buf = await asyncio.to_thread(_fiyat_grafik_saatlik, kod, actual, ens, begin, end, simdi)
        else:
            buf = await asyncio.to_thread(_fiyat_grafik_gunluk,  kod, actual, ens, begin, end, simdi)
        await update.message.reply_photo(photo=buf)
    except Exception as e:
        await update.message.reply_text(f"Hata: {e}")


# ── Residual Load commands ────────────────────────────────────────────────────

async def eqrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _komut(update, context, saatlik=False,
                 actual_dict=RL_ACTUAL_CURVE, forecast_dict=RL_FORECAST_CURVE,
                 normal_dict=RL_NORMAL_CURVE, baslik="Residual load")


async def eqrlh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _komut(update, context, saatlik=True,
                 actual_dict=RL_ACTUAL_CURVE, forecast_dict=RL_FORECAST_CURVE,
                 normal_dict=RL_NORMAL_CURVE, baslik="Residual load")


# ── Wind Power commands ───────────────────────────────────────────────────────

async def eqwind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _komut(update, context, saatlik=False,
                 actual_dict=WIND_ACTUAL_CURVE, forecast_dict=WIND_FORECAST_CURVE,
                 normal_dict=WIND_NORMAL_CURVE, baslik="Wind Power")


async def eqwindh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _komut(update, context, saatlik=True,
                 actual_dict=WIND_ACTUAL_CURVE, forecast_dict=WIND_FORECAST_CURVE,
                 normal_dict=WIND_NORMAL_CURVE, baslik="Wind Power")


# ── Solar Power commands ──────────────────────────────────────────────────────

async def eqsolar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _komut(update, context, saatlik=False,
                 actual_dict=SOLAR_ACTUAL_CURVE, forecast_dict=SOLAR_FORECAST_CURVE,
                 normal_dict=SOLAR_NORMAL_CURVE, baslik="Solar Power")


async def eqsolarh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _komut(update, context, saatlik=True,
                 actual_dict=SOLAR_ACTUAL_CURVE, forecast_dict=SOLAR_FORECAST_CURVE,
                 normal_dict=SOLAR_NORMAL_CURVE, baslik="Solar Power")


# ── Temperature commands ─────────────────────────────────────────────────────

async def eqtemp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _komut(update, context, saatlik=False,
                 actual_dict=TEMP_ACTUAL_CURVE, forecast_dict=TEMP_FORECAST_CURVE,
                 normal_dict=TEMP_NORMAL_CURVE, baslik="Temperature", ybirim="°C")


async def eqtemph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _komut(update, context, saatlik=True,
                 actual_dict=TEMP_ACTUAL_CURVE, forecast_dict=TEMP_FORECAST_CURVE,
                 normal_dict=TEMP_NORMAL_CURVE, baslik="Temperature", ybirim="°C")


# ── Spot Price commands ───────────────────────────────────────────────────────

async def eqfiyat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _fiyat_komut(update, context, saatlik=False)


async def eqfiyath(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _fiyat_komut(update, context, saatlik=True)


# ── Handler registration ──────────────────────────────────────────────────────

def eq_handlerlari_ekle(app):
    app.add_handler(CommandHandler("eqnukleer", eqnukleer))
    app.add_handler(CommandHandler("eqrl",      eqrl))
    app.add_handler(CommandHandler("eqrlh",     eqrlh))
    app.add_handler(CommandHandler("eqwind",    eqwind))
    app.add_handler(CommandHandler("eqwindh",   eqwindh))
    app.add_handler(CommandHandler("eqsolar",   eqsolar))
    app.add_handler(CommandHandler("eqsolarh",  eqsolarh))
    app.add_handler(CommandHandler("eqfiyat",   eqfiyat))
    app.add_handler(CommandHandler("eqfiyath",  eqfiyath))
    app.add_handler(CommandHandler("eqtemp",    eqtemp))
    app.add_handler(CommandHandler("eqtemph",   eqtemph))
