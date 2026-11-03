"""
Tradutor de tela (com menu)
F8  = traduz a área e cobre o texto original / F8 de novo = remove
F9  = escolher a área da tela
F10 = abrir/fechar o menu (modo, OCR, tradutor, idioma, fonte...)

Arquivos na mesma pasta: tradutor.py, config.json, ptbr.json
Instalar:
  pip install mss pillow keyboard google-genai deep-translator pytesseract winocr argostranslate
  (+ programa Tesseract: github.com/UB-Mannheim/tesseract/wiki)
Para o tradutor "opus" (Opus-MT pt-BR): coloque opus_tradutor.py na mesma pasta e use
  pip install ctranslate2 sentencepiece
  (só na 1ª vez, para converter o modelo: pip install transformers torch huggingface_hub)
Opcional: pip install easyocr
"""
import ctypes
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
import urllib.request
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from tkinter import ttk
from urllib.parse import quote

import keyboard
import mss
from google import genai
from google.genai import types
from PIL import Image


# ---------- log: tudo que aparece no terminal também vai para log.txt ----------
class Tee:
    def __init__(self, *saidas):
        self.saidas = [s for s in saidas if s]

    def write(self, dado):
        for s in self.saidas:
            s.write(dado)
            s.flush()

    def flush(self):
        pass


_log = open("log.txt", "a", encoding="utf-8")
sys.stdout = Tee(sys.__stdout__, _log)
sys.stderr = Tee(sys.__stderr__, _log)
print(f"\n===== iniciado {time.strftime('%d/%m/%Y %H:%M:%S')} =====")

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

CONFIG_FILE = "config.json"
PADRAO = {
    "api_key": "",
    "modelos": ["gemini-flash-lite-latest", "gemini-3.8-flash", "gemini-3.5-flash",
                "gemini-flash-latest"],
    "modo": "ocr_local",              # gemini_completo | ocr_local
    "ocr": "tesseract",               # windows | tesseract | easyocr
    "tradutor": "opus",               # opus | argos | gtx | google | gemini | groq
    "idioma_origem": "en",
    "idioma_destino": "português do Brasil",
    "destino_codigo": "pt",
    "ajustar_ptbr": True,             # corrige português de Portugal (Argos e Opus)
    "opus_manter_caixa_alta": False,  # Opus: se o texto lido era MAIÚSCULO, devolve MAIÚSCULO
    "fonte_escala": 1.2,
    "juntar_linhas": True,
    "fallback": False,
    "mostrar_tempo": True,
    "tecla_traduzir": "f8",
    "tecla_configurar_area": "f9",
    "tecla_menu": "f10",
    "tamanho_max": 1280,
    "baixa_resolucao": False,
    "timeout_ms": 10000,              # Gemini / Groq
    "timeout_traducao_ms": 5000,      # Google / gtx / Argos
    "tesseract_escala": 1,            # 2 = amplia a imagem (lê texto pequeno melhor, mais lento)
    "tesseract_caminho": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    "groq_api_key": "",
    "groq_modelo": "llama-3.3-70b-versatile",
    "area": None,
}
TRANSP = "#010101"

MENU_MODOS = {"Gemini completo (1 chamada)": "gemini_completo", "OCR local + tradutor": "ocr_local"}
MENU_OCRS = {"Windows OCR (rápido)": "windows", "Tesseract": "tesseract",
             "EasyOCR (pesado, bom p/ asiático)": "easyocr"}
MENU_TRADS = {"Opus-MT pt-BR (offline, recomendado)": "opus", "Argos (offline)": "argos", "Google rápido (gtx)": "gtx",
              "Google (deep-translator)": "google", "Gemini (só texto)": "gemini",
              "Groq (llama)": "groq"}
MENU_ORIGENS = {"Inglês": "en", "Coreano": "ko", "Japonês": "ja", "Chinês": "zh", "Espanhol": "es",
                "Russo": "ru", "Francês": "fr", "Alemão": "de", "Português": "pt"}
MENU_DESTINOS = {"português do Brasil": "pt", "inglês": "en", "espanhol": "es", "francês": "fr",
                 "alemão": "de", "italiano": "it", "japonês": "ja"}
WIN_LANG = {"en": "en-US", "ko": "ko", "ja": "ja", "zh": "zh-Hans-CN", "es": "es-ES",
            "ru": "ru", "fr": "fr-FR", "de": "de-DE", "pt": "pt-BR"}
TESS_LANG = {"en": "eng", "ko": "kor", "ja": "jpn", "zh": "chi_sim", "es": "spa",
             "ru": "rus", "fr": "fra", "de": "deu", "pt": "por"}
