"""
Medidor de tempo com Saleae - rode no terminal do VS Code:

    python medir.py

Mede tasks do FreeRTOS ou funções bare metal instrumentadas com um GPIO (1 no início, 0 no fim).
Na primeira vez ele pergunta quais tasks/funções, GPIOs e canais medir e salva em config.json.
Depois fica num menu: capturar, ver ao vivo, reabrir, comparar, stack...
Os resultados abrem no proprio VS Code (Ctrl+Shift+V mostra tabela + graficos).
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from analisar import (AQUI, CONFIG_PADRAO, GRAFICOS_DISPONIVEIS, analisar_pasta,
                      carregar_config, fmt_t)
from capturar import capturar, conectar, nova_pasta
from comparar import comparar

DESCRICAO_GRAFICOS = {
    "timeline": "sinais no tempo (tipo analisador lógico)",
    "execucao": "histograma do tempo em alto, com WCET",
    "periodo": "período de cada ativação ao longo da captura",
    "jitter": "histograma do desvio do período",
    "resumo": "barras com WCET, jitter, duty e miss de todos",
}
LINHA = "-" * 64


# ================================================================ entrada
def perguntar(texto, padrao=None, tipo=str, opcional=False, minimo=None, maximo=None):
    """Pergunta no terminal. Enter = padrao. opcional=True permite resposta vazia (None)."""
    if padrao not in (None, ""):
        dica = f" [{padrao}{' / auto' if opcional else ''}]"
    else:
        dica = " [Enter = automático]" if opcional else ""
    while True:
        r = input(f"  {texto}{dica}: ").strip()
        if opcional and r.lower() in ("auto", "a", "-"):
            return None
        if not r:
            if padrao not in (None, ""):
                r = str(padrao)
            elif opcional:
                return None
            else:
                print("    -> resposta obrigatória")
                continue
        try:
            v = tipo(r.replace(",", ".")) if tipo in (int, float) else tipo(r)
        except ValueError:
            print("    -> valor inválido")
            continue
        if minimo is not None and v < minimo or maximo is not None and v > maximo:
            print(f"    -> use um valor entre {minimo} e {maximo}")
            continue
        return v


def sim(texto, padrao=True):
    r = input(f"  {texto} [{'S/n' if padrao else 's/N'}]: ").strip().lower()
    return padrao if not r else r.startswith("s") or r.startswith("y")


def escolher_captura(texto, multiplas=False):
    pastas = listar_capturas()
    if not pastas:
        print("  Nenhuma captura ainda.")
        return None
    for i, p in enumerate(pastas, 1):
        print(f"   {i:>2}. {os.path.basename(p)}")
    if multiplas:
        r = input(f"  {texto} (ex: 1,3) [as 2 últimas]: ").strip()
        if not r:
            return pastas[-2:] if len(pastas) >= 2 else None
        try:
            idx = [int(x) for x in r.replace(" ", "").split(",") if x]
            return [pastas[i - 1] for i in idx]
        except (ValueError, IndexError):
            print("  -> escolha inválida")
            return None
    r = input(f"  {texto} [{len(pastas)} = mais recente]: ").strip()
    try:
        return pastas[(int(r) if r else len(pastas)) - 1]
    except (ValueError, IndexError):
        print("  -> escolha inválida")
        return None


# ================================================================ config
def assistente_config(atual=None):
    print(f"\n{LINHA}\n CONFIGURAÇÃO  (Enter aceita o valor entre colchetes)\n{LINHA}")
    sinais_atuais = (atual or {}).get("tasks", [])
    n = perguntar("Quantas tasks/funções vai medir", len(sinais_atuais) or 1, int, minimo=1, maximo=16)

    sinais, usados, gpios_usadas = [], set(), set()
    for i in range(n):
        ant = sinais_atuais[i] if i < len(sinais_atuais) else {}
        print(f"\n  Sinal {i + 1}")
        nome = perguntar("Nome da task/função (ex: mpu_task, calc_fft, isr_botao)", ant.get("nome", f"sinal{i}"))
        while True:
            gpio = perguntar("GPIO que a task/função coloca em 1 e 0 (ex: 10)", ant.get("gpio"), int,
                             minimo=0, maximo=29)
            if gpio not in gpios_usadas:
                break
            print("    -> GPIO já usada por outro sinal")
        gpios_usadas.add(gpio)
        while True:
            canal = perguntar("Canal do Saleae onde o fio está ligado", ant.get("canal", i), int, minimo=0, maximo=15)
            if canal not in usados:
                break
            print("    -> canal já usado por outro sinal")
        usados.add(canal)
        per = perguntar("Período esperado em ms", ant.get("periodo_ms"), float, opcional=True, minimo=0.000001)
        dl = perguntar("Deadline em ms (Enter = igual ao período)", ant.get("deadline_ms"), float,
                       opcional=True, minimo=0.000001)
        sinais.append({"nome": nome, "gpio": gpio, "canal": canal, "periodo_ms": per, "deadline_ms": dl})

    cap = (atual or {}).get("captura", {})
    an = (atual or {}).get("analise", {})
    print("\n  Captura")
    duracao = perguntar("Duração de cada captura em segundos", cap.get("duracao_s", 10), float, minimo=0.1, maximo=600)
    taxa = perguntar("Taxa de amostragem em MS/s (10 = resolução de 0,1 us)",
                     int(cap.get("sample_rate_hz", 10_000_000) / 1e6), float, minimo=0.1)

    print("\n  Gráficos")
    for i, g in enumerate(GRAFICOS_DISPONIVEIS, 1):
        print(f"   {i}. {g:<9} - {DESCRICAO_GRAFICOS[g]}")
    atuais = an.get("graficos", GRAFICOS_DISPONIVEIS)
    pad = ",".join(str(GRAFICOS_DISPONIVEIS.index(g) + 1) for g in atuais if g in GRAFICOS_DISPONIVEIS) or "0"
    while True:
        r = input(f"  Quais gerar? números separados por vírgula, 0 = nenhum [{pad}]: ").strip() or pad
        try:
            nums = [int(x) for x in r.replace(" ", "").split(",") if x]
            graficos = [] if nums == [0] else [GRAFICOS_DISPONIVEIS[k - 1] for k in nums]
            break
        except (ValueError, IndexError):
            print("    -> escolha inválida")

    fw = configurar_firmware((atual or {}).get("firmware"))

    cfg = {
        "captura": {"porta_automation": cap.get("porta_automation", 10430),
                    "sample_rate_hz": int(taxa * 1e6), "duracao_s": duracao},
        "analise": {"tolerancia_periodo": an.get("tolerancia_periodo", 0.10),
                    "graficos": graficos, "timeline_janela_ms": an.get("timeline_janela_ms")},
        "sinais": sinais,
    }
    if fw:
        cfg["firmware"] = fw
    with open(CONFIG_PADRAO, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"\n  Configuração salva em {os.path.basename(CONFIG_PADRAO)}")
    if fw:
        gerar_firmware(fw, sinais)
    else:
        print("\n  Não achei o projeto da placa (CMakeLists.txt numa pasta acima desta).")
        print("  Coloque esta pasta dentro do projeto para os arquivos serem gerados sozinhos, ou use:")
        for s in sinais:
            print(f"    #define {macro_pino(s)} {s['gpio']}")
        print(f"    METRICS_INIT_PINS({', '.join(macro_pino(s) for s in sinais)});")
    return carregar_config(CONFIG_PADRAO)


# ================================================================ firmware
def macro_pino(sinal):
    return "PIN_" + "".join(c if c.isalnum() else "_" for c in sinal["nome"]).upper()


def ler_texto(caminho):
    try:
        with open(caminho, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def achar_projeto():
    """Primeira pasta acima desta que tem CMakeLists.txt (o projeto da placa)."""
    d = os.path.dirname(AQUI)
    while True:
        if os.path.isfile(os.path.join(d, "CMakeLists.txt")):
            return d
        pai = os.path.dirname(d)
        if pai == d:
            return None
        d = pai


def fontes_c(raiz):
    """Arquivos .c/.cpp do projeto, sem build, SDK, FreeRTOS nem esta pasta."""
    eu = os.path.normcase(os.path.abspath(AQUI))
    for pasta, subpastas, arquivos in os.walk(raiz):
        subpastas[:] = [s for s in subpastas
                        if os.path.normcase(os.path.abspath(os.path.join(pasta, s))) != eu
                        and not s.lower().startswith((".", "build", "pico-sdk", "pico_sdk", "freertos"))]
        for a in arquivos:
            if a.endswith((".c", ".cpp")):
                yield os.path.join(pasta, a)


def configurar_firmware(atual):
    """Acha o projeto e a pasta do main.c. Devolve {"pasta", "freertos"} ou None."""
    raiz = achar_projeto()
    if not raiz:
        return None
    fontes = list(fontes_c(raiz))
    mains = sorted({os.path.dirname(f) for f in fontes if re.search(r"\bint\s+main\s*\(", ler_texto(f))})
    usa_rtos = any(re.search(r'#\s*include\s*[<"]FreeRTOS\.h', ler_texto(f)) for f in fontes)
    candidatas = mains or [raiz]

    print(f"\n  Firmware  (projeto: {raiz})")
    anterior = os.path.normcase(os.path.normpath(os.path.join(AQUI, atual["pasta"]))) if atual else None
    if len(candidatas) == 1:
        pasta = candidatas[0]
    else:
        padrao = next((i for i, c in enumerate(candidatas, 1) if os.path.normcase(c) == anterior), 1)
        for i, c in enumerate(candidatas, 1):
            print(f"   {i}. {os.path.relpath(c, raiz)}")
        pasta = candidatas[perguntar("Em qual pasta está o main.c", padrao, int, minimo=1,
                                     maximo=len(candidatas)) - 1]
    print(f"    Arquivos vão para: {pasta}")
    rtos = sim("O projeto usa FreeRTOS?", atual.get("freertos", usa_rtos) if atual else usa_rtos)
    return {"pasta": os.path.relpath(pasta, AQUI).replace(os.sep, "/"), "freertos": rtos}


def gerar_firmware(fw, sinais, verbose=True):
    """Escreve metrics_pins.h (GPIOs da config) e copia rtos_metrics.h para a pasta do main.c."""
    pasta = os.path.normpath(os.path.join(AQUI, fw["pasta"]))
    if not os.path.isdir(pasta):
        print(f"  [aviso] pasta do firmware não existe mais: {pasta}  (use [e] para escolher de novo)")
        return
    sinais = [s for s in sinais if s.get("gpio") is not None]
    if not sinais:
        return
    nomes = [macro_pino(s) for s in sinais]
    linhas = [
        "/* Gerado pelo medir.py - NAO edite a mao: rode `python medir.py` e use [e] para mudar. */",
        "#ifndef METRICS_PINS_H",
        "#define METRICS_PINS_H",
        "",
        "#ifndef METRICS_BARE_METAL",
        f"#define METRICS_BARE_METAL {0 if fw.get('freertos') else 1}",
        "#endif",
        '#include "rtos_metrics.h"',
        "",
        *(f"#define {m:<24} {s['gpio']:>2}   /* {s['nome']} -> canal {s['canal']} do Saleae */"
          for m, s in zip(nomes, sinais)),
        "",
        f"#define METRICS_INIT_ALL() METRICS_INIT_PINS({', '.join(nomes)})",
        "",
        "#endif /* METRICS_PINS_H */",
        "",
    ]
    conteudo = "\n".join(linhas)
    destino = os.path.join(pasta, "metrics_pins.h")
    mudou = ler_texto(destino) != conteudo
    if mudou:
        with open(destino, "w", encoding="utf-8", newline="\n") as f:
            f.write(conteudo)

    origem = os.path.join(AQUI, "firmware", "rtos_metrics.h")
    copia = os.path.join(pasta, "rtos_metrics.h")
    status_hdr = "já estava lá"
    if not os.path.exists(copia):
        shutil.copy(origem, copia)
        status_hdr, mudou = "copiado", True
    elif ler_texto(copia) != ler_texto(origem):
        status_hdr = "mantido o seu (é diferente do repositório; apague-o para receber a versão nova)"

    if not (verbose or mudou):
        return
    rel = os.path.relpath(pasta, os.path.dirname(AQUI))
    print(f"\n  Firmware atualizado em {rel}:")
    pinos = ", ".join(f"{m}={s['gpio']}" for m, s in zip(nomes, sinais))
    print(f"    metrics_pins.h  ({pinos})")
    print(f"    rtos_metrics.h  ({status_hdr})")
    print("  No código, só falta:")
    print('    #include "metrics_pins.h"     // no topo de cada .c que tem task/função medida')
    print("    METRICS_INIT_ALL();           // no começo da main")
    print("    + START/END em cada task/função (veja o README)")


def mostrar_config(cfg):
    cap = cfg["captura"]
    print(f"  Captura: {cap['duracao_s']:g} s @ {cap['sample_rate_hz'] / 1e6:g} MS/s   "
          f"Gráficos: {', '.join(cfg['analise']['graficos']) or 'nenhum'}")
    for s in cfg["tasks"]:
        per = f"{s['periodo_ms']:g} ms" if s.get("periodo_ms") else "auto"
        dl = f"{s['deadline_ms']:g} ms" if s.get("deadline_ms") else "= período"
        gpio = f"GPIO {s['gpio']}" if s.get("gpio") is not None else "GPIO ?"
        print(f"   canal {s['canal']:>2}  {gpio:<8} {s['nome']:<16} período {per:<10} deadline {dl}")


# ================================================================ acoes
def listar_capturas():
    return sorted((p for p in glob.glob(os.path.join(AQUI, "capturas", "*")) if os.path.isdir(p)),
                  key=os.path.getmtime)


def abrir_no_vscode(arquivo):
    """Abre o arquivo na janela atual do VS Code; fora dele, abre a pasta."""
    if shutil.which("code"):
        subprocess.Popen(f'code -r "{arquivo}"', shell=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"  Aberto no VS Code: {os.path.relpath(arquivo, AQUI)}  ->  Ctrl+Shift+V mostra com os gráficos")
    else:
        pasta = os.path.dirname(arquivo)
        print(f"  Resultado em: {pasta}")
        if sys.platform.startswith("win"):
            os.startfile(pasta)


def acao_capturar(cfg, contador):
    nome = perguntar("Nome desta captura (ex: single_core, smp, antes, depois)", f"captura{contador}")
    nome = "".join(c if c.isalnum() or c in "-_" else "_" for c in nome)
    pasta = nova_pasta(nome)
    print(f"  Capturando {cfg['captura']['duracao_s']:g} s ...")
    capturar(cfg, pasta)
    shutil.copy(CONFIG_PADRAO, os.path.join(pasta, "config.json"))
    print()
    analisar_pasta(pasta, mostrar=False)
    abrir_no_vscode(os.path.join(pasta, "metricas.md"))


def acao_ao_vivo(cfg):
    """Captura curta em loop, mostrando um resumo - bom para checar fiação."""
    print("  Modo ao vivo: captura 1 s em loop. Ctrl+C para voltar ao menu.\n")
    tmp = tempfile.mkdtemp(prefix="saleae_vivo_")
    manager = conectar(cfg["captura"]["porta_automation"])
    try:
        while True:
            pasta = os.path.join(tmp, "c")
            shutil.rmtree(pasta, ignore_errors=True)
            capturar(cfg, pasta, duracao=1.0, manager=manager)
            M = analisar_pasta(pasta, mostrar=False, config_path=CONFIG_PADRAO, graficos=[], verbose=False)
            print(f"  {'sinal':<16}{'canal':>6}{'freq':>12}{'período':>13}{'larg. máx':>13}{'jitter pp':>13}  status")
            for s in cfg["tasks"]:
                m = M.get(s["nome"])
                if not m:
                    print(f"  {s['nome']:<16}{s['canal']:>6}{'-':>12}{'-':>13}{'-':>13}{'-':>13}  SEM SINAL")
                    continue
                status = "OK"
                if m["wcet_s"] < 2.5 / cfg["captura"]["sample_rate_hz"]:
                    status = "RUÍDO? (pulsos de 1 amostra - confira GND)"
                elif m["miss_rate_pct"] > 0:
                    status = f"miss {m['miss_rate_pct']:.1f}%"
                print(f"  {s['nome']:<16}{s['canal']:>6}{m['frequencia_hz']:>10.2f}Hz"
                      f"{fmt_t(m['periodo_medio_s']):>13}{fmt_t(m['wcet_s']):>13}{fmt_t(m['jitter_pp_s']):>13}  {status}")
            print()
    except KeyboardInterrupt:
        print("  (ao vivo encerrado)")
    finally:
        manager.close()
        shutil.rmtree(tmp, ignore_errors=True)


def acao_reabrir():
    pasta = escolher_captura("Qual captura reabrir")
    if pasta:
        print()
        analisar_pasta(pasta, mostrar=False)
        abrir_no_vscode(os.path.join(pasta, "metricas.md"))


def acao_comparar():
    pastas = escolher_captura("Quais capturas comparar", multiplas=True)
    if not pastas or len(pastas) < 2:
        print("  -> precisa de pelo menos 2 capturas")
        return
    for p in pastas:
        if not os.path.exists(os.path.join(p, "metricas.json")):
            analisar_pasta(p, mostrar=False, verbose=False)
    saida = comparar(pastas, mostrar=False)
    abrir_no_vscode(os.path.join(saida, "comparacao.md"))


def acao_stack():
    print("  No firmware, compile com METRICS_STACK 1 (veja firmware/rtos_metrics.h).")
    pasta = escolher_captura("Em qual captura adicionar o stack")
    if not pasta:
        return
    print("  Cole as linhas do terminal serial ([STACK] nome hwm=.. size=..) e aperte Enter numa linha vazia:")
    linhas = []
    while True:
        l = input()
        if not l.strip():
            break
        linhas.append(l)
    validas = [l for l in linhas if "[STACK]" in l]
    if not validas:
        print("  -> nenhuma linha [STACK] encontrada")
        return
    with open(os.path.join(pasta, "stack.txt"), "a", encoding="utf-8") as f:
        f.write("\n".join(validas) + "\n")
    print(f"  {len(validas)} linhas salvas em stack.txt\n")
    analisar_pasta(pasta, mostrar=False)
    abrir_no_vscode(os.path.join(pasta, "metricas.md"))


# ================================================================ main
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.chdir(AQUI)
    print(f"\n{LINHA}\n MEDIDOR DE TEMPO - SALEAE\n{LINHA}")

    if os.path.exists(CONFIG_PADRAO):
        cfg = carregar_config(CONFIG_PADRAO)
        print(" Configuração salva:")
        mostrar_config(cfg)
        if not sim("Usar essa configuração?"):
            cfg = assistente_config(cfg)
        elif cfg.get("firmware"):
            gerar_firmware(cfg["firmware"], cfg["tasks"], verbose=False)  # só avisa se algo mudou
        elif achar_projeto():
            print("  Dica: use [e] para gerar o metrics_pins.h no projeto da placa automaticamente.")
    else:
        cfg = assistente_config()

    contador = len(listar_capturas()) + 1
    menu = (f"\n{LINHA}\n"
            "  [Enter] capturar e medir\n"
            "  [v] ao vivo (checar fiação/sinais)\n"
            "  [r] reabrir uma captura\n"
            "  [c] comparar capturas\n"
            "  [s] adicionar stack (colar log serial)\n"
            "  [e] editar configuração\n"
            "  [q] sair\n"
            f"{LINHA}")
    while True:
        print(menu)
        try:
            op = input("  Opção: ").strip().lower()
            if op in ("q", "sair", "exit"):
                break
            elif op == "":
                acao_capturar(cfg, contador)
                contador += 1
            elif op == "v":
                acao_ao_vivo(cfg)
            elif op == "r":
                acao_reabrir()
            elif op == "c":
                acao_comparar()
            elif op == "s":
                acao_stack()
            elif op == "e":
                cfg = assistente_config(cfg)
                mostrar_config(cfg)
            else:
                print("  -> opção inválida")
        except ConnectionError as e:
            print(f"\n  {e}")
        except KeyboardInterrupt:
            print("\n  (cancelado)")
        except SystemExit as e:
            print(f"\n  {e}")
        except Exception as e:
            if type(e).__name__ == "MissingDeviceError":
                print("\n  O Logic 2 está aberto, mas não encontrou o Saleae. Confira o cabo USB "
                      "(no topo do Logic 2 deve aparecer 'Connected').")
                continue
            print(f"\n  ERRO: {type(e).__name__}: {e}")
            if "sample" in str(e).lower() or "rate" in str(e).lower():
                print("  -> taxa de amostragem não suportada pelo seu Saleae. Use [e] e tente 12.5, 25 ou 50.")
    print("  Até mais!")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n  Até mais!")
