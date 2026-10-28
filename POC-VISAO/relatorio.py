"""Formatação e gravação dos resultados da avaliação."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from avaliacao import MetricasClasse, media_das_precisoes
from mapeamento import nome_da_classe


def tabela(metricas: dict[int, MetricasClasse]) -> str:
    """Monta a tabela de métricas por classe para exibição no terminal."""
    cabecalho = (
        f"{'classe':<12}{'refs':>7}{'VP':>7}{'FP':>7}{'FN':>7}"
        f"{'precisão':>11}{'revocação':>11}{'F1':>8}{'AP@0,5':>9}"
    )
    linhas = [cabecalho, "-" * len(cabecalho)]
    for classe in sorted(metricas, key=lambda c: nome_da_classe(c)):
        item = metricas[classe]
        linhas.append(
            f"{nome_da_classe(classe):<12}"
            f"{item.referencias:>7}"
            f"{item.verdadeiros_positivos:>7}"
            f"{item.falsos_positivos:>7}"
            f"{item.falsos_negativos:>7}"
            f"{item.precisao:>11.3f}"
            f"{item.revocacao:>11.3f}"
            f"{item.f1:>8.3f}"
            f"{item.ap:>9.3f}"
        )
    linhas.append("-" * len(cabecalho))
    linhas.append(f"{'mAP@0,5':<12}{media_das_precisoes(metricas):>58.3f}")
    return "\n".join(linhas)


def tabela_por_atributo(
    recortes: dict[str, dict[int, MetricasClasse]],
) -> str:
    """Monta a tabela de mAP por condição de captura."""
    linhas = [f"{'condição':<28}{'anotações':>11}{'mAP@0,5':>10}", "-" * 49]
    for nome in sorted(recortes):
        metricas = recortes[nome]
        referencias = sum(item.referencias for item in metricas.values())
        linhas.append(
            f"{nome:<28}{referencias:>11}{media_das_precisoes(metricas):>10.3f}"
        )
    return "\n".join(linhas)


def gravar_json(caminho: Path, conteudo: dict[str, Any]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(conteudo, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def gravar_csv(caminho: Path, metricas: dict[int, MetricasClasse]) -> None:
    """Grava as métricas por classe em CSV, para uso direto no texto."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            [
                "classe",
                "referencias",
                "verdadeiros_positivos",
                "falsos_positivos",
                "falsos_negativos",
                "precisao",
                "revocacao",
                "f1",
                "ap",
            ]
        )
        for classe in sorted(metricas, key=lambda c: nome_da_classe(c)):
            item = metricas[classe]
            escritor.writerow(
                [
                    nome_da_classe(classe),
                    item.referencias,
                    item.verdadeiros_positivos,
                    item.falsos_positivos,
                    item.falsos_negativos,
                    f"{item.precisao:.4f}",
                    f"{item.revocacao:.4f}",
                    f"{item.f1:.4f}",
                    f"{item.ap:.4f}",
                ]
            )


def montar_relatorio(
    parametros: dict[str, Any],
    metricas: dict[int, MetricasClasse],
    map_por_iou: dict[float, float],
    recortes: dict[str, dict[int, MetricasClasse]],
    exclusoes: dict[str, int],
    custo: dict[str, Any],
) -> dict[str, Any]:
    """Reúne em um único dicionário tudo o que descreve a execução."""
    return {
        "executado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "parametros": parametros,
        "custo_computacional": custo,
        "metricas_por_classe": {
            nome_da_classe(classe): asdict(item)
            for classe, item in metricas.items()
        },
        "map_05": media_das_precisoes(metricas),
        "map_por_limiar_de_iou": {str(k): v for k, v in map_por_iou.items()},
        "map_05_095": (
            sum(map_por_iou.values()) / len(map_por_iou) if map_por_iou else 0.0
        ),
        "map_por_condicao": {
            nome: media_das_precisoes(item) for nome, item in recortes.items()
        },
        "anotacoes_excluidas_por_ausencia_de_equivalente": exclusoes,
    }