EASY_LANG = {"en": "en", "ko": "ko", "ja": "ja", "zh": "ch_sim", "es": "es",
             "ru": "ru", "fr": "fr", "de": "de", "pt": "pt"}


def carregar_config():
    cfg = dict(PADRAO)
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg.update(json.load(f))
    else:
        salvar_config(cfg)
    return cfg


def salvar_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


MSS = getattr(mss, "MSS", None) or mss.mss
cfg = carregar_config()

root = tk.Tk()
root.withdraw()
fila = queue.Queue()
estado = {"overlay": None, "canvas": None, "img": None, "req": 0}
cache = {}


# ---------- Gemini ----------
_client = {"c": None}


def obter_client():
    if _client["c"] is None:
        chave = cfg["api_key"] or os.environ.get("GEMINI_API_KEY", "")
        if not chave or chave == "SUA_CHAVE":
            raise RuntimeError("Falta a api_key do Gemini no config.json")
        _client["c"] = genai.Client(api_key=chave, http_options=types.HttpOptions(timeout=cfg["timeout_ms"]))
    return _client["c"]


def montar_conf(sem_pensar):
    extra = {}
    if sem_pensar:
        extra["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    if cfg["baixa_resolucao"]:
        extra["media_resolution"] = "MEDIA_RESOLUTION_LOW"
    return types.GenerateContentConfig(
        response_mime_type="application/json", temperature=0.2, **extra)


CONF_RAPIDO = montar_conf(True)
CONF_BASE = montar_conf(False)


def gemini_gerar(conteudo, validar):
    """Tenta cada modelo da lista até um responder e passar na validação."""
    c = obter_client()
    erros = []
    for modelo in cfg["modelos"]:
        conf = CONF_RAPIDO
        for tentativa in range(2):
            ini = time.time()
            try:
                resp = c.models.generate_content(model=modelo, contents=conteudo, config=conf)
                r = validar(resp.text)
                print(f"OK gemini {modelo} em {time.time() - ini:.1f}s")
                return r
            except Exception as e:
                msg = str(e)
                if tentativa == 0 and "thinking" in msg.lower():
                    conf = CONF_BASE
                    continue
                print(f"FALHOU {modelo} ({time.time() - ini:.1f}s): {e}")
                if "API key not valid" in msg or "API_KEY_INVALID" in msg:
                    raise RuntimeError("Chave de API do Gemini inválida.")
                erros.append(f"{modelo}: {msg[:100]}")
                break
    raise RuntimeError("Nenhum modelo Gemini funcionou.\n" + "\n".join(erros))


def _limpar_json(txt):
    txt = (txt or "").strip()
    if txt.startswith("```"):
        txt = txt.strip("`").removeprefix("json").strip()
    return json.loads(txt)


def interpretar(txt):
    dados = _limpar_json(txt)
    if isinstance(dados, dict):
        dados = dados.get("blocos", [])
    return [d for d in dados if d.get("t") and len(d.get("b", [])) == 4]


def modo_gemini_completo(img):
    pequena = img.copy()
    pequena.thumbnail((cfg["tamanho_max"], cfg["tamanho_max"]))
    d = cfg["idioma_destino"]
    prompt = (
        "Você é um tradutor. Encontre todos os textos visíveis nesta imagem (cada fala, legenda, "
        "linha ou frase separada é um bloco). Detecte o idioma de cada bloco, seja qual for, e "
        f'traduza para {d}. O campo "t" DEVE estar em {d}: nunca copie o texto original '
        f"(só deixe igual se já estiver em {d}). "
        'Responda SOMENTE um JSON: lista de objetos {"t": "tradução", "b": [ymin, xmin, ymax, xmax]}, '
        "onde b é a caixa que envolve justo o texto ORIGINAL, em coordenadas normalizadas de 0 a 1000. "
        "Ignore ícones e números soltos. Se não houver texto, responda []."
    )
    brutos = gemini_gerar([pequena, prompt], interpretar)
    W, H = img.size
    blocos = []
    for d_ in brutos:
        ymin, xmin, ymax, xmax = [max(0, min(1000, float(v))) for v in d_["b"]]
        box = (int(xmin / 1000 * W), int(ymin / 1000 * H), int(xmax / 1000 * W), int(ymax / 1000 * H))
        blocos.append({"t": str(d_["t"]), "box": box, "lh": max(box[3] - box[1], 8)})
    return blocos, "gemini completo"


# ---------- OCR local: cada função devolve [{"t": texto, "box": (x0,y0,x1,y1)}] ----------
def _g(o, nome):
    return o[nome] if isinstance(o, dict) else getattr(o, nome)


def ocr_windows(img, origem):
    try:
        import winocr  # type: ignore
    except ImportError:
        raise RuntimeError("Falta: pip install winocr (e o idioma de OCR instalado no Windows)")
    r = winocr.recognize_pil_sync(img, WIN_LANG.get(origem, origem))
    linhas = []
    for ln in _g(r, "lines"):
        x0 = y0 = 10 ** 9
        x1 = y1 = -1
        for w in _g(ln, "words"):
            b = _g(w, "bounding_rect")
            x, y, bw, bh = (_g(b, k) for k in ("x", "y", "width", "height"))
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x + bw), max(y1, y + bh)
        texto = str(_g(ln, "text")).strip()
        if texto and x1 > 0:
            linhas.append({"t": texto, "box": (int(x0), int(y0), int(x1), int(y1))})
    return linhas


