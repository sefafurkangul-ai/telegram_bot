import os
import matplotlib
matplotlib.use("Agg")

from telegram.ext import ApplicationBuilder
from agsi import agsi_handlerlari_ekle
from tahmin import tahmin_handlerlari_ekle

BOT_TOKEN = os.environ.get("BOT_TOKEN")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    agsi_handlerlari_ekle(app)
    tahmin_handlerlari_ekle(app)
    print("Bot çalışıyor...")
    app.run_polling()
