"""
Le uma captura (digital.csv exportado pelo Logic 2) e calcula, por task:
  WCET, jitter, deadline miss rate, utilizacao e (se houver stack.txt) stack usage.
Salva metricas.md / metricas.json e os graficos escolhidos (PNG) na pasta da captura.

Uso:
  python analisar.py                          -> captura mais recente em capturas/
  python analisar.py capturas/<pasta>         -> uma captura especifica
  python analisar.py meu_export.csv           -> CSV exportado manualmente pelo Logic 2
  python analisar.py <pasta> --stack log.txt  -> usa um log serial de stack
  python analisar.py <pasta> --graficos timeline,resumo --sem-grafico
"""
import argparse
import csv
import glob
import json
import math
import os
import re
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG_PADRAO = os.path.join(AQUI, "config.json")
NOMES_CONFIG = ("config.json", "config_tasks.json")  # o segundo e o nome antigo
GRAFICOS_DISPONIVEIS = ["timeline", "execucao", "periodo", "jitter", "resumo"]
CORES = ["#2a78b8", "#e8711a", "#2e9e4a", "#d03a3a", "#8a5cc2", "#8c564b", "#d062b0", "#6b6b6b"]


# ----------------------------------------------------------------- config
def carregar_config(caminho):
    with open(caminho, encoding="utf-8") as f:
        cfg = json.load(f)
    # a lista de sinais pode se chamar "sinais" (atual) ou "tasks" (antigo)
    cfg["tasks"] = cfg.get("sinais") or cfg.get("tasks") or []
    if not cfg["tasks"]:
        raise SystemExit(f"Nenhum sinal configurado em {caminho} (lista 'sinais').")
    # compatibilidade com o formato antigo (chaves soltas no topo)
    cfg.setdefault("captura", {
        "porta_automation": cfg.get("porta_automation", 10430),
        "sample_rate_hz": cfg.get("sample_rate_hz", 10_000_000),
        "duracao_s": cfg.get("duracao_s", 10),
    })
    an = cfg.setdefault("analise", {})
    an.setdefault("tolerancia_periodo", cfg.get("tolerancia_periodo", 0.10))
    an.setdefault("graficos", GRAFICOS_DISPONIVEIS)
    an.setdefault("timeline_janela_ms", None)

    nomes, canais = set(), set()
    for t in cfg["tasks"]:
        if "nome" not in t or "canal" not in t:
            raise SystemExit(f"Sinal sem 'nome' ou 'canal' na config: {t}")
        if t["nome"] in nomes or t["canal"] in canais:
            raise SystemExit(f"Nome ou canal repetido na config: {t['nome']} / canal {t['canal']}")
        nomes.add(t["nome"]); canais.add(t["canal"])
    return cfg


# ----------------------------------------------------------------- leitura
def ler_digital_csv(caminho):
    """CSV do Logic 2: 'Time [s]',Channel 0,Channel 1,... (uma linha por transicao)."""
    with open(caminho, newline="", encoding="utf-8-sig") as f:
        r = csv.reader(f)
        header = next(r)
        dados = np.array([[float(x) for x in row] for row in r if row], dtype=float)
    if dados.ndim != 2 or len(dados) == 0:
        raise SystemExit(f"CSV vazio: {caminho}")
    return dados[:, 0], dados[:, 1:], header[1:]


def coluna_do_canal(header, canal):
    for i, nome in enumerate(header):
        m = re.search(r"(\d+)\s*$", nome.strip())
        if m and int(m.group(1)) == canal:
            return i
    return None


def ler_stack(caminho):
    """Linhas do firmware no formato:  [STACK] task_btn hwm=123 size=1024   (em words)."""
    res = {}
    if not caminho or not os.path.exists(caminho):
        return res
    pat = re.compile(r"\[STACK\]\s+(\S+)\s+hwm=(\d+)\s+size=(\d+)")
    with open(caminho, encoding="utf-8", errors="ignore") as f:
        for linha in f:
            m = pat.search(linha)
            if not m:
                continue
            nome, hwm, size = m.group(1), int(m.group(2)), int(m.group(3))
            usado = size - hwm
            if nome not in res or usado > res[nome]["usado"]:
                res[nome] = {"usado": usado, "size": size, "hwm": hwm, "pct": 100.0 * usado / size}
    return res