def ocr_tesseract(img, origem):
    try:
        import pytesseract
    except ImportError:
        raise RuntimeError("Falta: pip install pytesseract + instalar o programa Tesseract")
    if os.path.exists(cfg["tesseract_caminho"]):
        pytesseract.pytesseract.tesseract_cmd = cfg["tesseract_caminho"]
    lang = TESS_LANG.get(origem, "eng") + ("+eng" if origem != "en" else "")
    esc = float(cfg["tesseract_escala"])
    entrada = img.resize((int(img.width * esc), int(img.height * esc)), Image.LANCZOS) if esc != 1 else img
    d = pytesseract.image_to_data(entrada, lang=lang, output_type=pytesseract.Output.DICT)
    grupos = {}
    for i, t in enumerate(d["text"]):
        t = t.strip()
        if not t or float(d["conf"][i]) < 30:
            continue
        k = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
        g = grupos.setdefault(k, {"ws": [], "box": [x, y, x + w, y + h]})
        g["ws"].append(t)
        g["box"] = [min(g["box"][0], x), min(g["box"][1], y), max(g["box"][2], x + w), max(g["box"][3], y + h)]
    return [{"t": " ".join(g["ws"]), "box": tuple(int(v / esc) for v in g["box"])} for g in grupos.values()]


_easy = {}


def ocr_easy(img, origem):
    try:
        import easyocr  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        raise RuntimeError("Falta: pip install easyocr")
    langs = list(dict.fromkeys([EASY_LANG.get(origem, "en"), "en"]))
    chave = tuple(langs)
    if chave not in _easy:
        print("EasyOCR: carregando modelo (demora na primeira vez)...")
        _easy[chave] = easyocr.Reader(langs)
    linhas = []
    for pts, texto, conf in _easy[chave].readtext(np.array(img)):
        if conf < 0.3 or not texto.strip():
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        linhas.append({"t": texto.strip(), "box": (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))})
    return linhas


OCRS = {"windows": ocr_windows, "tesseract": ocr_tesseract, "easyocr": ocr_easy}


def juntar(linhas):
    """Junta linhas vizinhas (mesma fala/parágrafo) em um bloco só: tradução melhor e fonte maior."""
    linhas = sorted(linhas, key=lambda l: (l["box"][1], l["box"][0]))
    blocos = []
    for l in linhas:
        x0, y0, x1, y1 = l["box"]
        lh = max(y1 - y0, 1)
        for b in blocos:
            bx0, by0, bx1, by1 = b["box"]
            gap = y0 - b["ult_y1"]
            sobre = min(x1, bx1) - max(x0, bx0)
            if (-0.3 * lh <= gap <= 0.9 * lh and sobre > 0.3 * min(x1 - x0, bx1 - bx0)
                    and 0.6 <= lh / b["lh"] <= 1.7):
                b["t"] += " " + l["t"]
                b["box"] = (min(bx0, x0), by0, max(bx1, x1), max(by1, y1))
                b["ult_y1"] = y1
                break
        else:
            blocos.append({"t": l["t"], "box": (x0, y0, x1, y1), "lh": lh, "ult_y1": y1})
    return blocos


# ---------- português de Portugal -> Brasil (usa o ptbr.json, recarrega sozinho) ----------
PTBR_ARQ = "ptbr.json"
_ptbr = {"mtime": None, "pal": {}, "pad": None, "rx": []}
GERUNDIO = {"ar": "ando", "er": "endo", "ir": "indo"}


