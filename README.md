# insper-saleae-timing-metrics

Mede o **tempo de tasks do FreeRTOS e de funções bare metal com o Saleae, direto do VS Code**.

A ideia: cada task/função que você quer medir ganha **um GPIO só dela**. O código coloca o GPIO em
**1 quando começa** e em **0 quando termina**. O Saleae lê esse pino e o `medir.py` calcula as métricas
e abre o resultado com tabela e gráficos.

```
           GPIO = 1          GPIO = 0                GPIO = 1          GPIO = 0
              ┌─── execução ───┐                        ┌─── execução ───┐
  ────────────┘                └────────────────────────┘                └──────
              │◀──────────────────── período ──────────▶│
```

**Métricas:** tempo de execução (**WCET** / BCET), período, frequência, **jitter**, **utilização**,
**deadline miss rate** e **stack usage** (só FreeRTOS).

| Para medir... | Onde colocar o GPIO em 1 e em 0 |
|---|---|
| Task do FreeRTOS | 1 logo depois de acordar (`vTaskDelay`, `xQueueReceive`…), 0 logo antes de bloquear de novo |
| Função bare metal | 1 na primeira linha da função, 0 na última |
| ISR / callback | 1 no começo da interrupção, 0 no fim |

```
 placa ──fios──▶ Saleae ──USB──▶ Logic 2 ◀── medir.py (VS Code) ──▶ tabela + gráficos
```

---

## Instalação (uma vez só)

### 1. Logic 2

1. Baixe e instale o **Logic 2**: <https://www.saleae.com/downloads/>
2. Ligue o Saleae no USB e abra o Logic 2. No topo tem que aparecer **"Logic 8 - Connected"** (ou o seu modelo).
3. No canto **inferior direito** do Logic 2, clique em **Automation** e ligue **Automation Server**.
   É por ele que o VS Code controla o Saleae.

### 2. Este repositório + Python

Precisa do **Python 3.9 ou mais novo** e do **VS Code**.

Clone **dentro da pasta do seu projeto da placa** (a que tem o `CMakeLists.txt`). Assim o `medir.py`
acha o seu código e gera os arquivos do firmware sozinho:

```
meu_projeto/
├── CMakeLists.txt
├── main.c                          ← aqui vão aparecer metrics_pins.h e rtos_metrics.h
└── insper-saleae-timing-metrics/   ← este repositório
```

