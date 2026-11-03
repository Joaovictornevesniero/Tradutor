import json
import time

import mss
from PIL import Image

cfg = json.load(open("config.json", encoding="utf-8"))
MSS = getattr(mss, "MSS", None) or mss.mss
with MSS() as s:
    shot = s.grab(cfg["area"])
    img = Image.frombytes("RGB", shot.size, shot.rgb)


def win():
    import winocr
    r = winocr.recognize_pil_sync(img, "en-US")
    return r["text"] if isinstance(r, dict) else r.text


def tess():
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    return pytesseract.image_to_string(img, lang="eng")


def goog():
    from deep_translator import GoogleTranslator
    return GoogleTranslator(source="auto", target="pt").translate("Hello, how are you today? I am fine.")


def argos():
    import argostranslate.translate as tr
    return tr.translate("Hello, how are you today?", "en", "pt")


for nome, f in [("windows OCR", win), ("tesseract", tess), ("google", goog), ("argos", argos)]:
    for i in (1, 2):
        ini = time.time()
        try:
            r = f()
            print(f"{nome} [{i}]: {time.time() - ini:.2f}s -> {str(r)[:60]!r}")
        except Exception as e:
            print(f"{nome} [{i}]: ERRO {time.time() - ini:.2f}s -> {str(e)[:120]}")