# ----------------------------------------------------------------- metricas
def bordas(t, v):
    d = np.diff(v)
    sobe = t[1:][d > 0]
    desce = t[1:][d < 0]
    if len(sobe) and len(desce) and desce[0] < sobe[0]:
        desce = desce[1:]
    n = min(len(sobe), len(desce))
    return sobe, sobe[:n], desce[:n]


def metricas_task(t, v, task, tol, duracao):
    sobe_all, sobe, desce = bordas(t, v)
    if len(sobe_all) < 3 or len(desce) < 2:
        return None
    execu = desce - sobe                     # tempo com o pino em 1 (inclui preempcao)
    per = np.diff(sobe_all)                  # intervalo entre ativacoes (subida -> subida)

    T = task["periodo_ms"] / 1e3 if task.get("periodo_ms") else float(np.median(per))
    D = task["deadline_ms"] / 1e3 if task.get("deadline_ms") else T

    k = np.rint(per / T).astype(int)
    perdidas = int(np.sum(np.maximum(k - 1, 0)))                # ativacoes que nao aconteceram
    atrasadas = int(np.sum((k <= 1) & (per > T * (1 + tol))))  # ativacao atrasada alem da tolerancia
    estouro = int(np.sum(execu > D))                            # execucao maior que o deadline
    total = len(sobe_all) + perdidas
    misses = perdidas + atrasadas + estouro

    return {
        "n_ativacoes": int(len(sobe_all)),
        "periodo_nominal_s": T,
        "deadline_s": D,
        "periodo_auto": not task.get("periodo_ms"),
        "wcet_s": float(execu.max()),
        "bcet_s": float(execu.min()),
        "exec_media_s": float(execu.mean()),
        "periodo_medio_s": float(per.mean()),
        "periodo_min_s": float(per.min()),
        "periodo_max_s": float(per.max()),
        "frequencia_hz": float(1.0 / per.mean()),
        "jitter_pp_s": float(per.max() - per.min()),
        "jitter_std_s": float(per.std()),
        "jitter_max_desvio_s": float(np.max(np.abs(per - T))),
        "miss_rate_pct": 100.0 * misses / total,
        "miss_detalhe": {"estouro_exec": estouro, "atrasadas": atrasadas, "perdidas": perdidas, "total": total},
        "utilizacao_pct": 100.0 * execu.sum() / duracao,
        "_execu": execu, "_per": per, "_sobe": sobe,
    }


def fmt_t(s):
    if s is None:
        return "-"
    a = abs(s)
    if a >= 1:
        return f"{s:.3f} s"
    if a >= 1e-3:
        return f"{s*1e3:.3f} ms"
    return f"{s*1e6:.1f} us"


def unidade(s_max):
    """Escolhe a unidade de tempo para um eixo de grafico."""
    if s_max >= 1:
        return 1.0, "s"
    if s_max >= 1e-3:
        return 1e3, "ms"
    return 1e6, "us"


# ----------------------------------------------------------------- tabela
def tabela_md(nomes, M, stack, titulo):
    def linha(rotulo, f):
        return "| " + rotulo + " | " + " | ".join(f(M.get(n), n) for n in nomes) + " |"

    def stk(m, n):
        s = stack.get(n)
        return f"{s['usado']}/{s['size']} words ({s['pct']:.1f}%)" if s else "-"

    def miss(m, n):
        if not m:
            return "-"
        d = m["miss_detalhe"]
        return f"{m['miss_rate_pct']:.2f}% ({d['estouro_exec']+d['atrasadas']+d['perdidas']}/{d['total']})"

    g = lambda key: (lambda m, n: fmt_t(m[key]) if m else "-")
    cab = "| Métrica / Sinal | " + " | ".join(nomes) + " |"
    sep = "|---|" + "---|" * len(nomes)
    return "\n".join([
        f"### {titulo}", "", cab, sep,
        linha("WCET", g("wcet_s")),
        linha("Jitter (pico-a-pico do período)", g("jitter_pp_s")),
        linha("Deadline Miss Rate", miss),
        linha("Stack Usage", stk),
        "", "Detalhes:", "",
        cab.replace("Métrica", "Extra"), sep,
        linha("Período nominal (T)", lambda m, n: (fmt_t(m["periodo_nominal_s"]) + (" (auto)" if m["periodo_auto"] else "")) if m else "-"),
        linha("Deadline (D)", g("deadline_s")),
        linha("Frequência medida", lambda m, n: f"{m['frequencia_hz']:.2f} Hz" if m else "-"),
        linha("Período min / max", lambda m, n: f"{fmt_t(m['periodo_min_s'])} / {fmt_t(m['periodo_max_s'])}" if m else "-"),
        linha("Jitter (desvio padrão)", g("jitter_std_s")),
        linha("Jitter (máx. desvio de T)", g("jitter_max_desvio_s")),
        linha("BCET", g("bcet_s")),
        linha("Exec. média", g("exec_media_s")),
        linha("Utilização CPU", lambda m, n: f"{m['utilizacao_pct']:.2f}%" if m else "-"),
        linha("Nº ativações", lambda m, n: str(m["n_ativacoes"]) if m else "-"),
        "",
        "> Execução (WCET/BCET) = tempo com o sinal em nível alto (subida -> descida). Numa task RTOS inclui preempção.",
        "> Jitter = variação do intervalo entre bordas de subida consecutivas (ativação -> ativação).",
        "> Deadline miss = execução > D, ou ativação atrasada além da tolerância, ou ativação perdida.",
        "",
    ])


