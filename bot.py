import os
from dotenv import load_dotenv
import matplotlib
matplotlib.use("Agg")

load_dotenv()

from telegram.ext import ApplicationBuilder
from telegram.request import HTTPXRequest
from agsi import agsi_handlerlari_ekle
from tahmin import tahmin_handlerlari_ekle
from ilker import ilker_handlerlari_ekle
from elektrik import elektrik_handlerlari_ekle
from epias import epias_handlerlari_ekle

BOT_TOKEN = os.environ.get("BOT_TOKEN")

if __name__ == "__main__":
    request = HTTPXRequest(httpx_kwargs={"verify": False})
    app = ApplicationBuilder().token(BOT_TOKEN).request(request).get_updates_request(request).build()
    agsi_handlerlari_ekle(app)
    tahmin_handlerlari_ekle(app)
    ilker_handlerlari_ekle(app)
    elektrik_handlerlari_ekle(app)
    epias_handlerlari_ekle(app)
    print("Bot çalışıyor...")
    app.run_polling()
