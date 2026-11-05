/*
 * rtos_metrics.h - instrumentacao de tempo (GPIO) para medir tasks do FreeRTOS ou funcoes
 * bare metal com o Saleae, e stack das tasks. Feito para Raspberry Pi Pico / Pico 2 (pico-sdk).
 * Para outra placa, troque so as 3 macros METRICS_GPIO_* abaixo.
 *
 * Uso:
 *   #define METRICS_BARE_METAL 1  // so em projeto SEM FreeRTOS
 *   #define METRICS_TIMING 1      // 1 = mede tempo pelos pinos (desligue para medir stack)
 *   #define METRICS_STACK  0      // 1 = imprime o high water mark (so FreeRTOS)
 *   #include "rtos_metrics.h"
 *
 * Veja o README para o exemplo completo.
 */
#ifndef RTOS_METRICS_H
#define RTOS_METRICS_H

#ifndef METRICS_BARE_METAL
#define METRICS_BARE_METAL 0
#endif

#include <stdio.h>
#if !METRICS_BARE_METAL
#include "FreeRTOS.h"
#include "task.h"
#endif

#ifndef METRICS_TIMING
#define METRICS_TIMING 1
#endif
#ifndef METRICS_STACK
#define METRICS_STACK 0
#endif

/* ---------------------------------------------------------------- tempo (GPIO) */
#if METRICS_TIMING
#include "hardware/gpio.h"
#define METRICS_GPIO_INIT(pin) do { gpio_init(pin); gpio_set_dir(pin, GPIO_OUT); gpio_put(pin, 0); } while (0)
#define METRICS_GPIO_SET(pin)  gpio_put(pin, 1)
#define METRICS_GPIO_CLR(pin)  gpio_put(pin, 0)
#else
#define METRICS_GPIO_INIT(pin) ((void)0)
#define METRICS_GPIO_SET(pin)  ((void)0)
#define METRICS_GPIO_CLR(pin)  ((void)0)
#endif

/* Inicializa uma lista de pinos:  METRICS_INIT_PINS(10, 11, 12, 13); */
#define METRICS_INIT_PINS(...) do {                                           \
        const unsigned _p[] = {__VA_ARGS__};                                  \
        for (unsigned _i = 0; _i < sizeof(_p) / sizeof(_p[0]); _i++)          \
            METRICS_GPIO_INIT(_p[_i]);                                        \
    } while (0)

/* Task: logo DEPOIS do ponto de bloqueio (vTaskDelay, xQueueReceive...) */
#define METRICS_TASK_START(pin) METRICS_GPIO_SET(pin)
/* Task: logo ANTES de bloquear de novo */
#define METRICS_TASK_END(pin)   METRICS_GPIO_CLR(pin)

/* Funcao bare metal: primeira e ultima linha da funcao (GPIO = 1 no inicio, 0 no fim) */
#define METRICS_FUNC_START(pin) METRICS_GPIO_SET(pin)
#define METRICS_FUNC_END(pin)   METRICS_GPIO_CLR(pin)

/* ---------------------------------------------------------------- stack (so FreeRTOS) */
#if !METRICS_BARE_METAL
/* Precisa de  #define INCLUDE_uxTaskGetStackHighWaterMark 1  no FreeRTOSConfig.h */
typedef struct {
    TaskHandle_t *handle;   /* endereco do handle preenchido pelo xTaskCreate */
    const char   *nome;     /* MESMO nome usado no config_tasks.json           */
    uint32_t      size;     /* tamanho de stack passado no xTaskCreate (words) */
} metrics_stack_entry_t;

#if METRICS_STACK
/* Task que imprime, a cada 1 s:  [STACK] <nome> hwm=<livre> size=<total>
 * Crie passando um vetor terminado em {NULL, NULL, 0}. */
static void metrics_stack_task(void *param) {
    const metrics_stack_entry_t *lista = (const metrics_stack_entry_t *)param;
    for (;;) {
        for (const metrics_stack_entry_t *e = lista; e->handle != NULL; e++) {
            if (*e->handle != NULL) {
                printf("[STACK] %s hwm=%u size=%u\n", e->nome,
                       (unsigned)uxTaskGetStackHighWaterMark(*e->handle), (unsigned)e->size);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
#define METRICS_START_STACK_MONITOR(lista) \
    xTaskCreate(metrics_stack_task, "metrics_stack", 1024, (void *)(lista), tskIDLE_PRIORITY + 1, NULL)
#else
#define METRICS_START_STACK_MONITOR(lista) ((void)(lista))
#endif
#endif /* !METRICS_BARE_METAL */

#endif /* RTOS_METRICS_H */
