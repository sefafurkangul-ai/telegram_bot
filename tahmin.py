import io
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from datetime import datetime
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

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

    hourly  = data["hourly"]
    tarihler = pd.to_datetime(hourly["time"])

    # Tüm üye kolonlarını bul (member01, member02 ...)
    uyeler = [k for k in hourly.keys() if k.startswith(degisken) and k != degisken]

    # Eğer üye yoksa direkt degisken kolonunu kullan
    if not uyeler:
        if degisken in hourly:
            df = pd.DataFrame({"tarih": tarihler, "medyan": hourly[degisken]})
            df["min"] = df["medyan"]
            df["max"] = df["medyan"]
            return df.dropna()
        return None

    # Üyeleri DataFrame'e al
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

# ── Grafik teması ─────────────────────────────────────────────────────────────
def grafik_olustur(figsize=(13, 5)):
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#161b22")
    for spine in ax.spines.values():
        spine.set_edgecolor("#30363d")
    ax.tick_params(colors="#8b949e")
    plt.xticks(color="#8b949e")
    plt.yticks(color="#8b949e")
    return fig, ax

def grafik_kaydet(fig) -> io.BytesIO:
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150,
                bbox_inches="tight", facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close()
    return buf

# ── Tek değişken için grafik çiz ─────────────────────────────────────────────
def degisken_grafik(sehir_adi, degisken, birim, baslik):
    modeller = {
        "ECMWF ENS": ("ecmwf_ifs025", "#58a6ff"),
        "GFS ENS"  : ("gfs_seamless",  "#f78166"),
    }

    fig, ax = grafik_olustur()
    veri_geldi = False

    for isim, (model, renk) in modeller.items():
        df = ensemble_cek(None, None, model, degisken)  # lat/lon dışarıdan verilecek
        if df is None:
            continue
        veri_geldi = True

        # Min-max bandı (çok şeffaf)
        ax.fill_between(df["tarih"], df["min"], df["max"],
                        color=renk, alpha=0.10)
        # %25-%75 bandı (biraz daha belirgin)
        ax.fill_between(df["tarih"], df["p25"], df["p75"],
                        color=renk, alpha=0.25, label=f"{isim} (%25–75)")
        # Medyan çizgisi
        ax.plot(df["tarih"], df["medyan"],
                color=renk, linewidth=2, label=f"{isim} Medyan")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    plt.xticks(rotation=45)
    ax.set_title(f"{sehir_adi} — {baslik} (10 Gün ENS)",
                 color="white", fontsize=13, pad=15)
    ax.set_ylabel(birim, color="#8b949e")
    ax.legend(facecolor="#21262d", edgecolor="#30363d",
              labelcolor="white", fontsize=9)
    plt.tight_layout()
    return fig, veri_geldi

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

    modeller = {
        "ECMWF ENS": ("ecmwf_ifs025", "#58a6ff"),
        "GFS ENS"  : ("gfs_seamless",  "#f78166"),
    }

    # ── Sıcaklık grafiği ──────────────────────────────────────────────────────
    fig1, ax1 = grafik_olustur()
    dfs_sicaklik = {}

    for isim, (model, renk) in modeller.items():
        df = ensemble_cek(lat, lon, model, "temperature_2m")
        if df is None:
            continue
        dfs_sicaklik[isim] = df

        ax1.fill_between(df["tarih"], df["min"], df["max"],
                         color=renk, alpha=0.10)
        ax1.fill_between(df["tarih"], df["p25"], df["p75"],
                         color=renk, alpha=0.25, label=f"{isim} (%25–75)")
        ax1.plot(df["tarih"], df["medyan"],
                 color=renk, linewidth=2, label=f"{isim} Medyan")

    ax1.axhline(y=0, color="#555", linestyle="--", linewidth=0.8, alpha=0.6)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax1.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    plt.xticks(rotation=45)
    ax1.set_title(f"{sehir_adi} — Sicaklik Tahmini (10 Gun ENS)",
                  color="white", fontsize=13, pad=15)
    ax1.set_ylabel("Sicaklik (C)", color="#8b949e")
    ax1.legend(facecolor="#21262d", edgecolor="#30363d",
               labelcolor="white", fontsize=9)
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
                    g = dfs_sicaklik[isim]
                    g = g[g["tarih"].dt.date == gun]
                    if not g.empty:
                        satir += f"{g['min'].min():>4.0f} {g['max'].max():>4.0f}  "
                    else:
                        satir += f"{'—':>4} {'—':>4}  "
            satirlar.append(satir)
        tablo_metni = "```\n" + "\n".join(satirlar) + "\n```"

    # ── Rüzgar grafiği ────────────────────────────────────────────────────────
    fig2, ax2 = grafik_olustur()

    for isim, (model, renk) in modeller.items():
        df = ensemble_cek(lat, lon, model, "wind_speed_10m")
        if df is None:
            continue

        ax2.fill_between(df["tarih"], df["min"], df["max"],
                         color=renk, alpha=0.10)
        ax2.fill_between(df["tarih"], df["p25"], df["p75"],
                         color=renk, alpha=0.25, label=f"{isim} (%25–75)")
        ax2.plot(df["tarih"], df["medyan"],
                 color=renk, linewidth=2, label=f"{isim} Medyan")

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax2.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    plt.xticks(rotation=45)
    ax2.set_title(f"{sehir_adi} — Ruzgar Hizi Tahmini (10 Gun ENS)",
                  color="white", fontsize=13, pad=15)
    ax2.set_ylabel("Ruzgar (km/h)", color="#8b949e")
    ax2.legend(facecolor="#21262d", edgecolor="#30363d",
               labelcolor="white", fontsize=9)
    plt.tight_layout()
    buf2 = grafik_kaydet(fig2)

    # ── Telegram'a gönder ─────────────────────────────────────────────────────
    await update.message.reply_photo(
        photo=buf1,
        caption=f"🌡 {sehir_adi} Sicaklik — ECMWF & GFS Ensemble"
    )
    if tablo_metni:
        await update.message.reply_text(tablo_metni, parse_mode="Markdown")
    await update.message.reply_photo(
        photo=buf2,
        caption=f"💨 {sehir_adi} Ruzgar — ECMWF & GFS Ensemble"
    )

# ── Handler kayıt ─────────────────────────────────────────────────────────────
def tahmin_handlerlari_ekle(app):
    app.add_handler(CommandHandler("tahmin", tahmin))
