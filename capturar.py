"""
Captura pelo Saleae Logic 2 (Automation API). Usado pelo medir.py; tambem roda sozinho:
  python capturar.py --nome teste
"""
import argparse
import os
import shutil
from datetime import datetime

from analisar import AQUI, CONFIG_PADRAO, carregar_config, analisar_pasta

AJUDA_CONEXAO = (
    "Nao conectou no Logic 2.\n"
    "  1. Abra o Logic 2 com o Saleae ligado no USB.\n"
    "  2. Clique em 'Automation' (canto inferior direito) e ligue 'Automation Server'.\n"
    "     (Logic 2 antigo: Options -> Preferences -> 'Enable scripting socket server')"
)


def conectar(porta):
    """Retorna o Manager conectado, ou levanta ConnectionError com a explicacao."""
    try:
        from saleae import automation
    except ImportError:
        raise ConnectionError("Falta o pacote: rode  pip install -r requirements.txt")
    try:
        return automation.Manager.connect(port=porta, connect_timeout_seconds=5)
    except Exception:
        raise ConnectionError(AJUDA_CONEXAO)


def capturar(cfg, pasta, duracao=None, manager=None):
    """Captura os canais da config e salva capture.sal + digital.csv em `pasta`."""
    from saleae import automation

    cap = cfg["captura"]
    duracao = duracao or cap["duracao_s"]
    canais = sorted({t["canal"] for t in cfg["tasks"]})
    proprio = manager is None
    if proprio:
        manager = conectar(cap["porta_automation"])
    os.makedirs(pasta, exist_ok=True)
    try:
        dev_cfg = automation.LogicDeviceConfiguration(
            enabled_digital_channels=canais,
            digital_sample_rate=cap["sample_rate_hz"],
        )
        cap_cfg = automation.CaptureConfiguration(
            capture_mode=automation.TimedCaptureMode(duration_seconds=duracao)
        )
        with manager.start_capture(device_configuration=dev_cfg, capture_configuration=cap_cfg) as capture:
            capture.wait()
            capture.export_raw_data_csv(directory=pasta, digital_channels=canais)
            capture.save_capture(filepath=os.path.join(pasta, "capture.sal"))
    except Exception:
        shutil.rmtree(pasta, ignore_errors=True)
        raise
    finally:
        if proprio:
            manager.close()
    return pasta


def nova_pasta(nome):
    return os.path.join(AQUI, "capturas", datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + nome)


def main():
    ap = argparse.ArgumentParser(description="Captura os canais configurados com o Saleae Logic 2.")
    ap.add_argument("--nome", default="captura")
    ap.add_argument("--config", default=CONFIG_PADRAO)
    ap.add_argument("--duracao", type=float)
    ap.add_argument("--sem-analise", action="store_true")
    ap.add_argument("--sem-grafico", action="store_true")
    args = ap.parse_args()

    cfg = carregar_config(args.config)
    pasta = nova_pasta(args.nome)
    try:
        capturar(cfg, pasta, args.duracao)
    except ConnectionError as e:
        raise SystemExit(str(e))
    shutil.copy(args.config, os.path.join(pasta, "config.json"))
    print(f"Salvo em: {pasta}")
    if not args.sem_analise:
        analisar_pasta(pasta, mostrar=not args.sem_grafico)


if __name__ == "__main__":
    main()
