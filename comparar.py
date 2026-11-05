"""
Compara duas ou mais capturas ja analisadas (ex: antes x depois, single core x SMP).
Gera comparacoes/<data>_<A>_x_<B>/comparacao.md (+ comparacao.png). Usado pelo medir.py.

  python comparar.py                                 -> as 2 capturas mais recentes
  python comparar.py capturas/<A> capturas/<B>
"""
import argparse
import glob
import json
import os
import re
from datetime import datetime

import numpy as np

from analisar import AQUI, CORES, fmt_t

METRICAS = [
    ("WCET (largura máx em alto)", "wcet_s", "t"),
    ("Jitter (pico-a-pico)", "jitter_pp_s", "t"),
    ("Jitter (desvio padrão)", "jitter_std_s", "t"),
    ("Deadline Miss Rate", "miss_rate_pct", "%"),
    ("Utilização / Duty", "utilizacao_pct", "%"),
    ("Frequência medida", "frequencia_hz", "hz"),
]


def rotulo(pasta):
    nome = os.path.basename(os.path.normpath(pasta))
    m = re.match(r"\d{8}_\d{6}_(.+)", nome)
    return m.group(1) if m else nome


def carregar(pasta):
    caminho = os.path.join(pasta, "metricas.json")
    if not os.path.exists(caminho):
        raise SystemExit(f"{pasta} ainda não foi analisada (falta metricas.json).")
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def fmt(v, tipo):
    if v is None:
        return "-"
    return fmt_t(v) if tipo == "t" else (f"{v:.2f}%" if tipo == "%" else f"{v:.2f} Hz")


def comparar(pastas, mostrar=False, verbose=True):
    dados = [carregar(p) for p in pastas]
    rots = [rotulo(p) for p in pastas]
    sinais = list(dict.fromkeys(n for d in dados for n in d["tasks"]))

    def val(d, s, key):
        m = d["tasks"].get(s)
        return m.get(key) if m else None

    md = [f"# Comparação: {' x '.join(rots)}", ""]
    for titulo, key, tipo in METRICAS:
        md += [f"### {titulo}", "", "| Sinal | " + " | ".join(rots) + " |", "|---|" + "---|" * len(rots)]
        for s in sinais:
            md.append(f"| {s} | " + " | ".join(fmt(val(d, s, key), tipo) for d in dados) + " |")
        md.append("")
    md += ["### Stack Usage", "", "| Sinal | " + " | ".join(rots) + " |", "|---|" + "---|" * len(rots)]
    for s in sinais:
        cel = []
        for d in dados:
            st = d.get("stack", {}).get(s)
            cel.append(f"{st['usado']}/{st['size']} ({st['pct']:.1f}%)" if st else "-")
        md.append(f"| {s} | " + " | ".join(cel) + " |")
    md += ["", "![comparacao](comparacao.png)", ""]
    md = "\n".join(md)

    saida = os.path.join(AQUI, "comparacoes", datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + "_x_".join(rots))
    os.makedirs(saida, exist_ok=True)

    import matplotlib
    if not mostrar:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    paineis = [("WCET (us)", "wcet_s", 1e6), ("Jitter pico-a-pico (us)", "jitter_pp_s", 1e6),
               ("Utilização / Duty (%)", "utilizacao_pct", 1), ("Deadline Miss Rate (%)", "miss_rate_pct", 1)]
    fig, axs = plt.subplots(2, 2, figsize=(13, 7.5))
    x = np.arange(len(sinais))
    w = 0.8 / len(dados)
    for a, (titulo, key, fat) in zip(axs.ravel(), paineis):
        for j, (d, r) in enumerate(zip(dados, rots)):
            ys = [(val(d, s, key) or 0) * fat for s in sinais]
            b = a.bar(x + (j - (len(dados) - 1) / 2) * w, ys, w, label=r, color=CORES[j % len(CORES)])
            a.bar_label(b, fmt="%.1f", fontsize=7)
        a.set_xticks(x, sinais, rotation=15)
        a.set_title(titulo)
        a.margins(y=0.2)
        a.legend(fontsize=8)
    fig.suptitle("Comparação: " + " x ".join(rots))
    fig.tight_layout()
    fig.savefig(os.path.join(saida, "comparacao.png"), dpi=130)
    if mostrar:
        plt.show()
    plt.close("all")

    with open(os.path.join(saida, "comparacao.md"), "w", encoding="utf-8") as f:
        f.write(md)
    if verbose:
        print(md)
        print(f"Salvo em: {saida}")
    return saida


def main():
    ap = argparse.ArgumentParser(description="Compara capturas analisadas.")
    ap.add_argument("pastas", nargs="*", help="pastas de captura (padrão: as 2 mais recentes)")
    ap.add_argument("--sem-grafico", action="store_true")
    args = ap.parse_args()

    pastas = args.pastas
    if not pastas:
        todas = sorted((p for p in glob.glob(os.path.join(AQUI, "capturas", "*")) if os.path.isdir(p)),
                       key=os.path.getmtime)
        if len(todas) < 2:
            raise SystemExit("Preciso de pelo menos 2 capturas em capturas/.")
        pastas = todas[-2:]
    comparar(pastas, mostrar=not args.sem_grafico)


if __name__ == "__main__":
    main()
