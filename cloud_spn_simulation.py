#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
 Modelagem e Avaliação de Desempenho com SPN — Computação em Nuvem
=============================================================================
 Disciplina: Sistemas Distribuídos
 Contexto  : Computação em Nuvem com Máquinas Virtuais (VMs)

 Arquitetura do Sistema:
   Carga (Poisson λ) → Buffer Limitado (C_VM) → Pool de VMs (N_VM, μ_VM) → Saída / Descarte

 Modelo SPN Canônico:
   Places:
     P_Chegada    — Fonte contínua de requisições
     P_Entrada    — Requisição em admissão
     P_Capacidade — Capacidade disponível no buffer (inicia com C_VM tokens)
     P_Fila       — Requisições aguardando VM livre
     P_VMLivre    — VMs disponíveis (inicia com N_VM tokens)
     P_EmProcesso — Tarefas em execução paralela nas VMs
     P_Descarte   — Requisições descartadas por saturação (sink)
     P_Concluido  — Requisições concluídas com sucesso (sink)

   Transitions:
     T_Chegada    — (temporizada, taxa λ) geração de requisições
     T_Aceita     — (imediata) admite na fila se P_Capacidade > 0
     T_Descarta   — (imediata) descarta se P_Capacidade == 0 (arco inibidor)
     T_Inicio     — (imediata) aloca VM ociosa para tarefa da fila
     T_Servico    — (temporizada, taxa μ_VM) processamento nas VMs

 Métricas avaliadas:
   TP   — Throughput (Vazão do sistema) [tarefas/ms]
   MRT  — Mean Response Time (Tempo Médio de Resposta) [ms]
   MQT  — Mean Queue Time (Tempo Médio de Fila) [ms]
   U_VM — Utilização do Pool de VMs [%]
   DP   — Drop Probability (Probabilidade de Descarte) [%]