# ----------------------------------------------------------------- graficos
def _grade(plt, n, largura=13, altura_linha=2.8):
    cols = 1 if n == 1 else 2
    rows = math.ceil(n / cols)
    fig, axs = plt.subplots(rows, cols, figsize=(largura, altura_linha * rows + 0.6), squeeze=False)
    axs = axs.ravel()
    for a in axs[n:]:
        a.axis("off")
    return fig, axs


def g_timeline(plt, ctx):
    t, V, cols, tasks, M, an = ctx["t"], ctx["V"], ctx["cols"], ctx["tasks"], ctx["M"], ctx["an"]
    if an.get("timeline_janela_ms"):
        janela = an["timeline_janela_ms"] / 1e3
    else:
        Ts = [M[x["nome"]]["periodo_nominal_s"] for x in tasks if M.get(x["nome"])]
        janela = 3 * max(Ts) if Ts else 0.1
    # comeca um pouco antes da primeira ativacao de qualquer task
    subidas = [M[x["nome"]]["_sobe"][0] for x in tasks if M.get(x["nome"])]
    t0 = max(min(subidas) - janela * 0.05, t[0]) if subidas else max(t[0], 0.0)
    fat, un = unidade(janela)

    fig, ax = plt.subplots(figsize=(13, 0.9 * len(tasks) + 1.4))
    for i, (task, c) in enumerate(zip(tasks, cols)):
        if c is None:
            continue
        sel = (t >= t0) & (t <= t0 + janela)
        tt = np.concatenate([[t0], t[sel], [t0 + janela]])
        idx = np.clip(np.searchsorted(t, tt, side="right") - 1, 0, len(t) - 1)
        y = (len(tasks) - 1 - i) * 1.5
        ax.step((tt - t0) * fat, y + V[idx, c], where="post", color=CORES[i % len(CORES)], lw=1.3)
        ax.text(-0.01, y + 0.5, f"{task['nome']} (ch{task['canal']})", ha="right", va="center",
                fontsize=9, transform=ax.get_yaxis_transform())
    ax.set_yticks([])
    ax.set_xlabel(f"tempo ({un})")
    ax.set_xlim(0, janela * fat)
    ax.set_title("Timeline das tasks (nível alto = task executando)")
    fig.tight_layout()
    return fig


def g_execucao(plt, ctx):
    tasks, M = ctx["tasks"], ctx["M"]
    fig, axs = _grade(plt, len(tasks))
    for i, task in enumerate(tasks):
        a, m = axs[i], M.get(task["nome"])
        if not m:
            a.text(0.5, 0.5, f"{task['nome']}: sem sinal", ha="center", transform=a.transAxes); continue
        fat, un = unidade(m["wcet_s"])
        a.hist(m["_execu"] * fat, bins=60, color=CORES[i % len(CORES)], alpha=0.85)
        a.axvline(m["wcet_s"] * fat, color="k", ls="--", lw=1, label=f"WCET {fmt_t(m['wcet_s'])}")
        a.set_title(f"{task['nome']} - tempo de execução")
        a.set_xlabel(un); a.set_ylabel("ocorrências"); a.legend(fontsize=8)
    fig.tight_layout()
    return fig


