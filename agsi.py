import asyncio
import aiohttp
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from grafik_utils import grafik_olustur, grafik_kaydet

# ── Ayarlar ───────────────────────────────────────────────────────────────────
import os
AGSI_API_KEY = os.environ.get("AGSI_API_KEY")

ULKE_KODLARI = {
    "avrupa"    : "eu", "almanya"   : "de", "fransa"    : "fr",
    "italya"    : "it", "hollanda"  : "nl", "avusturya" : "at",
    "ispanya"   : "es", "polonya"   : "pl", "belcika"   : "be",
    "romanya"   : "ro", "macaristan": "hu", "cekya"     : "cz",
}

# ── Tek günlük async istek ────────────────────────────────────────────────────
async def agsi_tek_gun_async(ulke_kodu, tarih):
    url     = f"https://agsi.gie.eu/api?country={ulke_kodu}&date={tarih}"
    headers = {"x-key": AGSI_API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, ssl=False,
                                   timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                rows = data.get("data", [])
                return rows[0] if rows else {}
    except Exception:
        return {}

# ── Tarih aralığı — paralel async istekler ───────────────────────────────────
async def agsi_aralik(ulke_kodu: str, gun_sayisi: int,
                      max_concurrent: int = 20, step: int = 1) -> pd.DataFrame:
    bugun    = datetime.today()
    tarihler = [
        (bugun - timedelta(days=i+1)).strftime("%Y-%m-%d")
        for i in range(0, gun_sayisi, step)
    ]

    semaphore = asyncio.Semaphore(max_concurrent)

    async def limitli(session, tarih):
        url     = f"https://agsi.gie.eu/api?country={ulke_kodu}&date={tarih}"
        headers = {"x-key": AGSI_API_KEY}
        async with semaphore:
            try:
                async with session.get(url, headers=headers, ssl=False,
                                       timeout=aiohttp.ClientTimeout(total=10)) as r:
                    data = await r.json()
                    rows = data.get("data", [])
                    return rows[0] if rows else None
            except Exception:
                return None

    async with aiohttp.ClientSession() as session:
        sonuclar = await asyncio.gather(
            *[limitli(session, t) for t in tarihler],
            return_exceptions=True
        )

    tum_veri = [s for s in sonuclar if s and not isinstance(s, Exception)]

    if not tum_veri:
        return pd.DataFrame()

    df = pd.DataFrame(tum_veri)

    if "gasInStorage" not in df.columns or "workingGasVolume" not in df.columns:
        return pd.DataFrame()

    df["tarih"]      = pd.to_datetime(df["gasDayStart"])
    df["doluluk"]    = (
        pd.to_numeric(df["gasInStorage"],     errors="coerce") /
        pd.to_numeric(df["workingGasVolume"], errors="coerce") * 100
    ).round(2)
    df["hacim"]      = pd.to_numeric(df["gasInStorage"],    errors="coerce")
    df["enjeksiyon"] = pd.to_numeric(df["injection"],       errors="coerce")
    df["cekim"]      = pd.to_numeric(df["withdrawal"],      errors="coerce")
    df["gun_sirasi"] = df["tarih"].dt.dayofyear
    df["yil"]        = df["tarih"].dt.year
    return df.sort_values("tarih").reset_index(drop=True)


# ── /gaz : Anlık durum (tek istek, hızlı) ────────────────────────────────────
async def gaz_depo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ulke_adi  = " ".join(context.args).lower() if context.args else "avrupa"
    ulke_kodu = ULKE_KODLARI.get(ulke_adi)

    if not ulke_kodu:
        await update.message.reply_text(
            f"Bilinmeyen ulke. Secenekler:\n{', '.join(ULKE_KODLARI.keys())}"
        )
        return

    bugun = datetime.today()
    v     = await agsi_tek_gun_async(ulke_kodu, bugun.strftime("%Y-%m-%d"))
    if not v:
        v = await agsi_tek_gun_async(ulke_kodu, (bugun - timedelta(days=1)).strftime("%Y-%m-%d"))
    if not v:
        await update.message.reply_text("Veri alinamadi.")
        return

    depo     = float(v.get("gasInStorage",    0))
    kapasite = float(v.get("workingGasVolume", 1))
    doluluk  = round(depo / kapasite * 100, 2)
    bar      = "🟩" * int(doluluk / 10) + "⬜" * (10 - int(doluluk / 10))

    mesaj = (
        f"{ulke_adi.title()} Dogalgaz Depo Durumu\n"
        f"Tarih: {v['gasDayStart']}\n"
        f"────────────────\n"
        f"Doluluk: %{doluluk:.1f}\n"
        f"{bar}\n"
        f"Depodaki Gaz : {depo:.1f} TWh\n"
        f"Enjeksiyon   : {float(v.get('injection',  0)):.2f} GWh/gun\n"
        f"Cekim        : {float(v.get('withdrawal', 0)):.2f} GWh/gun\n"
    )
    await update.message.reply_text(mesaj)

# ── /gazgrafik : Y-2 Ekim'den bugüne ─────────────────────────────────────────
async def gaz_grafik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ulke_adi  = " ".join(context.args).lower() if context.args else "avrupa"
    ulke_kodu = ULKE_KODLARI.get(ulke_adi, "eu")

    await update.message.reply_text("Grafik hazirlaniyor...")

    bugun      = datetime.today()
    baslangic  = datetime(bugun.year - 2, 10, 1)
    gun_sayisi = (bugun - baslangic).days

    try:
        df = await asyncio.wait_for(agsi_aralik(ulke_kodu, gun_sayisi), timeout=60)
    except asyncio.TimeoutError:
        await update.message.reply_text("Zaman asimi. Lutfen tekrar deneyin.")
        return

    if df.empty:
        await update.message.reply_text("Veri alinamadi.")
        return

    fig, ax = grafik_olustur()
    ax.plot(df["tarih"], df["doluluk"], color="#58a6ff", linewidth=2)
    ax.fill_between(df["tarih"], df["doluluk"],
                    where=(df["doluluk"] >= 70),
                    color="#238636", alpha=0.4, label=">=%70")
    ax.fill_between(df["tarih"], df["doluluk"],
                    where=(df["doluluk"] >= 30) & (df["doluluk"] < 70),
                    color="#d29922", alpha=0.3, label="%30-70")
    ax.fill_between(df["tarih"], df["doluluk"],
                    where=(df["doluluk"] < 30),
                    color="#da3633", alpha=0.4, label="<%30")

    for seviye, renk in [(30, "#da3633"), (50, "#8b949e"), (70, "#238636")]:
        ax.axhline(y=seviye, color=renk, linestyle="--", linewidth=0.8, alpha=0.6)

    son_deger = df["doluluk"].iloc[-1]
    son_tarih = df["tarih"].iloc[-1]
    ax.scatter([son_tarih], [son_deger], color="white", s=50, zorder=5)
    ax.annotate(f" %{son_deger:.1f}", xy=(son_tarih, son_deger),
                color="white", fontsize=11, fontweight="bold",
                xytext=(8, 0), textcoords="offset points")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.xticks(rotation=45)
    ax.set_xlim(df["tarih"].iloc[0], df["tarih"].iloc[-1])
    ax.set_ylim(0, 100)
    ax.set_title(
        f"{ulke_adi.title()} Dogalgaz Depo - Eki {bugun.year-2} / Bugun",
        color="white", fontsize=13, pad=15)
    ax.set_ylabel("Doluluk (%)", color="#8b949e")
    ax.legend(facecolor="#21262d", edgecolor="#30363d",
              labelcolor="white", fontsize=9, loc="upper left")
    plt.tight_layout()

    buf = grafik_kaydet(fig)
    await update.message.reply_photo(
        photo=buf,
        caption=f"{ulke_adi.title()} | Eki {bugun.year-2} - Bugun | Guncel: %{son_deger:.1f}"
    )

# ── /gazytd : Bu yıl vs geçen yıl + 5 yıl bulutu ────────────────────────────
async def gaz_ytd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ulke_adi  = " ".join(context.args).lower() if context.args else "avrupa"
    ulke_kodu = ULKE_KODLARI.get(ulke_adi, "eu")

    await update.message.reply_text("YTD grafigi hazirlaniyor...")

    bugun = datetime.today()
    yil   = bugun.year

    try:
        # Bulut (Y-5'ten Y-2'ye, haftalık) + detaylı (Y-1 ve Y, günlük) paralel çek
        gun_bulut  = (bugun - datetime(yil - 5, 1, 1)).days
        gun_detay  = (bugun - datetime(yil - 1, 1, 1)).days
        df_bulut, df_detay = await asyncio.wait_for(
            asyncio.gather(
                agsi_aralik(ulke_kodu, gun_bulut, max_concurrent=10, step=14),
                agsi_aralik(ulke_kodu, gun_detay, max_concurrent=10, step=1),
            ),
            timeout=120
        )
        df_tum = (pd.concat([df_bulut, df_detay])
                  .drop_duplicates(subset=["tarih"], keep="last")
                  .sort_values("tarih")
                  .reset_index(drop=True))
    except asyncio.TimeoutError:
        await update.message.reply_text("Zaman asimi. Lutfen tekrar deneyin.")
        return

    if df_tum.empty:
        await update.message.reply_text("Veri alinamadi.")
        return

    # Yıllara göre ayır
    veriler = {y: df_tum[df_tum["yil"] == y]
               for y in range(yil - 5, yil + 1)
               if not df_tum[df_tum["yil"] == y].empty}

    if not veriler:
        await update.message.reply_text("Veri alinamadi.")
        return

    fig, ax = grafik_olustur()
    bugun_gun = bugun.timetuple().tm_yday

    # ── 5 yıllık min-max bulutu (Y-5 … Y-1) ─────────────────────────────────
    bulut_yillar = [y for y in range(yil - 5, yil) if y in veriler]
    if bulut_yillar:
        bulut_df = df_tum[df_tum["yil"].isin(bulut_yillar)]
        bulut_g  = (bulut_df.groupby("gun_sirasi")["doluluk"]
                    .agg(["min", "max"])
                    .reindex(range(1, 367))
                    .interpolate(method="linear")
                    .reset_index()
                    .rename(columns={"index": "gun_sirasi"}))
        ax.fill_between(bulut_g["gun_sirasi"], bulut_g["min"], bulut_g["max"],
                        color="#8b949e", alpha=0.18,
                        label=f"{min(bulut_yillar)}-{max(bulut_yillar)} araligi")

    # ── Geçen yıl ve bu yıl çizgileri ────────────────────────────────────────
    renkler = {yil: "#58a6ff", yil - 1: "#f78166"}
    for y in [yil - 1, yil]:
        if y not in veriler:
            continue
        df       = veriler[y]
        renk     = renkler[y]
        son_gun  = df["gun_sirasi"].iloc[-1]
        son_deger = df["doluluk"].iloc[-1]
        kalinlik = 2.5 if y == yil else 1.5

        ax.plot(df["gun_sirasi"], df["doluluk"], color=renk,
                linewidth=kalinlik, label=f"{y} (%{son_deger:.1f})", zorder=3)

        if y == yil:
            ax.fill_between(df["gun_sirasi"], df["doluluk"],
                            alpha=0.10, color=renk, zorder=2)

        ax.scatter([son_gun], [son_deger], color=renk, s=55, zorder=5)
        ax.annotate(f" %{son_deger:.1f}", xy=(son_gun, son_deger),
                    color=renk, fontsize=9, fontweight="bold",
                    xytext=(5, 4), textcoords="offset points")

    ax.axvline(x=bugun_gun, color="#8b949e", linestyle=":",
               linewidth=1.2, label=f"Bugun ({bugun.strftime('%d %b')})")

    for seviye, renk in [(30, "#da3633"), (50, "#555"), (70, "#238636")]:
        ax.axhline(y=seviye, color=renk, linestyle="--", linewidth=0.8, alpha=0.5)

    ay_baslangic = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    ay_isimleri  = ["Oca","Sub","Mar","Nis","May","Haz",
                    "Tem","Agu","Eyl","Eki","Kas","Ara"]
    ax.set_xticks(ay_baslangic)
    ax.set_xticklabels(ay_isimleri, color="#8b949e")
    ax.set_xlim(1, 365)
    ax.set_ylim(0, 100)
    bulut_etiket = (f"{min(bulut_yillar)}-{max(bulut_yillar)}"
                    if bulut_yillar else "")
    baslik = (f"{ulke_adi.title()} Dogalgaz - YTD ({yil-1} vs {yil}"
              + (f" | {bulut_etiket} bulutu)" if bulut_etiket else ")"))
    ax.set_title(baslik, color="white", fontsize=13, pad=15)
    ax.set_ylabel("Doluluk (%)", color="#8b949e")
    ax.legend(facecolor="#21262d", edgecolor="#30363d",
              labelcolor="white", fontsize=9, loc="upper left")
    plt.tight_layout()

    buf = grafik_kaydet(fig)

    # Caption
    bugun_deger     = veriler[yil]["doluluk"].iloc[-1] if yil in veriler else None
    gecen_yil_deger = None
    fark_metni      = ""

    if (yil - 1) in veriler:
        df_gecen   = veriler[yil - 1]
        gecen_ayni = df_gecen[df_gecen["gun_sirasi"] == bugun_gun]
        if not gecen_ayni.empty:
            gecen_yil_deger = gecen_ayni["doluluk"].iloc[0]
            if bugun_deger is not None:
                fark    = bugun_deger - gecen_yil_deger
                isaret  = "+" if fark > 0 else ""
                fark_metni = f"\nGecen yila fark: {isaret}{fark:.1f} puan"

    caption = (
        (f"{yil}: %{bugun_deger:.1f}\n" if bugun_deger else "")
        + (f"{yil-1}: %{gecen_yil_deger:.1f}" if gecen_yil_deger else "")
        + fark_metni
    )
    await update.message.reply_photo(photo=buf, caption=caption)

# ── Handler kayıt ─────────────────────────────────────────────────────────────
def agsi_handlerlari_ekle(app):
    app.add_handler(CommandHandler("gaz",       gaz_depo))
    app.add_handler(CommandHandler("gazgrafik", gaz_grafik))
    app.add_handler(CommandHandler("gazytd",    gaz_ytd))
