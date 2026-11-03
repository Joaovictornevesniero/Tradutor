"""Tradução inglês -> português do Brasil.

Opus-MT (Helsinki-NLP/opus-mt-en-ROMANCE) via CTranslate2, offline e em CPU,
seguido de uma correção de português de Portugal usando o ptbr.json.

Na 1ª execução, se a pasta do modelo não existir, converte sozinho
(precisa de internet e de: pip install transformers torch huggingface_hub).
"""
import json
import os
import re
import threading

REPO = "Helsinki-NLP/opus-mt-en-ROMANCE"
PASTA_MODELO = "opus-en-romance-ct2"
TOKEN_DESTINO = ">>pt_BR<<"
ARQ_PTBR = "ptbr.json"

_lock = threading.Lock()
_modelo = {}


# ---------- modelo ----------
def _converter_se_preciso():
    if os.path.exists(os.path.join(PASTA_MODELO, "model.bin")):
        return
    print("Opus-MT: convertendo o modelo (só na primeira vez, demora uns minutos)...")
    try:
        from ctranslate2.converters import TransformersConverter
        TransformersConverter(REPO, copy_files=["source.spm", "target.spm"]).convert(
            PASTA_MODELO, quantization="int8")
    except ImportError:
        raise RuntimeError("Para converter o modelo (uma vez): pip install transformers torch huggingface_hub")


def _carregar():
    with _lock:
        if _modelo:
            return
        import ctranslate2
        import sentencepiece as spm
        _converter_se_preciso()
        threads = max(2, (os.cpu_count() or 4) // 2)
        _modelo["tr"] = ctranslate2.Translator(
            PASTA_MODELO, device="cpu", compute_type="int8", inter_threads=1, intra_threads=threads)
        _modelo["src"] = spm.SentencePieceProcessor(model_file=os.path.join(PASTA_MODELO, "source.spm"))
        _modelo["tgt"] = spm.SentencePieceProcessor(model_file=os.path.join(PASTA_MODELO, "target.spm"))


def aquecer():
    """Carrega o modelo antes do primeiro uso."""
    _carregar()
    traduzir(["Hello"], ajustar=False)


# ---------- pré-processamento ----------
def _eh_caixa_alta(t):
    letras = [c for c in t if c.isalpha()]
    return len(letras) >= 4 and sum(c.isupper() for c in letras) / len(letras) > 0.8


def _normalizar_caixa(t):
    """Texto TODO EM MAIÚSCULAS é traduzido pior: converte para frase normal."""
    t = t.lower()
    t = re.sub(r"(^|[.!?…]\s+)([a-zà-ú])", lambda m: m.group(1) + m.group(2).upper(), t)
    return re.sub(r"\bi\b", "I", t)


def dividir_frases(t):
    """Quebra em frases curtas: o modelo perde palavras quando recebe trecho muito longo."""
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


# ---------- português de Portugal -> Brasil ----------
_ptbr = {"mtime": None, "palavras": {}, "padrao": None, "regex": []}
_GERUNDIO = {"ar": "ando", "er": "endo", "ir": "indo"}


def _carregar_ptbr():
    """Lê o ptbr.json; recarrega sozinho quando o arquivo muda."""
    try:
        m = os.path.getmtime(ARQ_PTBR)
    except OSError:
        return
    if m == _ptbr["mtime"]:
        return
    _ptbr["mtime"] = m
    try:
        with open(ARQ_PTBR, encoding="utf-8") as f:
            d = json.load(f)
        pal = {k.lower(): v for k, v in d.get("palavras", {}).items()}
        _ptbr["palavras"] = pal
        _ptbr["padrao"] = re.compile(
            r"\b(" + "|".join(re.escape(k) for k in sorted(pal, key=len, reverse=True)) + r")\b",
            re.I) if pal else None
        _ptbr["regex"] = [(re.compile(k, re.I), v) for k, v in d.get("regex", {}).items()]
        print(f"ptbr.json carregado: {len(pal)} palavras, {len(_ptbr['regex'])} regras")
    except Exception as e:
        print(f"ptbr.json com erro: {e}")


def ajustar_ptbr(t):
    _carregar_ptbr()
    # "estou a fazer" -> "estou fazendo"
    t = re.sub(r"\b(estou|está|estamos|estão|estava|estavam|esteve|fico|ficou|continua|continuo|continuam) a (\w+?)(ar|er|ir)\b",
               lambda m: f"{m.group(1)} {m.group(2)}{_GERUNDIO[m.group(3)]}", t, flags=re.I)

    # "diz-me" -> "me diz"
    def clitico(m):
        verbo, pron = m.group(1), m.group(2).lower()
        if verbo[0].isupper():
            return pron.capitalize() + " " + verbo[0].lower() + verbo[1:]
        return pron + " " + verbo

    t = re.sub(r"\b(\w+)-(me|te|se|lhe|lhes|nos)\b", clitico, t)
    for rx, v in _ptbr["regex"]:
        t = rx.sub(v, t)
    if _ptbr["padrao"]:
        def troca(m):
            novo = _ptbr["palavras"][m.group(0).lower()]
            return novo[0].upper() + novo[1:] if m.group(0)[0].isupper() else novo

        t = _ptbr["padrao"].sub(troca, t)
    return re.sub(r"\b(você) \1\b", r"\1", t, flags=re.I)  # "tu estás" -> "você está"


# ---------- API ----------
def traduzir(textos, ajustar=True):
    """Recebe lista de textos em inglês, devolve lista em português do Brasil."""
    _carregar()
    tr, sp_src, sp_tgt = _modelo["tr"], _modelo["src"], _modelo["tgt"]

    frases, dono = [], []  # lista plana de frases + de qual texto cada uma veio
    for i, t in enumerate(textos):
        base = _normalizar_caixa(t) if _eh_caixa_alta(t) else t
        for f in dividir_frases(base):
            frases.append(f)
            dono.append(i)
    if not frases:
        return list(textos)

    entradas = [[TOKEN_DESTINO] + sp_src.encode(f, out_type=str) + ["</s>"] for f in frases]
    res = tr.translate_batch(entradas, beam_size=4, max_decoding_length=256,
                             repetition_penalty=1.1, no_repeat_ngram_size=0)
    partes = [[] for _ in textos]
    for i, r in zip(dono, res):
        partes[i].append(sp_tgt.decode(r.hypotheses[0]).strip())

    saida = [" ".join(p for p in ps if p) or textos[i] for i, ps in enumerate(partes)]
    return [ajustar_ptbr(s) for s in saida] if ajustar else saida