=============================================================================
"""

import os
import simpy
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÃO GLOBAL
# ─────────────────────────────────────────────────────────────────────────────

SIM_TIME = 2_000_000   # Tempo de simulação (ms)
N_RUNS   = 7           # Replicações independentes por ponto
OUTPUT   = "resultados"

os.makedirs(OUTPUT, exist_ok=True)

# Cenário de Referência
REF = {
    'lambda': 0.08,   # Taxa de chegada  [tarefas/ms]
    'mu_vm':  0.08,   # Taxa de serviço por VM [tarefas/ms] (atraso médio = 12.5 ms)
    'n_vm':   3,      # Número de VMs
    'c_vm':   20,     # Capacidade do buffer de espera
}

# Paleta de cores para gráficos
COLORS  = ['#2563EB', '#DC2626', '#059669', '#7C3AED', '#D97706']
MARKERS = ['o', 's', '^', 'D', 'v']

# ─────────────────────────────────────────────────────────────────────────────
# NÚCLEO DA SIMULAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

def run_simulation(params: dict, seed: int = 42) -> dict:
    """
    Executa uma replicação da simulação do sistema em nuvem com buffer finito.
    Retorna dicionário com métricas: TP, MRT, MQT, U_VM, DP.
    """
    env = simpy.Environment()
    rng = np.random.RandomState(seed)

    vm = simpy.Resource(env, capacity=params['n_vm'])

    n_arrived   = [0]
    n_completed = [0]
    n_dropped   = [0]
    vm_busy_acc = [0.0]
    resp_times  = []
    queue_times = []

    def task_process(arrival_time: float):
        # Controle de buffer: se a fila atingir c_vm, descarta imediatamente
        if len(vm.queue) >= params['c_vm']:
            n_dropped[0] += 1
            return

        with vm.request() as req:
            yield req
            # Tempo de espera na fila
            q_wait = env.now - arrival_time
            queue_times.append(q_wait)

            t0 = env.now
            yield env.timeout(rng.exponential(1.0 / params['mu_vm']))
            vm_busy_acc[0] += env.now - t0

        # Conclusão bem-sucedida
        n_completed[0] += 1
        resp_times.append(env.now - arrival_time)

    def arrival_process():
        while True:
            yield env.timeout(rng.exponential(1.0 / params['lambda']))
            n_arrived[0] += 1
            env.process(task_process(env.now))

    env.process(arrival_process())
    env.run(until=SIM_TIME)

    T = SIM_TIME
    tp   = n_completed[0] / T
    mrt  = float(np.mean(resp_times)) if resp_times else 0.0
    mqt  = float(np.mean(queue_times)) if queue_times else 0.0
    u_vm = vm_busy_acc[0] / (T * params['n_vm']) * 100.0
    dp   = n_dropped[0]  / max(n_arrived[0], 1) * 100.0

    return {'TP': tp, 'MRT': mrt, 'MQT': mqt, 'U_VM': u_vm, 'DP': dp}


def run_replications(params: dict, n_runs: int = N_RUNS) -> dict:
    """Executa N_RUNS replicações, calculando média e desvio padrão para IC 95%."""
    results = [run_simulation(params, seed=s * 23 + 7) for s in range(n_runs)]
    summary = {}
    for key in results[0]:
        vals = [r[key] for r in results]
        summary[key] = {'mean': float(np.mean(vals)), 'std': float(np.std(vals))}
    return summary


def means(rep_results, metric):
    return np.array([r[metric]['mean'] for r in rep_results])

def stds(rep_results, metric):
    return np.array([r[metric]['std'] for r in rep_results])


# ─────────────────────────────────────────────────────────────────────────────
# E1 — Variação da Taxa de Chegada (5 níveis)
# ─────────────────────────────────────────────────────────────────────────────

print("=" * 65)
print("E1 — Taxa de Chegada (5 níveis de demanda)")
print("=" * 65)

E1_LAMBDAS = [0.04, 0.08, 0.12, 0.18, 0.24]
e1_results = []
for lam in E1_LAMBDAS:
    res = run_replications({**REF, 'lambda': lam})
    e1_results.append(res)
    print(f"  λ={lam:.2f} | TP={res['TP']['mean']:.4f} | "
          f"MRT={res['MRT']['mean']:.2f}ms | "
          f"U_VM={res['U_VM']['mean']:.1f}% | DP={res['DP']['mean']:.1f}%")

# ─────────────────────────────────────────────────────────────────────────────
# E2 — Capacidade de Processamento (3 configurações de N_VM)
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 65)
print("E2 — Capacidade de Processamento (N_VM)")
print("=" * 65)

E2_NVM    = [2, 3, 5]
E2_LABELS = ['Config A — 2 VMs', 'Config B — 3 VMs (Ref)', 'Config C — 5 VMs']
e2_all    = []
for n_vm in E2_NVM:
    row = [run_replications({**REF, 'lambda': lam, 'n_vm': n_vm})
           for lam in E1_LAMBDAS]
    e2_all.append(row)
    r = row[1]  # cenário de referência λ=0.08
    print(f"  N_VM={n_vm} (λ=0.08) | TP={r['TP']['mean']:.4f} | "
          f"MRT={r['MRT']['mean']:.2f}ms | U={r['U_VM']['mean']:.1f}% | DP={r['DP']['mean']:.1f}%")

# ─────────────────────────────────────────────────────────────────────────────
# E3 — Capacidade da Fila (3 limites de C_VM)
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 65)
print("E3 — Capacidade da Fila de VMs (C_VM)")
print("=" * 65)

E3_CVM    = [5, 20, 50]
E3_LABELS = ['Config X — C_VM=5', 'Config Y — C_VM=20 (Ref)', 'Config Z — C_VM=50']
e3_all    = []
for c_vm in E3_CVM:
    row = [run_replications({**REF, 'lambda': lam, 'c_vm': c_vm})
           for lam in E1_LAMBDAS]
    e3_all.append(row)
    r = row[4]  # saturação máxima λ=0.24
    print(f"  C_VM={c_vm:2d} (λ=0.24) | DP={r['DP']['mean']:.1f}% | "
          f"MRT={r['MRT']['mean']:.2f}ms")

# ─────────────────────────────────────────────────────────────────────────────
# E4 — Demanda × Recursos Combinados (3 cenários)
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 65)
print("E4 — Cenários Combinados")
print("=" * 65)

E4_SCENARIOS = [
    {'lambda': 0.04, 'n_vm': 2, 'c_vm':  5, 'label': 'Cenário I\n(Baixa Carga)'},
    {'lambda': 0.08, 'n_vm': 3, 'c_vm': 20, 'label': 'Cenário II\n(Referência)'},
    {'lambda': 0.20, 'n_vm': 5, 'c_vm': 50, 'label': 'Cenário III\n(Alta Carga)'},
]
e4_results = []
for sc in E4_SCENARIOS:
    res = run_replications({**REF, 'lambda': sc['lambda'],
                            'n_vm': sc['n_vm'], 'c_vm': sc['c_vm']})
    e4_results.append(res)
    print(f"  {sc['label'].replace(chr(10), ' ')}")
    print(f"    TP={res['TP']['mean']:.4f} tarefas/ms | MRT={res['MRT']['mean']:.2f}ms | "
          f"U_VM={res['U_VM']['mean']:.1f}% | DP={res['DP']['mean']:.1f}%\n")

# ─────────────────────────────────────────────────────────────────────────────
# GERAÇÃO DE GRÁFICOS (4-PANEL COM TP, MRT, U, DP)
# ─────────────────────────────────────────────────────────────────────────────

plt.rcParams.update({
    'font.size': 10, 'axes.titlesize': 11, 'axes.labelsize': 10,
    'legend.fontsize': 8.5, 'figure.dpi': 300, 'axes.grid': True,
    'grid.alpha': 0.3,
})

x       = np.array(E1_LAMBDAS)
x_ticks = [f"{v:.2f}" for v in E1_LAMBDAS]
PLOT_METRICS = [
    ('TP',   'Vazão do Sistema TP (tarefas/ms)'),
    ('MRT',  'Tempo Médio de Resposta MRT (ms)'),
    ('U_VM', 'Utilização do Pool de VMs U (%)'),
    ('DP',   'Probabilidade de Descarte DP (%)'),
]


def make_4panel(title, datasets, labels, filename):
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), dpi=300)
    fig.suptitle(title, fontsize=12, fontweight='bold')
    for idx, (metric, ylabel) in enumerate(PLOT_METRICS):
        ax = axes[idx // 2][idx % 2]
        for i, (data, label) in enumerate(zip(datasets, labels)):
            ax.errorbar(x, means(data, metric), yerr=stds(data, metric),
                        color=COLORS[i], marker=MARKERS[i],
                        linewidth=2, markersize=6, capsize=4,
                        elinewidth=1.2, label=label)
        ax.set_xlabel('Taxa de Chegada λ (tarefas/ms)')
        ax.set_ylabel(ylabel)
        ax.set_xticks(x)
        ax.set_xticklabels(x_ticks)
        ax.legend(frameon=True, facecolor='white', framealpha=0.9)
    plt.tight_layout()
    fig.savefig(filename, bbox_inches='tight')
    print(f"[OK] Gráfico salvo: {filename}")
    plt.close(fig)


# Figura E1
make_4panel(
    'E1 — Variação da Demanda λ (N_VM=3, C_VM=20)',
    [e1_results], ['Cenário de Referência'],
    f"{OUTPUT}/E1_taxa_chegada.png"
)

# Figura E2
make_4panel(
    'E2 — Variação da Capacidade de Processamento N_VM (C_VM=20)',
    e2_all, E2_LABELS,
    f"{OUTPUT}/E2_capacidade_processamento.png"
)

# Figura E3
make_4panel(
    'E3 — Variação da Capacidade do Buffer C_VM (N_VM=3)',
    e3_all, E3_LABELS,
    f"{OUTPUT}/E3_capacidade_fila.png"
)

# Figura E4 — Barras comparativas
fig, axes = plt.subplots(1, 4, figsize=(14, 3.8), dpi=300)
fig.suptitle('E4 — Desempenho nos Cenários Combinados I, II e III',
             fontsize=12, fontweight='bold')
e4_x = np.arange(3)
e4_xlabels = [sc['label'] for sc in E4_SCENARIOS]

for idx, (metric, ylabel) in enumerate(PLOT_METRICS):
    ax   = axes[idx]
    vals = [r[metric]['mean'] for r in e4_results]
    errs = [r[metric]['std']  for r in e4_results]
    bars = ax.bar(e4_x, vals, yerr=errs, color=COLORS[:3],
                  capsize=5, edgecolor='#1E293B', linewidth=0.8, alpha=0.9)
    ax.set_xticks(e4_x)
    ax.set_xticklabels(e4_xlabels, fontsize=8.5)
    ax.set_ylabel(ylabel)
    for bar, val in zip(bars, vals):
        fmt = f'{val:.4f}' if metric == 'TP' else f'{val:.1f}'
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.02,
                fmt, ha='center', va='bottom', fontsize=8, fontweight='bold')

plt.tight_layout()
fig.savefig(f"{OUTPUT}/E4_combinado.png", bbox_inches='tight')
print(f"[OK] Gráfico salvo: {OUTPUT}/E4_combinado.png")
plt.close(fig)

# ─────────────────────────────────────────────────────────────────────────────
# TABELA CSV CONSOLIDADA
# ─────────────────────────────────────────────────────────────────────────────

rows = []
for lam, res in zip(E1_LAMBDAS, e1_results):
    rows.append({'Exp': 'E1', 'lambda': lam, 'N_VM': REF['n_vm'], 'C_VM': REF['c_vm'],
                 'TP': round(res['TP']['mean'], 5), 'MRT': round(res['MRT']['mean'], 2),
                 'MQT': round(res['MQT']['mean'], 2), 'U_VM': round(res['U_VM']['mean'], 2),
                 'DP': round(res['DP']['mean'], 2)})

for sc, res in zip(E4_SCENARIOS, e4_results):
    label_short = sc['label'].split('\n')[0]
    rows.append({'Exp': 'E4', 'lambda': sc['lambda'], 'N_VM': sc['n_vm'], 'C_VM': sc['c_vm'],
                 'TP': round(res['TP']['mean'], 5), 'MRT': round(res['MRT']['mean'], 2),
                 'MQT': round(res['MQT']['mean'], 2), 'U_VM': round(res['U_VM']['mean'], 2),
                 'DP': round(res['DP']['mean'], 2)})

pd.DataFrame(rows).to_csv(f"{OUTPUT}/resultados_consolidados.csv", index=False)
print(f"[OK] Tabela consolidada salva: {OUTPUT}/resultados_consolidados.csv")

print("\n" + "=" * 65)
print("SIMULAÇÕES CONCLUÍDAS COM SUCESSO! Resultados prontos.")
print("=" * 65)