def _carregar_ptbr():
    try:
        m = os.path.getmtime(PTBR_ARQ)
    except OSError:
        return
    if m == _ptbr["mtime"]:
        return
    _ptbr["mtime"] = m
    try:
        with open(PTBR_ARQ, encoding="utf-8") as f:
            d = json.load(f)
        pal = {k.lower(): v for k, v in d.get("palavras", {}).items()}
        _ptbr["pal"] = pal
        _ptbr["pad"] = re.compile(
            r"\b(" + "|".join(re.escape(k) for k in sorted(pal, key=len, reverse=True)) + r")\b",
            re.I) if pal else None
        _ptbr["rx"] = [(re.compile(k, re.I), v) for k, v in d.get("regex", {}).items()]
        print(f"ptbr.json carregado: {len(pal)} palavras, {len(_ptbr['rx'])} regras")
    except Exception as e:
        print(f"ptbr.json com erro: {e}")


def ajustar_ptbr(t):
    _carregar_ptbr()
    # "estou a fazer" -> "estou fazendo"
    t = re.sub(r"\b(estou|está|estamos|estão|estava|estavam|esteve|fico|ficou|continua|continuo|continuam) a (\w+?)(ar|er|ir)\b",
               lambda m: f"{m.group(1)} {m.group(2)}{GERUNDIO[m.group(3)]}", t, flags=re.I)

    # "diz-me" -> "me diz"
    def clitico(m):
        v, p = m.group(1), m.group(2).lower()
        if v[0].isupper():
            return p.capitalize() + " " + v[0].lower() + v[1:]
        return p + " " + v

    t = re.sub(r"\b(\w+)-(me|te|se|lhe|lhes|nos)\b", clitico, t)
    for rx, v in _ptbr["rx"]:
        t = rx.sub(v, t)
    if _ptbr["pad"]:
        def troca(m):
            novo = _ptbr["pal"][m.group(0).lower()]
            return novo[0].upper() + novo[1:] if m.group(0)[0].isupper() else novo

        t = _ptbr["pad"].sub(troca, t)
    return re.sub(r"\b(você) \1\b", r"\1", t, flags=re.I)  # "tu estás" -> "você está"


# ---------- tradutores: recebem lista de textos, devolvem lista traduzida ----------
def trad_google(textos):
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        raise RuntimeError("Falta: pip install deep-translator")
    gt = GoogleTranslator(source="auto", target=cfg["destino_codigo"])
    junto = "\n".join(t.replace("\n", " ") for t in textos)
    if len(junto) < 4500:  # uma requisição só = mais rápido
        partes = (gt.translate(junto) or "").split("\n")
        if len(partes) == len(textos):
            return [p.strip() for p in partes]
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(lambda t: gt.translate(t) or t, textos))


def trad_gtx(textos):
    def um(t):
        url = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl="
               + cfg["destino_codigo"] + "&dt=t&q=" + quote(t))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            d = json.loads(r.read().decode("utf-8"))
        return "".join(p[0] for p in d[0] if p and p[0]) or t

    with ThreadPoolExecutor(4) as ex:
        return list(ex.map(um, textos))


_argos = {}


def _frases(t):
    """Quebra em frases curtas: o Argos perde palavras quando recebe trecho muito longo."""
    saida = []
    for f in re.split(r"(?<=[.!?…])\s+", t.strip()):
        while len(f) > 160:  # frase longa: quebra em vírgula ou ponto e vírgula
            corte = max(f.rfind(", ", 0, 160), f.rfind("; ", 0, 160))
            if corte < 40:
                break
            saida.append(f[:corte + 1])
            f = f[corte + 2:]
        if f.strip():
            saida.append(f)
    return saida


def trad_argos(textos):
    try:
        import argostranslate.package as pkg  # type: ignore
        import argostranslate.translate as tr  # type: ignore
    except ImportError:
        raise RuntimeError("Falta: pip install argostranslate")
    a, b = cfg["idioma_origem"], cfg["destino_codigo"]
    if (a, b) not in _argos:
        def achar():
            langs = {l.code: l for l in tr.get_installed_languages()}
            if a in langs and b in langs:
                return langs[a].get_translation(langs[b])
            return None

        t = achar()
        if t is None:
            print("Argos: baixando pacotes de idioma (só na primeira vez)...")
            pkg.update_package_index()
            disp = pkg.get_available_packages()

            def instalar(de, para):
                for p in disp:
                    if p.from_code == de and p.to_code == para:
                        pkg.install_from_path(p.download())
                        return True
                return False

            if not instalar(a, b):
                instalar(a, "en")
                instalar("en", b)
            t = achar()
        if t is None:
            raise RuntimeError(f"Argos não tem o par {a} -> {b}")
        _argos[(a, b)] = t
    traduz = _argos[(a, b)].translate
    res = [" ".join(traduz(p) for p in _frases(x)) or x for x in textos]
    return [ajustar_ptbr(x) for x in res] if (b == "pt" and cfg.get("ajustar_ptbr", True)) else res


