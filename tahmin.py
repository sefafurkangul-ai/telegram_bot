import asyncio
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from grafik_utils import grafik_olustur, grafik_kaydet

# ── Şehir → koordinat ────────────────────────────────────────────────────────
def sehir_koordinat(sehir: str):
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={sehir}&count=1&language=tr"
    r   = requests.get(url, timeout=10, verify=False)
    res = r.json().get("results", [])
    if not res:
        return None, None, None
    return res[0]["latitude"], res[0]["longitude"], res[0]["name"]

# ── Ensemble verisi çek ───────────────────────────────────────────────────────
def ensemble_cek(lat, lon, model, degisken):
    """
    model: ecmwf_ifs025 veya gfs_seamless
    Tüm ensemble üyelerini çeker, min/maks/medyan döndürür
    """
    url = (
        f"https://ensemble-api.open-meteo.com/v1/ensemble"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly={degisken}"
        f"&models={model}"
        f"&forecast_days=10"
        f"&timezone=auto"
    )
    r    = requests.get(url, timeout=15, verify=False)
    data = r.json()

    if "hourly" not in data:
        return None

    hourly   = data["hourly"]
    tarihler = pd.to_datetime(hourly["time"])

    uyeler = [k for k in hourly.keys() if k.startswith(degisken) and k != degisken]

    if not uyeler:
        if degisken in hourly:
            df = pd.DataFrame({"tarih": tarihler, "medyan": hourly[degisken]})
            df["min"] = df["medyan"]
            df["max"] = df["medyan"]
            df["p25"] = df["medyan"]
            df["p75"] = df["medyan"]
            return df.dropna()
        return None

    uye_df = pd.DataFrame({u: hourly[u] for u in uyeler}, index=tarihler)
    df = pd.DataFrame({
        "tarih" : tarihler,
        "medyan": uye_df.median(axis=1).values,
        "min"   : uye_df.min(axis=1).values,
        "max"   : uye_df.max(axis=1).values,
        "p25"   : uye_df.quantile(0.25, axis=1).values,
        "p75"   : uye_df.quantile(0.75, axis=1).values,
    })
    return df.dropna()