def g_periodo(plt, ctx):
    tasks, M = ctx["tasks"], ctx["M"]
    fig, axs = _grade(plt, len(tasks))
    for i, task in enumerate(tasks):
        a, m = axs[i], M.get(task["nome"])
        if not m:
            a.text(0.5, 0.5, f"{task['nome']}: sem sinal", ha="center", transform=a.transAxes); continue
        fat, un = unidade(m["periodo_nominal_s"])
        per, T = m["_per"] * fat, m["periodo_nominal_s"] * fat
        a.plot(per, ".", ms=2, color=CORES[i % len(CORES)])
        a.axhline(T, color="k", lw=1, label=f"T = {T:.3f} {un}")
        lo, hi = min(per.min(), T), max(per.max(), T)
        mg = max((hi - lo) * 0.15, T * 1e-4)
        a.set_ylim(lo - mg, hi + mg)
        a.ticklabel_format(axis="y", useOffset=False)
        a.set_title(f"{task['nome']} - período | jitter pp {fmt_t(m['jitter_pp_s'])} | miss {m['miss_rate_pct']:.2f}%")
        a.set_xlabel("ativação"); a.set_ylabel(un); a.legend(fontsize=8)
    fig.tight_layout()
    return fig


def g_jitter(plt, ctx):
    tasks, M = ctx["tasks"], ctx["M"]
    fig, axs = _grade(plt, len(tasks))
    for i, task in enumerate(tasks):
        a, m = axs[i], M.get(task["nome"])
        if not m:
            a.text(0.5, 0.5, f"{task['nome']}: sem sinal", ha="center", transform=a.transAxes); continue
        desvio = m["_per"] - m["periodo_nominal_s"]
        fat, un = unidade(max(np.abs(desvio).max(), 1e-9))
        a.hist(desvio * fat, bins=60, color=CORES[i % len(CORES)], alpha=0.85)
        a.axvline(0, color="k", lw=1)
        a.set_title(f"{task['nome']} - desvio do período (σ = {fmt_t(m['jitter_std_s'])})")
        a.set_xlabel(f"período − T ({un})"); a.set_ylabel("ocorrências")
    fig.tight_layout()
    return fig


def g_resumo(plt, ctx):
    tasks, M = ctx["tasks"], ctx["M"]
    nomes = [x["nome"] for x in tasks]
    cores = [CORES[i % len(CORES)] for i in range(len(tasks))]
    val = lambda k, f=1.0: [(M[n][k] * f if M.get(n) else 0) for n in nomes]
    paineis = [
        ("WCET (us)", val("wcet_s", 1e6)),
        ("Jitter pico-a-pico (us)", val("jitter_pp_s", 1e6)),
        ("Utilização CPU (%)", val("utilizacao_pct")),
        ("Deadline Miss Rate (%)", val("miss_rate_pct")),
    ]
    fig, axs = plt.subplots(2, 2, figsize=(13, 7))
    for a, (titulo, ys) in zip(axs.ravel(), paineis):
        b = a.bar(nomes, ys, color=cores)
        a.bar_label(b, fmt="%.2f", fontsize=8)
        a.set_title(titulo)
        a.tick_params(axis="x", labelrotation=15)
        a.margins(y=0.2)
    fig.suptitle(f"Resumo - {ctx['titulo']}")
    fig.tight_layout()
    return fig


GERADORES = {"timeline": g_timeline, "execucao": g_execucao, "periodo": g_periodo,
             "jitter": g_jitter, "resumo": g_resumo}


def gerar_graficos(pasta, ctx, lista, mostrar):
    import matplotlib
    if not mostrar:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    feitos = []
    for nome in lista:
        if nome not in GERADORES:
            print(f"[aviso] gráfico desconhecido '{nome}'. Opções: {', '.join(GRAFICOS_DISPONIVEIS)}")
            continue
        fig = GERADORES[nome](plt, ctx)
        fig.savefig(os.path.join(pasta, f"{nome}.png"), dpi=130)
        feitos.append(nome)
    if mostrar:
        plt.show()
    plt.close("all")
    return feitos


# ----------------------------------------------------------------- principal
def achar_csv(pasta):
    csvs = glob.glob(os.path.join(pasta, "*.csv"))
    return next((p for p in csvs if os.path.basename(p).lower().startswith("digital")), csvs[0] if csvs else None)