def trad_opus(textos):
    if cfg["idioma_origem"] != "en" or cfg["destino_codigo"] != "pt":
        raise RuntimeError("Opus-MT aqui só faz inglês -> português do Brasil (use outro tradutor para os demais idiomas)")
    try:
        import opus_tradutor
    except ImportError:
        raise RuntimeError("Falta o arquivo opus_tradutor.py na mesma pasta do tradutor.py")
    res = opus_tradutor.traduzir(
        textos, _frases, manter_caixa_alta=cfg.get("opus_manter_caixa_alta", False))
    return [ajustar_ptbr(x) for x in res] if cfg.get("ajustar_ptbr", True) else res


def trad_gemini(textos):
    prompt = (f"Traduza cada item da lista JSON abaixo para {cfg['idioma_destino']} (detecte o idioma). "
              "Responda SOMENTE um JSON: lista de strings, com exatamente o mesmo número de itens e na "
              "mesma ordem. Nunca copie o original.\n" + json.dumps(textos, ensure_ascii=False))

    def validar(txt):
        dados = _limpar_json(txt)
        if isinstance(dados, dict):
            dados = next(iter(dados.values()))
        if len(dados) != len(textos):
            raise ValueError("quantidade de itens diferente")
        return [str(x) for x in dados]

    return gemini_gerar([prompt], validar)


def trad_groq(textos):
    chave = cfg["groq_api_key"] or os.environ.get("GROQ_API_KEY", "")
    if not chave:
        raise RuntimeError("Falta groq_api_key no config.json (chave grátis em console.groq.com)")
    corpo = {
        "model": cfg["groq_modelo"], "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": f'Traduza cada item da lista para {cfg["idioma_destino"]} '
             '(detecte o idioma). Responda SOMENTE um JSON {"t": [...]} com o mesmo número de itens '
             "e na mesma ordem."},
            {"role": "user", "content": json.dumps(textos, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions", data=json.dumps(corpo).encode("utf-8"),
        headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json",
                 "User-Agent": "tradutor/1.0"})
    with urllib.request.urlopen(req, timeout=cfg["timeout_ms"] / 1000) as r:
        dados = json.loads(r.read().decode("utf-8"))
    lista = json.loads(dados["choices"][0]["message"]["content"])["t"]
    if len(lista) != len(textos):
        raise ValueError("Groq devolveu quantidade diferente de itens")
    return [str(x) for x in lista]


TRADUTORES = {"opus": trad_opus, "argos": trad_argos, "gtx": trad_gtx, "google": trad_google,
              "gemini": trad_gemini, "groq": trad_groq}
ORDEM_FALLBACK = ["opus", "argos", "gtx", "google", "gemini", "groq"]


def com_timeout(fn, arg, ms):
    """Roda fn(arg) e desiste se passar do tempo (evita travar esperando rede)."""
    ex = ThreadPoolExecutor(1)
    try:
        return ex.submit(fn, arg).result(timeout=ms / 1000)
    except FutTimeout:
        raise RuntimeError(f"demorou mais de {ms / 1000:.0f}s")
    finally:
        ex.shutdown(wait=False)


def _opus_pronto():
    try:
        import opus_tradutor
        return opus_tradutor.pronto()
    except ImportError:
        return True  # sem o módulo falha rápido com mensagem clara


def traduzir_textos(textos):
    escolhido = cfg["tradutor"]
    ordem = [escolhido] + ([t for t in ORDEM_FALLBACK if t != escolhido] if cfg["fallback"] else [])
    erros = []
    for nome in ordem:
        ini = time.time()
        if (nome == "argos" and not _argos) or (nome == "opus" and not _opus_pronto()):
            ms = 600000  # primeira vez carrega (ou converte, no Opus) o modelo / baixa o pacote de idioma
        elif nome in ("gemini", "groq"):
            ms = cfg["timeout_ms"]
        else:
            ms = cfg["timeout_traducao_ms"]
        try:
            r = com_timeout(TRADUTORES[nome], textos, ms)
            print(f"OK tradutor {nome} em {time.time() - ini:.1f}s")
            return r, nome
        except Exception as e:
            print(f"FALHOU tradutor {nome} ({time.time() - ini:.1f}s): {e}")
            erros.append(f"{nome}: {str(e)[:160]}")
    raise RuntimeError("Tradução falhou.\n" + "\n".join(erros))