# ── /tahmin komutu ────────────────────────────────────────────────────────────
async def tahmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Kullanım: /tahmin [şehir]\nÖrnek: /tahmin Istanbul"
        )
        return

    sehir = " ".join(context.args)
    await update.message.reply_text(f"📡 {sehir} için ensemble tahmin alınıyor...")

    lat, lon, sehir_adi = sehir_koordinat(sehir)
    if not lat:
        await update.message.reply_text(f"'{sehir}' bulunamadı.")
        return

    loop = asyncio.get_running_loop()

    # 4 ensemble verisini paralel çek (sıralı ~60s → paralel ~15s)
    try:
        (df_ecmwf_t, df_gfs_t,
         df_ecmwf_w, df_gfs_w) = await asyncio.wait_for(
            asyncio.gather(
                loop.run_in_executor(None, ensemble_cek, lat, lon, "ecmwf_ifs025", "temperature_2m"),
                loop.run_in_executor(None, ensemble_cek, lat, lon, "gfs_seamless",  "temperature_2m"),
                loop.run_in_executor(None, ensemble_cek, lat, lon, "ecmwf_ifs025", "wind_speed_10m"),
                loop.run_in_executor(None, ensemble_cek, lat, lon, "gfs_seamless",  "wind_speed_10m"),
            ),
            timeout=45
        )
    except asyncio.TimeoutError:
        await update.message.reply_text("Veri alınamadı (zaman aşımı).")
        return

    sicaklik = {"ECMWF ENS": (df_ecmwf_t, "#58a6ff"), "GFS ENS": (df_gfs_t, "#f78166")}
    ruzgar   = {"ECMWF ENS": (df_ecmwf_w, "#58a6ff"), "GFS ENS": (df_gfs_w, "#f78166")}

    # ── Sıcaklık grafiği ──────────────────────────────────────────────────────
    fig1, ax1 = grafik_olustur(figsize=(13, 5))
    dfs_sicaklik = {}

    for isim, (df, renk) in sicaklik.items():
        if df is None:
            continue
        dfs_sicaklik[isim] = df
        ax1.fill_between(df["tarih"], df["min"], df["max"], color=renk, alpha=0.10)
        ax1.fill_between(df["tarih"], df["p25"], df["p75"], color=renk, alpha=0.25,
                         label=f"{isim} (%25–75)")
        ax1.plot(df["tarih"], df["medyan"], color=renk, linewidth=2,
                 label=f"{isim} Medyan")

    ax1.axhline(y=0, color="#555", linestyle="--", linewidth=0.8, alpha=0.6)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax1.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    plt.xticks(rotation=45)
    ax1.set_title(f"{sehir_adi} — Sicaklik Tahmini (10 Gun ENS)",
                  color="white", fontsize=13, pad=15)
    ax1.set_ylabel("Sicaklik (C)", color="#8b949e")
    ax1.legend(facecolor="#21262d", edgecolor="#30363d", labelcolor="white", fontsize=9)
    plt.tight_layout()
    buf1 = grafik_kaydet(fig1)

    # ── Günlük sıcaklık tablosu ───────────────────────────────────────────────
    tablo_metni = None
    if dfs_sicaklik:
        gunler = sorted({d.date() for df in dfs_sicaklik.values()
                         for d in df["tarih"].dt.to_pydatetime()})
        satirlar = [f"{'Tarih':<9}{'ECMWF':^11}{'GFS':^11}",
                    f"{'':9}{'Min':>4} {'Max':>4}  {'Min':>4} {'Max':>4}",
                    "─" * 32]
        for gun in gunler:
            satir = f"{gun.strftime('%d/%m'):<9}"
            for isim in ["ECMWF ENS", "GFS ENS"]:
                if isim in dfs_sicaklik:
                    g = dfs_sicaklik[isim][dfs_sicaklik[isim]["tarih"].dt.date == gun]
                    satir += (f"{g['min'].min():>4.0f} {g['max'].max():>4.0f}  "
                              if not g.empty else f"{'—':>4} {'—':>4}  ")
            satirlar.append(satir)
        tablo_metni = "```\n" + "\n".join(satirlar) + "\n```"

    # ── Rüzgar grafiği ────────────────────────────────────────────────────────
    fig2, ax2 = grafik_olustur(figsize=(13, 5))

    for isim, (df, renk) in ruzgar.items():
        if df is None:
            continue
        ax2.fill_between(df["tarih"], df["min"], df["max"], color=renk, alpha=0.10)
        ax2.fill_between(df["tarih"], df["p25"], df["p75"], color=renk, alpha=0.25,
                         label=f"{isim} (%25–75)")
        ax2.plot(df["tarih"], df["medyan"], color=renk, linewidth=2,
                 label=f"{isim} Medyan")

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax2.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    plt.xticks(rotation=45)
    ax2.set_title(f"{sehir_adi} — Ruzgar Hizi Tahmini (10 Gun ENS)",
                  color="white", fontsize=13, pad=15)
    ax2.set_ylabel("Ruzgar (km/h)", color="#8b949e")
    ax2.legend(facecolor="#21262d", edgecolor="#30363d", labelcolor="white", fontsize=9)
    plt.tight_layout()
    buf2 = grafik_kaydet(fig2)

    # ── Telegram'a gönder ─────────────────────────────────────────────────────
    await update.message.reply_photo(
        photo=buf1, caption=f"🌡 {sehir_adi} Sicaklik — ECMWF & GFS Ensemble")
    if tablo_metni:
        await update.message.reply_text(tablo_metni, parse_mode="Markdown")
    await update.message.reply_photo(
        photo=buf2, caption=f"💨 {sehir_adi} Ruzgar — ECMWF & GFS Ensemble")

# ── Handler kayıt ─────────────────────────────────────────────────────────────
def tahmin_handlerlari_ekle(app):
    app.add_handler(CommandHandler("tahmin", tahmin))