def analisar_pasta(alvo, mostrar=True, stack_path=None, config_path=None, graficos=None, verbose=True):
    if os.path.isdir(alvo):
        pasta, csv_path = alvo, achar_csv(alvo)
        if not csv_path:
            raise SystemExit(f"Nenhum CSV em {pasta}")
    else:
        csv_path, pasta = alvo, os.path.dirname(os.path.abspath(alvo))

    # prioridade: --config > config salva junto da captura > config.json da raiz
    if not config_path:
        locais = [os.path.join(pasta, n) for n in NOMES_CONFIG if os.path.exists(os.path.join(pasta, n))]
        config_path = locais[0] if locais else CONFIG_PADRAO
    cfg = carregar_config(config_path)
    tasks, an = cfg["tasks"], cfg["analise"]

    t, V, header = ler_digital_csv(csv_path)
    duracao = t[-1] - max(t[0], 0.0)
    cols = [coluna_do_canal(header, x["canal"]) for x in tasks]
    for task, c in zip(tasks, cols):
        if c is None:
            print(f"[aviso] canal {task['canal']} ({task['nome']}) não está no CSV. Colunas: {header}")

    M = {task["nome"]: (metricas_task(t, V[:, c], task, an["tolerancia_periodo"], duracao) if c is not None else None)
         for task, c in zip(tasks, cols)}
    sem_sinal = [n for n, m in M.items() if m is None]

    stack = ler_stack(stack_path or os.path.join(pasta, "stack.txt"))
    nomes = [x["nome"] for x in tasks]
    titulo = os.path.basename(os.path.normpath(pasta))
    md = tabela_md(nomes, M, stack, f"Resultados - {titulo}")

    with open(os.path.join(pasta, "metricas.json"), "w", encoding="utf-8") as f:
        json.dump({"captura": titulo, "duracao_s": duracao, "stack": stack,
                   "tasks": {n: ({k: v for k, v in m.items() if not k.startswith("_")} if m else None)
                             for n, m in M.items()}},
                  f, indent=2, ensure_ascii=False)

    if verbose:
        print(md)
    if sem_sinal:
        print(f"[aviso] sem sinal válido em: {', '.join(sem_sinal)} -> confira fiação, GND comum e instrumentação.")

    lista = graficos if graficos is not None else an["graficos"]
    feitos = []
    if lista and len(sem_sinal) < len(tasks):
        ctx = {"t": t, "V": V, "cols": cols, "tasks": tasks, "M": M, "an": an, "titulo": titulo}
        feitos = gerar_graficos(pasta, ctx, lista, mostrar)

    # o metricas.md ja inclui os graficos: abra o preview no VS Code (Ctrl+Shift+V)
    if feitos:
        md += "\n## Gráficos\n\n" + "\n\n".join(f"![{g}]({g}.png)" for g in feitos) + "\n"
    with open(os.path.join(pasta, "metricas.md"), "w", encoding="utf-8") as f:
        f.write(md)
    if verbose:
        print(f"Arquivos salvos em: {pasta}")
    return M


def captura_mais_recente():
    pastas = [p for p in glob.glob(os.path.join(AQUI, "capturas", "*")) if os.path.isdir(p)]
    if not pastas:
        raise SystemExit("Nenhuma captura em capturas/. Rode capturar.py ou passe um CSV.")
    return max(pastas, key=os.path.getmtime)


def main():
    ap = argparse.ArgumentParser(description="Calcula métricas RTOS a partir de uma captura do Saleae.")
    ap.add_argument("alvo", nargs="?", help="pasta da captura ou CSV (padrão: mais recente em capturas/)")
    ap.add_argument("--config", help="config a usar (padrão: a salva na captura, senão config.json)")
    ap.add_argument("--stack", help="log serial com linhas [STACK] ... (padrão: stack.txt na pasta)")
    ap.add_argument("--graficos", help=f"lista separada por vírgula: {','.join(GRAFICOS_DISPONIVEIS)} (ou 'nenhum')")
    ap.add_argument("--sem-grafico", action="store_true", help="salva os PNGs mas não abre janelas")
    args = ap.parse_args()

    graficos = None
    if args.graficos:
        graficos = [] if args.graficos == "nenhum" else [g.strip() for g in args.graficos.split(",") if g.strip()]
    analisar_pasta(args.alvo or captura_mais_recente(), mostrar=not args.sem_grafico,
                   stack_path=args.stack, config_path=args.config, graficos=graficos)


if __name__ == "__main__":
    main()
