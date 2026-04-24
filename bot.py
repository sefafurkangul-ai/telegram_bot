import os
import logging
from dotenv import load_dotenv
import matplotlib
matplotlib.use("Agg")

load_dotenv()

from telegram.error import NetworkError
from telegram.ext import ApplicationBuilder
from telegram.request import HTTPXRequest
from agsi import agsi_handlerlari_ekle
from tahmin import tahmin_handlerlari_ekle
from ilker import ilker_handlerlari_ekle
from elektrik import elektrik_handlerlari_ekle

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")


async def hata_handler(update, context):
    if isinstance(context.error, NetworkError):
        return  # geçici bağlantı kopmaları sessizce geçilsin
    logging.error("Beklenmeyen hata:", exc_info=context.error)


if __name__ == "__main__":
    request = HTTPXRequest(httpx_kwargs={"verify": False})
    app = ApplicationBuilder().token(BOT_TOKEN).request(request).get_updates_request(request).build()
    app.add_error_handler(hata_handler)
    agsi_handlerlari_ekle(app)
    tahmin_handlerlari_ekle(app)
    ilker_handlerlari_ekle(app)
    elektrik_handlerlari_ekle(app)
    print("Bot çalışıyor...")
    app.run_polling()
