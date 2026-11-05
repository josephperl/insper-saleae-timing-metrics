# Timing Metrics - extensao de medicao digital para o Saleae Logic 2.
#
# Selecione um trecho de QUALQUER canal digital (Shift + arrastar, ou o painel de
# Measurements) e a extensao calcula, considerando o sinal em nivel ALTO como "ativo":
#
#   periodo / frequencia  -> intervalo entre bordas de subida consecutivas
#   jitter                -> variacao desse intervalo (pico-a-pico e desvio padrao)
#   largura em alto       -> borda de subida -> borda de descida (WCET = maior, BCET = menor)
#   duty cycle            -> tempo em alto / tempo total (= utilizacao de CPU de uma task)
#   deadline miss rate    -> periodo nominal T = mediana dos periodos; conta como miss:
#                            pulso mais largo que T, periodo > T*(1+TOLERANCIA)
#                            e ativacoes que nao aconteceram (periodo ~ 2T, 3T...)
#
# Roda dentro do Logic 2 (Python 3.8, sem numpy).

import math

from saleae.range_measurements import DigitalMeasurer

TOLERANCIA = 0.10  # 10% de atraso no periodo antes de contar como deadline miss

PULSOS = "pulsos"
FREQUENCIA = "frequencia"
PERIODO_MEDIO = "periodoMedio"
PERIODO_MIN = "periodoMin"
PERIODO_MAX = "periodoMax"
JITTER_PP = "jitterPP"
JITTER_STD = "jitterStd"
LARGURA_MAX = "larguraMax"
LARGURA_MIN = "larguraMin"
LARGURA_MEDIA = "larguraMedia"
DUTY = "dutyCycle"
MISS = "missRate"

US = 1e6


class TimingMetrics(DigitalMeasurer):
    supported_measurements = [PULSOS, FREQUENCIA, PERIODO_MEDIO, PERIODO_MIN, PERIODO_MAX,
                              JITTER_PP, JITTER_STD, LARGURA_MAX, LARGURA_MIN, LARGURA_MEDIA,
                              DUTY, MISS]

    def __init__(self, requested_measurements):
        super().__init__(requested_measurements)
        self.t0 = None          # GraphTime do inicio do trecho (referencia)
        self.estado = None      # nivel atual do sinal
        self.subidas = []       # instantes (s) das bordas de subida
        self.larguras = []      # largura (s) de cada pulso completo em alto
        self.ultima_subida = None

    def process_data(self, data):
        # O primeiro item e o inicio do trecho selecionado (nao e borda);
        # os demais sao transicoes. Pode ser chamado varias vezes (em blocos).
        for t, nivel in data:
            if self.t0 is None:
                self.t0 = t
                self.estado = nivel
                continue
            if nivel == self.estado:
                continue
            s = float(t - self.t0)
            if nivel:                                   # borda de subida
                self.subidas.append(s)
                self.ultima_subida = s
            elif self.ultima_subida is not None:        # borda de descida
                self.larguras.append(s - self.ultima_subida)
                self.ultima_subida = None
            self.estado = nivel

    def measure(self):
        r = {}
        sub, larg = self.subidas, self.larguras
        per = [b - a for a, b in zip(sub, sub[1:])]
        r[PULSOS] = len(sub)

        if per:
            media = sum(per) / len(per)
            r[FREQUENCIA] = 1.0 / media if media > 0 else 0.0
            r[PERIODO_MEDIO] = media * US
            r[PERIODO_MIN] = min(per) * US
            r[PERIODO_MAX] = max(per) * US
            r[JITTER_PP] = (max(per) - min(per)) * US
            r[JITTER_STD] = math.sqrt(sum((p - media) ** 2 for p in per) / len(per)) * US

        if larg:
            r[LARGURA_MAX] = max(larg) * US
            r[LARGURA_MIN] = min(larg) * US
            r[LARGURA_MEDIA] = sum(larg) / len(larg) * US

        if per and larg:
            # duty sobre ciclos completos: da primeira a ultima borda de subida
            span = sub[-1] - sub[0]
            alto = sum(larg[:len(per)])
            r[DUTY] = 100.0 * alto / span if span > 0 else 0.0

            T = sorted(per)[len(per) // 2]
            perdidas = atrasadas = 0
            for p in per:
                k = int(round(p / T)) if T > 0 else 1
                if k >= 2:
                    perdidas += k - 1
                elif p > T * (1 + TOLERANCIA):
                    atrasadas += 1
            estouros = sum(1 for w in larg if w > T)
            total = len(sub) + perdidas
            r[MISS] = 100.0 * (perdidas + atrasadas + estouros) / total if total else 0.0

        return {k: v for k, v in r.items() if k in self.requested_measurements}
