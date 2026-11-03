"""OCR com Tesseract. Devolve linhas [{"t": texto, "box": (x0, y0, x1, y1)}]."""
import os

import pytesseract
from PIL import Image


def ler(img, cfg):
    if os.path.exists(cfg["tesseract_caminho"]):
        pytesseract.pytesseract.tesseract_cmd = cfg["tesseract_caminho"]
    esc = float(cfg["tesseract_escala"])
    entrada = img.resize((int(img.width * esc), int(img.height * esc)), Image.LANCZOS) if esc != 1 else img
    d = pytesseract.image_to_data(entrada, lang="eng", output_type=pytesseract.Output.DICT)

    grupos = {}  # uma entrada por linha detectada pelo Tesseract
    for i, texto in enumerate(d["text"]):
        texto = texto.strip()
        if not texto or float(d["conf"][i]) < 30:
            continue
        chave = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
        g = grupos.setdefault(chave, {"palavras": [], "box": [x, y, x + w, y + h]})
        g["palavras"].append(texto)
        b = g["box"]
        g["box"] = [min(b[0], x), min(b[1], y), max(b[2], x + w), max(b[3], y + h)]
    return [{"t": " ".join(g["palavras"]), "box": tuple(int(v / esc) for v in g["box"])}
            for g in grupos.values()]


def agrupar(linhas, juntar_linhas=True):
    """Transforma linhas em blocos. Com juntar_linhas, linhas vizinhas da mesma fala viram um bloco só
    (tradução melhor e fonte maior)."""
    linhas = sorted(linhas, key=lambda l: (l["box"][1], l["box"][0]))
    blocos = []
    for l in linhas:
        x0, y0, x1, y1 = l["box"]
        lh = max(y1 - y0, 1)
        if juntar_linhas:
            for b in blocos:
                bx0, by0, bx1, by1 = b["box"]
                folga = y0 - b["ult_y1"]
                sobreposicao = min(x1, bx1) - max(x0, bx0)
                if (-0.3 * lh <= folga <= 0.9 * lh
                        and sobreposicao > 0.3 * min(x1 - x0, bx1 - bx0)
                        and 0.6 <= lh / b["lh"] <= 1.7):
                    b["t"] += " " + l["t"]
                    b["box"] = (min(bx0, x0), by0, max(bx1, x1), max(by1, y1))
                    b["ult_y1"] = y1
                    break
            else:
                blocos.append({"t": l["t"], "box": (x0, y0, x1, y1), "lh": lh, "ult_y1": y1})
        else:
            blocos.append({"t": l["t"], "box": (x0, y0, x1, y1), "lh": lh, "ult_y1": y1})
    return blocos
