"""Interface na tela: overlay transparente com a tradução e seletor de área."""
import tkinter as tk
import traceback

TRANSPARENTE = "#010101"
FONTE = "Segoe UI"


class Overlay:
    def __init__(self, root, cfg):
        self.root, self.cfg = root, cfg
        self.win = self.canvas = None

    @property
    def aberto(self):
        return self.win is not None

    def abrir(self, area):
        w, h = area["width"], area["height"]
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", TRANSPARENTE)
        self.win.geometry(f"{w}x{h}+{area['left']}+{area['top']}")
        self.win.configure(bg=TRANSPARENTE)
        self.canvas = tk.Canvas(self.win, bg=TRANSPARENTE, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", lambda e: self.fechar())  # clique fecha
        self._selo("Traduzindo...")

    def fechar(self):
        if self.win:
            self.win.destroy()
        self.win = self.canvas = None

    def _selo(self, texto):
        self.canvas.delete("all")
        self.canvas.create_rectangle(4, 4, 150, 30, fill="#222222", outline="")
        self.canvas.create_text(77, 17, text=texto, fill="white", font=(FONTE, 10, "bold"))

    def erro(self, msg):
        if not self.canvas:
            return
        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, 2000, 260, fill="#330000", outline="")
        self.canvas.create_text(10, 10, text=msg, fill="white", anchor="nw", width=700, font=(FONTE, 10))

    def desenhar(self, blocos, img, info):
        canvas = self.canvas
        if not canvas:
            return
        canvas.delete("all")
        for b in blocos:
            try:
                self._desenhar_bloco(b, img)
            except Exception:
                traceback.print_exc()
        if not blocos:
            self._selo("(sem texto)")
        if self.cfg["mostrar_tempo"]:
            t = canvas.create_text(8, img.height - 4, anchor="sw", text=info, fill="white", font=(FONTE, 8))
            cx = canvas.bbox(t)
            if cx:
                canvas.create_rectangle(cx[0] - 3, cx[1] - 1, cx[2] + 3, cx[3] + 1, fill="#222222", outline="")
                canvas.tag_raise(t)

    def _desenhar_bloco(self, b, img):
        """Cobre o texto original com a cor do fundo e escreve a tradução por cima."""
        canvas, W, H = self.canvas, img.width, img.height
        x0, y0, x1, y1 = b["box"]
        x0, y0, x1, y1 = max(0, x0 - 3), max(0, y0 - 2), min(W, x1 + 3), min(H, y1 + 2)
        bw, bh = x1 - x0, y1 - y0
        if bw < 6 or bh < 6:
            return
        r, g, bl = _cor_dominante(img, (x0, y0, x1, y1))[:3]
        texto_cor = "#000000" if (0.299 * r + 0.587 * g + 0.114 * bl) > 140 else "#ffffff"
        fundo = canvas.create_rectangle(x0, y0, x1, y1, fill="#%02x%02x%02x" % (r, g, bl), outline="")

        tam = int(max(10, min(b["lh"] * 0.9 * self.cfg["fonte_escala"], 60)))
        largura = int(max(40, min(max(bw * 1.25, 90), W - x0 - 2)))
        item = canvas.create_text(x0 + 3, y0 + 1, anchor="nw", text=b["t"], width=largura,
                                  fill=texto_cor, justify="left", font=(FONTE, -tam, "bold"))
        limite = bh * 1.6 + b["lh"]
        while tam > 10:  # diminui se ficar alto demais ou passar do fim da área
            cx = canvas.bbox(item)
            if not cx or (cx[3] - cx[1] <= limite and cx[3] <= H - 2):
                break
            tam -= 1
            canvas.itemconfig(item, font=(FONTE, -tam, "bold"))
        cx = canvas.bbox(item)
        if cx and cx[3] > H - 2:  # ainda passa do fim: sobe o texto
            canvas.move(item, 0, (H - 2) - cx[3])
            cx = canvas.bbox(item)
        if cx:  # o fundo cresce até cobrir a tradução
            canvas.coords(fundo, min(x0, cx[0] - 3), min(y0, cx[1] - 2),
                          min(W, max(x1, cx[2] + 3)), min(H, max(y1, cx[3] + 2)))


def _cor_dominante(img, caixa):
    trecho = img.crop(caixa).resize((24, 24))
    cores = trecho.getcolors(576) or [(1, (0, 0, 0))]
    return sorted(cores, reverse=True)[0][1]


def escolher_area(root, ao_escolher):
    """Tela escurecida onde o usuário arrasta o retângulo. Chama ao_escolher({left,top,width,height})."""
    sel = tk.Toplevel(root)
    sel.attributes("-fullscreen", True)
    sel.attributes("-topmost", True)
    sel.attributes("-alpha", 0.3)
    sel.configure(bg="black", cursor="crosshair")
    canvas = tk.Canvas(sel, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    pos = {}

    def apertou(e):
        pos.update(x0=e.x_root, y0=e.y_root, cx0=e.x, cy0=e.y,
                   ret=canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=3))

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
            ao_escolher({"left": l, "top": t, "width": w, "height": h})

    canvas.bind("<ButtonPress-1>", apertou)
    canvas.bind("<B1-Motion>", arrastou)
    canvas.bind("<ButtonRelease-1>", soltou)
    sel.bind("<Escape>", lambda e: sel.destroy())
    sel.focus_force()
