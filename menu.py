"""Menu de configurações (F10): troca de atalhos e opções simples."""
import threading
import tkinter as tk
from tkinter import ttk

import keyboard

import config

NOMES_TECLAS = {
    "tecla_traduzir": "Traduzir / fechar",
    "tecla_configurar_area": "Escolher área",
    "tecla_menu": "Abrir este menu",
}

OPCOES = {
    "juntar_linhas": "Juntar linhas da mesma fala antes de traduzir",
    "ajustar_ptbr": "Corrigir português de Portugal para Brasil (ptbr.json)",
    "mostrar_tempo": "Mostrar o tempo no rodapé do overlay",
}


class Menu:
    def __init__(self, root, cfg, fila, desligar_teclas, ao_mudar_teclas, ao_mudar_opcoes):
        self.root, self.cfg, self.fila = root, cfg, fila
        self.desligar_teclas = desligar_teclas
        self.ao_mudar_teclas, self.ao_mudar_opcoes = ao_mudar_teclas, ao_mudar_opcoes
        self.win = None
        self.textos = {}  # StringVar de cada botão de atalho

    def alternar(self):
        if self.win:
            self._fechar()
        else:
            self._abrir()

    def _fechar(self):
        if self.win:
            self.win.destroy()
        self.win = None

    def _abrir(self):
        w = self.win = tk.Toplevel(self.root)
        w.title("Tradutor - configurações")
        w.attributes("-topmost", True)
        w.resizable(False, False)
        w.protocol("WM_DELETE_WINDOW", self._fechar)

        ttk.Label(w, text="Atalhos (clique e aperte a nova tecla):", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 4))
        linha = 1
        for chave, nome in NOMES_TECLAS.items():
            ttk.Label(w, text=nome).grid(row=linha, column=0, sticky="w", padx=10, pady=3)
            var = self.textos[chave] = tk.StringVar(value=self.cfg[chave].upper())
            ttk.Button(w, textvariable=var, width=34,
                       command=lambda c=chave: self._capturar(c)).grid(row=linha, column=1, padx=10, pady=3)
            linha += 1

        ttk.Label(w, text="Tamanho da fonte").grid(row=linha, column=0, sticky="w", padx=10, pady=(10, 0))
        escala = tk.Scale(w, from_=0.5, to=2.5, resolution=0.05, orient="horizontal", length=240,
                          command=lambda v: self.cfg.__setitem__("fonte_escala", float(v)))
        escala.set(self.cfg["fonte_escala"])
        escala.grid(row=linha, column=1, padx=10, pady=(10, 0))
        escala.bind("<ButtonRelease-1>", lambda e: self._salvar_opcoes())
        linha += 1

        for chave, rotulo in OPCOES.items():
            var = tk.BooleanVar(value=bool(self.cfg[chave]))

            def mudou(c=chave, v=var):
                self.cfg[c] = v.get()
                self._salvar_opcoes()

            ttk.Checkbutton(w, text=rotulo, variable=var, command=mudou).grid(
                row=linha, column=0, columnspan=2, sticky="w", padx=10, pady=2)
            linha += 1

        ttk.Button(w, text="Fechar", command=self._fechar).grid(row=linha, column=0, columnspan=2, pady=10)

    def _salvar_opcoes(self):
        config.salvar(self.cfg)
        self.ao_mudar_opcoes()

    # ---------- troca de atalho ----------
    def _capturar(self, chave):
        self.desligar_teclas()  # senão apertar F8 etc. dispararia a ação em vez de ser lido
        self.textos[chave].set("Aperte a nova tecla... (Esc cancela)")

        def ler():
            try:
                combo = keyboard.read_hotkey(suppress=False)
            except Exception:
                combo = None
            self.fila.put(("tecla", chave, combo))

        threading.Thread(target=ler, daemon=True).start()

    def tecla_capturada(self, chave, combo):
        """Chamado pela thread do Tk quando a tecla foi lida."""
        if combo and combo != "esc":
            repetida = [n for c, n in NOMES_TECLAS.items() if c != chave and self.cfg[c] == combo]
            if repetida:
                print(f"Atalho {combo.upper()} já é usado em '{repetida[0]}'")
            else:
                self.cfg[chave] = combo
                config.salvar(self.cfg)
        self.textos[chave].set(self.cfg[chave].upper())
        self.ao_mudar_teclas()  # registra tudo de novo (foi desligado na captura)
