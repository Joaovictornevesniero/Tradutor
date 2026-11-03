"""
Tradutor de tela (inglês -> português do Brasil), offline.
  F8 = traduz a área e cobre o texto original / F8 de novo = remove
  F9 = escolher a área da tela
  F10 = menu (trocar atalhos, fonte e opções)

Arquivos: tradutor.py, config.py, ocr.py, traducao.py, overlay.py, menu.py, ptbr.json
          + pasta opus-en-romance-ct2 (modelo; é criada sozinha na 1ª vez)

Instalar:
  pip install mss pillow keyboard pytesseract ctranslate2 sentencepiece
  + programa Tesseract: github.com/UB-Mannheim/tesseract/wiki
  (só na 1ª vez, para converter o modelo: pip install transformers torch huggingface_hub)
"""
import ctypes
import hashlib
import os
import queue
import sys
import threading
import time
import traceback
import tkinter as tk

os.chdir(os.path.dirname(os.path.abspath(__file__)))  # caminhos relativos sempre na pasta do script


# ---------- log: o que aparece no terminal também vai para log.txt ----------
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

import keyboard  # noqa: E402
import mss  # noqa: E402
from PIL import Image  # noqa: E402

import config  # noqa: E402
import ocr  # noqa: E402
import traducao  # noqa: E402
from menu import Menu  # noqa: E402
from overlay import Overlay, escolher_area  # noqa: E402

MSS = getattr(mss, "MSS", None) or mss.mss
cfg = config.carregar()
root = tk.Tk()
root.withdraw()
overlay = Overlay(root, cfg)
fila = queue.Queue()          # comandos das teclas e resultados das threads, lidos na thread do Tk
estado = {"img": None, "req": 0}
cache = {}


# ---------- captura e processamento ----------
def area_atual():
    if cfg["area"]:
        return cfg["area"]
    with MSS() as sct:
        return dict(sct.monitors[1])


def capturar(area):
    with MSS() as sct:
        shot = sct.grab(area)
        return Image.frombytes("RGB", shot.size, shot.rgb)


def processar(img):
    chave = hashlib.md5(img.tobytes()).hexdigest()
    if chave in cache:
        blocos, info = cache[chave]
        return blocos, info + " (cache)"

    ini = time.time()
    linhas = ocr.ler(img, cfg)
    t_ocr = time.time() - ini
    print(f"OCR: {len(linhas)} linhas em {t_ocr:.1f}s")
    if not linhas:
        return [], f"ocr {t_ocr:.1f}s: nenhum texto lido"

    blocos = ocr.agrupar(linhas, cfg["juntar_linhas"])
    ini2 = time.time()
    traduzidos = traducao.traduzir([b["t"] for b in blocos], cfg["ajustar_ptbr"])
    for b, t in zip(blocos, traduzidos):
        print(f"  ORIGINAL: {b['t']}\n  TRADUÇÃO: {t}")  # para ver onde o OCR erra
        b["t"] = t

    info = f"ocr {t_ocr:.1f}s + tradução {time.time() - ini2:.1f}s | total {time.time() - ini:.1f}s"
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
    """Carrega o modelo em segundo plano para o primeiro F8 não pagar esse custo."""
    try:
        ini = time.time()
        traducao.aquecer()
        print(f"Aquecimento pronto em {time.time() - ini:.1f}s")
    except Exception as e:
        print(f"Aquecimento falhou: {e}")


# ---------- ações dos atalhos ----------
def alternar():
    estado["req"] += 1  # descarta qualquer resposta que ainda esteja chegando
    if overlay.aberto:
        overlay.fechar()
        return
    area = area_atual()
    estado["img"] = capturar(area)
    overlay.abrir(area)
    threading.Thread(target=trabalhar, args=(estado["img"], estado["req"]), daemon=True).start()


def configurar_area():
    estado["req"] += 1
    overlay.fechar()

    def salvar(area):
        cfg["area"] = area
        config.salvar(cfg)
        print(f"Área salva: {area}")

    escolher_area(root, salvar)


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
                    menu.alternar()
                elif item[0] == "tecla":
                    menu.tecla_capturada(item[1], item[2])
                else:
                    tipo, req, dado = item
                    if req != estado["req"]:
                        continue  # resposta antiga, ignora
                    if tipo == "resultado":
                        overlay.desenhar(dado[0], estado["img"], dado[1])
                    else:
                        overlay.erro(dado)
            except Exception:
                erro = traceback.format_exc()
                print(erro)
                overlay.erro("Erro interno:\n" + erro[-600:])
    except queue.Empty:
        pass
    root.after(100, processar_fila)


def desligar_teclas():
    try:
        keyboard.unhook_all_hotkeys()
    except AttributeError:
        pass  # a lib ainda não iniciou (nenhum atalho registrado): nada para remover


def registrar_teclas():
    """(Re)registra os atalhos atuais do config."""
    desligar_teclas()
    for chave, acao in (("tecla_traduzir", "traduzir"), ("tecla_configurar_area", "area"),
                        ("tecla_menu", "menu")):
        try:
            keyboard.add_hotkey(cfg[chave], lambda a=acao: fila.put(a), suppress=True)
        except Exception as e:
            print(f"Atalho inválido em {chave} ({cfg[chave]!r}): {e}")
    print(f"Atalhos: {cfg['tecla_traduzir'].upper()} = traduzir/fechar | "
          f"{cfg['tecla_configurar_area'].upper()} = escolher área | "
          f"{cfg['tecla_menu'].upper()} = menu")


menu = Menu(root, cfg, fila, desligar_teclas=desligar_teclas,
            ao_mudar_teclas=registrar_teclas, ao_mudar_opcoes=cache.clear)
registrar_teclas()
print("Pronto! Ctrl+C no terminal para sair")
threading.Thread(target=aquecer, daemon=True).start()
root.after(100, processar_fila)
root.mainloop()
