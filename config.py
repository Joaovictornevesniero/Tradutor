"""Configuração: lê e grava o config.json (só as chaves conhecidas)."""
import json
import os

ARQUIVO = "config.json"

PADRAO = {
    "tecla_traduzir": "f8",          # traduz a área / fecha o overlay
    "tecla_configurar_area": "f9",   # escolher a área da tela
    "tecla_menu": "f10",             # abre o menu de configurações
    "fonte_escala": 1.2,             # tamanho do texto traduzido
    "juntar_linhas": True,           # junta linhas da mesma fala antes de traduzir
    "ajustar_ptbr": True,            # corrige português de Portugal (usa ptbr.json)
    "mostrar_tempo": True,           # mostra tempos no rodapé do overlay
    "tesseract_caminho": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    "tesseract_escala": 1,           # 2 = amplia a imagem (lê texto pequeno melhor, mais lento)
    "area": None,                    # {"left", "top", "width", "height"}
}


def carregar():
    cfg = dict(PADRAO)
    if os.path.exists(ARQUIVO):
        with open(ARQUIVO, encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in PADRAO})
    else:
        salvar(cfg)
    return cfg


def salvar(cfg):
    with open(ARQUIVO, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