def modo_ocr_local(img):
    ini = time.time()
    linhas = OCRS[cfg["ocr"]](img, cfg["idioma_origem"])
    t_ocr = time.time() - ini
    print(f"OCR {cfg['ocr']}: {len(linhas)} linhas em {t_ocr:.1f}s")
    if not linhas:
        return [], f"{cfg['ocr']} {t_ocr:.1f}s: nenhum texto lido"
    if cfg["juntar_linhas"]:
        blocos = juntar(linhas)
    else:
        blocos = [{"t": l["t"], "box": l["box"], "lh": max(l["box"][3] - l["box"][1], 1)} for l in linhas]
    ini2 = time.time()
    traduzidos, nome = traduzir_textos([b["t"] for b in blocos])
    for b, t in zip(blocos, traduzidos):
        print(f"  ORIGINAL: {b['t']}\n  TRADUÇÃO: {t}")  # para ver onde uma palavra some
        b["t"] = t
    return blocos, f"{cfg['ocr']} {t_ocr:.1f}s + {nome} {time.time() - ini2:.1f}s"


def processar(img):
    sig = "|".join(str(cfg[k]) for k in ("modo", "ocr", "tradutor", "idioma_origem",
                                          "destino_codigo", "juntar_linhas", "fallback", "ajustar_ptbr"))
    chave = sig + hashlib.md5(img.tobytes()).hexdigest()
    if chave in cache:
        blocos, info = cache[chave]
        return blocos, info + " (cache)"
    ini = time.time()
    blocos, info = modo_gemini_completo(img) if cfg["modo"] == "gemini_completo" else modo_ocr_local(img)
    info = f"{info} | total {time.time() - ini:.1f}s"
    print(info)
    cache[chave] = (blocos, info)
    return blocos, info


def trabalhar(img, req):
    try:
        fila.put(("resultado", req, processar(img)))
    except Exception as e:
        print(traceback.format_exc())
        fila.put(("erro", req, str(e)))


def aquecer():
    """Carrega OCR e tradutor em segundo plano ao abrir, para o primeiro F8 não pagar esse custo."""
    try:
        if cfg["modo"] == "ocr_local":
            ini = time.time()
            OCRS[cfg["ocr"]](Image.new("RGB", (200, 60), "white"), cfg["idioma_origem"])
            TRADUTORES[cfg["tradutor"]](["Hello"])
            print(f"Aquecimento pronto em {time.time() - ini:.1f}s")
    except Exception as e:
        print(f"Aquecimento falhou: {e}")


# ---------- captura ----------
def area_atual():
    if cfg["area"]:
        return cfg["area"]
    with MSS() as sct:
        return dict(sct.monitors[1])


def capturar(area):
    with MSS() as sct:
        shot = sct.grab(area)
        return Image.frombytes("RGB", shot.size, shot.rgb)


# ---------- overlay ----------
def fechar_overlay():
    if estado["overlay"]:
        estado["overlay"].destroy()
    estado["overlay"] = estado["canvas"] = None


