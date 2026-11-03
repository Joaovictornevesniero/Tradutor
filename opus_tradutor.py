"""
Tradutor Opus-MT (Helsinki-NLP/opus-mt-en-ROMANCE) via CTranslate2, EN -> pt-BR.
Offline, sem limite de uso, roda em CPU.

Primeira execução: converte o modelo sozinho para a pasta "opus-en-romance-ct2"
(precisa de internet e de: pip install transformers torch huggingface_hub).
Depois disso só usa ctranslate2 + sentencepiece (que o Argos já instalou).
"""
import os
import re
import threading

REPO = "Helsinki-NLP/opus-mt-en-ROMANCE"
PASTA_PADRAO = "opus-en-romance-ct2"
TOKEN_DESTINO = ">>pt_BR<<"

_lock = threading.Lock()
_est = {"tr": None, "sp_src": None, "sp_tgt": None}


def pronto():
    return _est["tr"] is not None


def _garantir_modelo(pasta):
    if os.path.exists(os.path.join(pasta, "model.bin")):
        return
    print("Opus-MT: convertendo o modelo (só na primeira vez, pode demorar uns minutos)...")
    try:
        from ctranslate2.converters import TransformersConverter
    except ImportError:
        raise RuntimeError("Falta: pip install ctranslate2")
    try:
        TransformersConverter(REPO, copy_files=["source.spm", "target.spm"]).convert(
            pasta, quantization="int8")
    except ImportError:
        raise RuntimeError("Para converter o modelo (uma vez): pip install transformers torch huggingface_hub")
    print("Opus-MT: modelo convertido.")


def _carregar(pasta):
    with _lock:
        if _est["tr"] is not None:
            return
        import ctranslate2
        import sentencepiece as spm
        _garantir_modelo(pasta)
        threads = max(2, (os.cpu_count() or 4) // 2)
        _est["tr"] = ctranslate2.Translator(
            pasta, device="cpu", compute_type="int8", inter_threads=1, intra_threads=threads)
        _est["sp_src"] = spm.SentencePieceProcessor(model_file=os.path.join(pasta, "source.spm"))
        _est["sp_tgt"] = spm.SentencePieceProcessor(model_file=os.path.join(pasta, "target.spm"))


def _eh_caixa_alta(t):
    letras = [c for c in t if c.isalpha()]
    return len(letras) >= 4 and sum(c.isupper() for c in letras) / len(letras) > 0.8


def _normalizar_caixa(t):
    """OCR de jogo costuma vir TUDO EM MAIÚSCULAS e o modelo traduz pior assim."""
    t = t.lower()
    t = re.sub(r"(^|[.!?…]\s+)([a-zà-ú])", lambda m: m.group(1) + m.group(2).upper(), t)
    return re.sub(r"\bi\b", "I", t)  # I, I'm, I'll...


def traduzir(textos, dividir_frases, pasta=None, manter_caixa_alta=False, beam=4):
    """textos: lista de str. dividir_frases: função str -> lista de frases curtas."""
    _carregar(pasta or PASTA_PADRAO)
    tr, sp_src, sp_tgt = _est["tr"], _est["sp_src"], _est["sp_tgt"]

    # monta a lista plana de frases, lembrando de onde cada uma veio
    frases, dono, caixa_alta = [], [], []
    for i, t in enumerate(textos):
        alta = _eh_caixa_alta(t)
        caixa_alta.append(alta)
        base = _normalizar_caixa(t) if alta else t
        for f in dividir_frases(base):
            frases.append(f)
            dono.append(i)

    if not frases:
        return list(textos)

    entradas = [[TOKEN_DESTINO] + sp_src.encode(f, out_type=str) + ["</s>"] for f in frases]
    res = tr.translate_batch(entradas, beam_size=beam, max_decoding_length=256,
                             repetition_penalty=1.1, no_repeat_ngram_size=0)
    saidas = [sp_tgt.decode(r.hypotheses[0]).strip() for r in res]

    final = [[] for _ in textos]
    for i, s in zip(dono, saidas):
        final[i].append(s)
    out = []
    for i, partes in enumerate(final):
        s = " ".join(p for p in partes if p) or textos[i]
        out.append(s.upper() if (caixa_alta[i] and manter_caixa_alta) else s)
    return out