No terminal do VS Code (**Ctrl + '**), dentro do seu projeto:

```bash
git clone https://github.com/josephperl/insper-saleae-timing-metrics.git
cd insper-saleae-timing-metrics
pip install -r requirements.txt
```

> Se usa git no projeto, coloque `insper-saleae-timing-metrics/` no `.gitignore` dele.

---

## Uso

### 1. Configure: rode `medir.py`

No terminal do VS Code, dentro de `insper-saleae-timing-metrics/`:

```bash
python medir.py
```

**Na primeira vez** ele pergunta (Enter aceita o valor sugerido). Use **um GPIO diferente para cada task/função**:

```
  Quantas tasks/funções vai medir [1]: 2

  Sinal 1
  Nome da task/função (ex: mpu_task, calc_fft, isr_botao) [sinal0]: mpu_task
  GPIO que a task/função coloca em 1 e 0 (ex: 10): 10
  Canal do Saleae onde o fio está ligado [0]: 0
  Período esperado em ms [Enter = automático]: 10
  Deadline em ms (Enter = igual ao período) [Enter = automático]:

  Sinal 2
  ...
  Duração de cada captura em segundos [10]:
  Taxa de amostragem em MS/s (10 = resolução de 0,1 us) [10]:

   1. timeline  - sinais no tempo (tipo analisador lógico)
   2. execucao  - histograma do tempo em alto, com WCET
   3. periodo   - período de cada ativação ao longo da captura
   4. jitter    - histograma do desvio do período
   5. resumo    - barras com WCET, jitter, duty e miss de todos
  Quais gerar? números separados por vírgula, 0 = nenhum [1,2,3,4,5]:

  Firmware  (projeto: C:\...\meu_projeto)
    Arquivos vão para: C:\...\meu_projeto
  O projeto usa FreeRTOS? [S/n]:
```

Ele acha sozinho a pasta do `main.c` (se tiver mais de uma, pergunta qual) e se o projeto usa FreeRTOS.
Depois salva tudo em `config.json` e **gera dois arquivos ao lado do seu `main.c`**:

| Arquivo | O que tem |
|---|---|
| `metrics_pins.h` | Os `#define PIN_...` com as GPIOs que você respondeu e o `METRICS_INIT_ALL()` |
| `rtos_metrics.h` | As macros `START`/`END` (copiado de [`firmware/`](firmware/rtos_metrics.h)) |

```
  Firmware atualizado em meu_projeto:
    metrics_pins.h  (PIN_MPU_TASK=10, PIN_CALC_FFT=11)
    rtos_metrics.h  (copiado)
```

O `metrics_pins.h` é **refeito toda vez que você muda a configuração** (opção **[e]**), então o GPIO do
código e o do `medir.py` nunca ficam diferentes. Não edite esse arquivo à mão.

Nas próximas vezes ele só pergunta se quer manter a configuração.

> Sem `CMakeLists.txt` numa pasta acima, ele não gera nada e só mostra os `#define` para você copiar.

### 2. Instrumente o código

No seu código você só escreve três coisas (exemplos completos em
[Instrumentar o código](#instrumentar-o-código)):

```c
#include "metrics_pins.h"                // 1. no topo de cada .c que tem task/função medida

int main() {
    METRICS_INIT_ALL();                  // 2. no começo da main
    ...
}

void calc_fft(void) {
    METRICS_FUNC_START(PIN_CALC_FFT);    // 3. GPIO = 1 no início
    ...
    METRICS_FUNC_END(PIN_CALC_FFT);      //    GPIO = 0 no fim
}
```

Compile e grave na placa.

### 3. Ligue os fios

| Saleae | Placa |
|---|---|
| Fio do canal 0, 1, 2… | GPIO de cada task/função |
| **Fio preto (GND)** | **GND da placa — obrigatório** |

> Sem o GND comum a medição vira ruído.

Pico / Pico 2: GP10 = pino 14, GP11 = 15, GP12 = 16, GP13 = 17. GND = pinos 3, 8, 13, 18, 23, 28, 33, 38.

### 4. Menu

Com a placa rodando e os fios ligados, volte ao terminal do `medir.py`. Ele fica neste menu:

```
  [Enter] capturar e medir
  [v] ao vivo (checar fiação/sinais)
  [r] reabrir uma captura
  [c] comparar capturas
  [s] adicionar stack (colar log serial)
  [e] editar configuração
  [q] sair
```

| Opção | O que faz |
|---|---|
| **Enter** | Pede um nome (ex: `single_core`), captura, mostra a tabela no terminal e **abre o resultado no VS Code** |
| **v** | Captura 1 s em loop e mostra frequência, período, largura e jitter de cada canal. Use **antes** de medir para ver se os fios estão certos. Ctrl+C volta ao menu |
| **r** | Lista as capturas anteriores e reabre uma. Recalcula tudo, então serve depois de mudar a config da captura |
| **c** | Compara 2 ou mais capturas lado a lado (ex: antes × depois, single core × SMP) |
| **s** | Cole as linhas `[STACK] ...` do monitor serial e o stack entra na tabela |
| **e** | Refaz as perguntas: troca GPIOs, canais, períodos, duração ou gráficos. Atualiza o `metrics_pins.h` (recompile o firmware se mudou GPIO) |

### 5. Ver o resultado

O resultado abre como `metricas.md` no VS Code. Aperte **Ctrl+Shift+V** para ver a tabela **com os gráficos**.

Tudo fica salvo em `capturas/<data>_<nome>/`:

| Arquivo | Para quê |
|---|---|
| `metricas.md` | Tabela + gráficos. Dá para copiar a tabela para o README da entrega |
| `*.png` | Gráficos |
| `capture.sal` | Captura original. Duplo clique abre no Logic 2, para tirar prints |
| `digital.csv`, `metricas.json` | Dados crus e métricas em JSON |
| `config.json` | Configuração usada nessa captura |

Comparações ficam em `comparacoes/`.

---

## Como as métricas são calculadas

GPIO em **1** = task/função executando. GPIO em **0** = parada.

| Métrica | Definição |
|---|---|
| **Período / Frequência** | Intervalo entre ativações (GPIO 0 → 1) consecutivas |
| **Jitter pico-a-pico** | Período máximo − período mínimo. Também mostra desvio padrão e maior desvio em relação a T |
| **WCET / BCET** | Maior / menor tempo com o GPIO em 1. Numa task RTOS inclui o tempo em que ela ficou preemptada; numa função bare metal inclui as interrupções que caíram no meio |
| **Utilização** | Tempo total com o GPIO em 1 ÷ duração da captura |
| **Deadline Miss Rate** | Conta como miss: tempo em alto > deadline, período > T + 10%, ou ativação que não aconteceu. T = período que você informou (ou a mediana, se deixou automático) |
| **Stack Usage** | `size − high water mark`, no pior caso do log (em words). Regra dos 80%: usado ≤ 80% |

---

## Instrumentar o código

O `medir.py` já gera o `metrics_pins.h` (GPIOs) e copia o `rtos_metrics.h` (macros) para a pasta do
seu `main.c`. As macros só colocam o GPIO em 1 (`START`) e em 0 (`END`). Os nomes `PIN_...` vêm do
nome que você deu no `medir.py` (`mpu_task` → `PIN_MPU_TASK`).

Feito para Pico / Pico 2. Para outra placa, troque só as 3 macros `METRICS_GPIO_*` do `rtos_metrics.h`.

### Tasks do FreeRTOS

```c
#include "metrics_pins.h"

void mpu_task(void *p) {
    for (;;) {
        METRICS_TASK_START(PIN_MPU_TASK);   // logo DEPOIS de acordar
        /* ... trabalho da task ... */
        METRICS_TASK_END(PIN_MPU_TASK);     // logo ANTES de dormir/bloquear
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

int main() {
    METRICS_INIT_ALL();
    /* xTaskCreate(...); vTaskStartScheduler(); */
}
```

Task disparada por fila: o `START` vai logo **depois** do `xQueueReceive` retornar.

### Funções bare metal (sem FreeRTOS)

Igual, só que com `METRICS_FUNC_START` / `METRICS_FUNC_END`. Se você respondeu que o projeto **não**
usa FreeRTOS, o `metrics_pins.h` já liga o modo bare metal sozinho.

```c
#include "metrics_pins.h"

void calc_fft(void) {
    METRICS_FUNC_START(PIN_CALC_FFT);   // GPIO = 1 na primeira linha
    /* ... trabalho da função ... */
    METRICS_FUNC_END(PIN_CALC_FFT);     // GPIO = 0 na última linha (antes de cada return)
}

int main() {
    stdio_init_all();
    METRICS_INIT_ALL();
    while (true) {
        calc_fft();
        sleep_ms(10);
    }
}
```

> Se a função tem mais de um `return`, coloque o `END` antes de **cada** um. Senão o GPIO fica em 1.

### Stack (só FreeRTOS)
1. Antes do include, coloque `#define METRICS_TIMING 0` e `#define METRICS_STACK 1`
   (não meça stack junto com tempo: o `printf` atrapalha a medição). Depois, `#include "metrics_pins.h"`.
2. No `FreeRTOSConfig.h`, coloque `#define INCLUDE_uxTaskGetStackHighWaterMark 1`.
3. Crie o monitor:

```c
TaskHandle_t h_mpu;
static const metrics_stack_entry_t stack_list[] = {
    { &h_mpu, "mpu_task", 4096 },     // mesmo nome do medir.py, mesmo tamanho do xTaskCreate
    { NULL, NULL, 0 }
};
xTaskCreate(mpu_task, "mpu", 4096, NULL, 2, &h_mpu);
METRICS_START_STACK_MONITOR(stack_list);
```

O firmware imprime `[STACK] mpu_task hwm=... size=...` a cada 1 s. No `medir.py`, use **[s]** e cole essas linhas.

---

## Problemas comuns

| Mensagem / sintoma | O que fazer |
|---|---|
| `Nao conectou no Logic 2` | Abra o Logic 2 e ligue **Automation → Automation Server** |
| `não encontrou o Saleae` | Cabo USB. No topo do Logic 2 tem que estar "Connected" |
| `SEM SINAL` | O GPIO não mexeu: a placa não está rodando, o código não foi instrumentado, o GPIO do código é diferente do configurado ou o fio está no canal errado |
| Sinal sempre em 1 | Falta o `END` em algum caminho (ex: um `return` no meio da função) |
| `RUÍDO?` / pulsos de 0,1 µs | Falta o **GND comum**. Ou o `START`/`END` estão colados, sem código entre eles |
| Erro de taxa de amostragem | Seu Saleae não aceita essa taxa. Use **[e]** e tente 12.5, 25 ou 50 |
| Miss rate alto com tudo certo | Período errado na config. Use **[e]** para corrigir e **[r]** para recalcular, sem capturar de novo |
| `pip` / `python` não encontrado | Instale o Python marcando **"Add to PATH"** e reabra o VS Code |

**Testar sem hardware:** `python analisar.py exemplo` analisa uma captura real que vem no repositório.

---

## Extras

### Comandos diretos (sem menu)

```bash
python capturar.py --nome teste             # captura + análise usando o config.json
python analisar.py capturas/<pasta>         # recalcula uma captura
python analisar.py capturas/<pasta> --graficos timeline,resumo
python comparar.py capturas/<A> capturas/<B>
```

Sem a Automation: no Logic 2, use **File → Export Data → CSV** (canais digitais) e rode `python analisar.py <pasta>`.

### Extensão para dentro do Logic 2 (opcional)

[`extensao-logic2/`](extensao-logic2/) tem uma extensão de medição que mostra as mesmas métricas (um
canal por vez) direto no Logic 2:

1. No Logic 2, abra o painel **Extensions** (barra lateral direita).
2. Clique em **⋮** → **Load Existing Extension…** e selecione `extensao-logic2/extension.json`.
3. Selecione um trecho de um canal com **Shift + arrastar**. As métricas "Timing Metrics" aparecem na caixa de medição.

---

## Estrutura

```
├── medir.py             # ← comece por aqui
├── analisar.py          # cálculo das métricas e gráficos
├── capturar.py          # captura pelo Logic 2 (Automation API)
├── comparar.py          # comparação entre capturas
├── firmware/
│   └── rtos_metrics.h   # macros C para instrumentar tasks/funções (GPIO 1/0 + stack)
├── extensao-logic2/     # extensão opcional para dentro do Logic 2
├── exemplo/             # captura real para testar sem hardware
└── requirements.txt
```