def abrir_overlay(area):
    w, h = area["width"], area["height"]
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.attributes("-transparentcolor", TRANSP)
    win.geometry(f"{w}x{h}+{area['left']}+{area['top']}")
    win.configure(bg=TRANSP)
    canvas = tk.Canvas(win, bg=TRANSP, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.bind("<Button-1>", lambda e: fechar_overlay())
    estado["overlay"], estado["canvas"] = win, canvas
    selo(canvas, "Traduzindo...")


def selo(canvas, texto, cor="#222222"):
    canvas.delete("all")
    canvas.create_rectangle(4, 4, 150, 30, fill=cor, outline="")
    canvas.create_text(77, 17, text=texto, fill="white", font=("Segoe UI", 10, "bold"))


def cor_dominante(img, caixa):
    trecho = img.crop(caixa).resize((24, 24))
    cores = trecho.getcolors(576) or [(1, (0, 0, 0))]
    return sorted(cores, reverse=True)[0][1]


def desenhar(blocos, img, info):
    canvas = estado["canvas"]
    if not canvas:
        return
    canvas.delete("all")
    W, H = img.size
    for b in blocos:
        try:
            x0, y0, x1, y1 = b["box"]
            x0, y0, x1, y1 = max(0, x0 - 3), max(0, y0 - 2), min(W, x1 + 3), min(H, y1 + 2)
            bw, bh = x1 - x0, y1 - y0
            if bw < 6 or bh < 6:
                continue
            r, g, bl = cor_dominante(img, (x0, y0, x1, y1))[:3]
            fundo = "#%02x%02x%02x" % (r, g, bl)
            texto_cor = "#000000" if (0.299 * r + 0.587 * g + 0.114 * bl) > 140 else "#ffffff"
            ret = canvas.create_rectangle(x0, y0, x1, y1, fill=fundo, outline="")
            tam = int(max(10, min(b["lh"] * 0.9 * cfg["fonte_escala"], 60)))
            largura = int(max(40, min(max(bw * 1.25, 90), W - x0 - 2)))
            item = canvas.create_text(x0 + 3, y0 + 1, anchor="nw", text=str(b["t"]), width=largura,
                                      fill=texto_cor, justify="left", font=("Segoe UI", -tam, "bold"))
            limite = bh * 1.6 + b["lh"]
            while tam > 10:  # diminui se ficar alto demais ou passar do fim da área
                cx = canvas.bbox(item)
                if not cx or (cx[3] - cx[1] <= limite and cx[3] <= H - 2):
                    break
                tam -= 1
                canvas.itemconfig(item, font=("Segoe UI", -tam, "bold"))
            cx = canvas.bbox(item)
            if cx and cx[3] > H - 2:  # ainda passa do fim: sobe o texto
                canvas.move(item, 0, (H - 2) - cx[3])
                cx = canvas.bbox(item)
            if cx:  # o fundo cresce até cobrir o texto traduzido
                canvas.coords(ret, min(x0, cx[0] - 3), min(y0, cx[1] - 2),
                              min(W, max(x1, cx[2] + 3)), min(H, max(y1, cx[3] + 2)))
        except Exception:
            traceback.print_exc()
    if not blocos:
        selo(canvas, "(sem texto)")
    if cfg["mostrar_tempo"]:
        t = canvas.create_text(8, H - 4, anchor="sw", text=info, fill="white", font=("Segoe UI", 8))
        cx = canvas.bbox(t)
        if cx:
            canvas.create_rectangle(cx[0] - 3, cx[1] - 1, cx[2] + 3, cx[3] + 1, fill="#222222", outline="")
            canvas.tag_raise(t)


def mostrar_erro(msg):
    canvas = estado["canvas"]
    if not canvas:
        return
    canvas.delete("all")
    canvas.create_rectangle(0, 0, 2000, 260, fill="#330000", outline="")
    canvas.create_text(10, 10, text=msg, fill="white", anchor="nw", width=700, font=("Segoe UI", 10))


# ---------- menu ----------
menu = {"w": None}


def abrir_menu():
    if menu["w"]:
        menu["w"].destroy()
        menu["w"] = None
        return
    w = tk.Toplevel(root)
    w.title("Tradutor - configurações")
    w.attributes("-topmost", True)
    w.resizable(False, False)
    menu["w"] = w

    def fechar():
        w.destroy()
        menu["w"] = None

    w.protocol("WM_DELETE_WINDOW", fechar)
    linha = [0]

    def combo(rotulo, mapa, chave, ao_escolher=None):
        ttk.Label(w, text=rotulo).grid(row=linha[0], column=0, sticky="w", padx=10, pady=4)
        inv = {v: k for k, v in mapa.items()}
        var = tk.StringVar(value=inv.get(cfg[chave], next(iter(mapa))))
        cb = ttk.Combobox(w, textvariable=var, values=list(mapa), state="readonly", width=36)
        cb.grid(row=linha[0], column=1, padx=10, pady=4)

        def mudou(_e=None):
            cfg[chave] = mapa[var.get()]
            if ao_escolher:
                ao_escolher(var.get())
            salvar_config(cfg)

        cb.bind("<<ComboboxSelected>>", mudou)
        linha[0] += 1

    def check(rotulo, chave):
        var = tk.BooleanVar(value=bool(cfg[chave]))

        def mudou():
            cfg[chave] = var.get()
            salvar_config(cfg)

        ttk.Checkbutton(w, text=rotulo, variable=var, command=mudou).grid(
            row=linha[0], column=0, columnspan=2, sticky="w", padx=10, pady=2)
        linha[0] += 1

    combo("Modo", MENU_MODOS, "modo")
    combo("OCR (modo local)", MENU_OCRS, "ocr")
    combo("Tradutor (modo local)", MENU_TRADS, "tradutor")
    combo("Idioma do texto na tela", MENU_ORIGENS, "idioma_origem")
    combo("Traduzir para", MENU_DESTINOS, "destino_codigo",
          ao_escolher=lambda nome: cfg.__setitem__("idioma_destino", nome))

    ttk.Label(w, text="Tamanho da fonte").grid(row=linha[0], column=0, sticky="w", padx=10)
    escala = tk.Scale(w, from_=0.5, to=2.5, resolution=0.05, orient="horizontal", length=260,
                      command=lambda v: cfg.__setitem__("fonte_escala", float(v)))
    escala.set(cfg["fonte_escala"])
    escala.grid(row=linha[0], column=1, padx=10)
    escala.bind("<ButtonRelease-1>", lambda e: salvar_config(cfg))
    linha[0] += 1

    check("Juntar linhas da mesma fala antes de traduzir", "juntar_linhas")
    check("Corrigir português de Portugal para Brasil (Argos/Opus, usa ptbr.json)", "ajustar_ptbr")
    check("Se o tradutor falhar, tentar os outros (deixe desligado p/ medir)", "fallback")
    check("Mostrar no overlay o que foi usado e o tempo", "mostrar_tempo")

    botoes = ttk.Frame(w)
    botoes.grid(row=linha[0], column=0, columnspan=2, pady=6)
    ttk.Button(botoes, text="Escolher área (F9)", command=lambda: fila.put("area")).pack(side="left", padx=4)
    ttk.Button(botoes, text="Fechar", command=fechar).pack(side="left", padx=4)
    linha[0] += 1

    ttk.Label(w, justify="left", wraplength=430, text=(
        "Depois de mudar algo: F8 para fechar o overlay e F8 de novo para traduzir.\n"
        "Meça a 2ª tentativa (a 1ª carrega o OCR/tradutor). Se aparecer (cache), mude a tela.\n"
        "Trocar para Argos/Opus pelo menu: a 1ª tradução demora (carrega o modelo).")).grid(
        row=linha[0], column=0, columnspan=2, padx=10, pady=(0, 10))


# ---------- ações dos atalhos ----------
def alternar():
    if estado["overlay"]:
        estado["req"] += 1  # descarta qualquer resposta que ainda esteja chegando
        fechar_overlay()
        return
    area = area_atual()
    img = capturar(area)
    estado["img"] = img
    estado["req"] += 1
    abrir_overlay(area)
    threading.Thread(target=trabalhar, args=(img, estado["req"]), daemon=True).start()


def configurar_area():
    estado["req"] += 1
    fechar_overlay()
    sel = tk.Toplevel(root)
    sel.attributes("-fullscreen", True)
    sel.attributes("-topmost", True)
    sel.attributes("-alpha", 0.3)
    sel.configure(bg="black", cursor="crosshair")
    canvas = tk.Canvas(sel, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    pos = {}

    def apertou(e):
        pos["x0"], pos["y0"] = e.x_root, e.y_root
        pos["ret"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=3)
        pos["cx0"], pos["cy0"] = e.x, e.y

    def arrastou(e):
        if "ret" in pos:
            canvas.coords(pos["ret"], pos["cx0"], pos["cy0"], e.x, e.y)

    def soltou(e):
        if "x0" not in pos:
            sel.destroy()
            return
        l, t = min(pos["x0"], e.x_root), min(pos["y0"], e.y_root)
        w, h = abs(e.x_root - pos["x0"]), abs(e.y_root - pos["y0"])
        sel.destroy()
        if w > 30 and h > 30:
            cfg["area"] = {"left": l, "top": t, "width": w, "height": h}
            salvar_config(cfg)
            print(f"Área salva: {cfg['area']}")

    canvas.bind("<ButtonPress-1>", apertou)
    canvas.bind("<B1-Motion>", arrastou)
    canvas.bind("<ButtonRelease-1>", soltou)
    sel.bind("<Escape>", lambda e: sel.destroy())
    sel.focus_force()


def processar_fila():
    try:
        while True:
            item = fila.get_nowait()
            try:
                if item == "traduzir":
                    alternar()
                elif item == "area":
                    configurar_area()
                elif item == "menu":
                    abrir_menu()
                else:
                    tipo, req, dado = item
                    if req != estado["req"]:
                        continue  # resposta antiga, ignora
                    if tipo == "resultado":
                        desenhar(dado[0], estado["img"], dado[1])
                    else:
                        mostrar_erro(dado)
            except Exception:
                erro = traceback.format_exc()
                print(erro)
                mostrar_erro("Erro interno:\n" + erro[-600:])
    except queue.Empty:
        pass
    root.after(100, processar_fila)


keyboard.add_hotkey(cfg["tecla_traduzir"], lambda: fila.put("traduzir"), suppress=True)
keyboard.add_hotkey(cfg["tecla_configurar_area"], lambda: fila.put("area"), suppress=True)
keyboard.add_hotkey(cfg["tecla_menu"], lambda: fila.put("menu"), suppress=True)
print(f"Pronto! {cfg['tecla_traduzir'].upper()} = traduzir/fechar | "
      f"{cfg['tecla_configurar_area'].upper()} = escolher área | "
      f"{cfg['tecla_menu'].upper()} = menu | Ctrl+C no terminal para sair")
threading.Thread(target=aquecer, daemon=True).start()
root.after(100, processar_fila)
root.mainloop()