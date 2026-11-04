"""Carregamento do modelo YOLO e execução da inferência.

As dependências pesadas são importadas apenas quando necessário, de modo que os
demais módulos do projeto possam ser testados sem instalá-las.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avaliacao import Predicao
from dataset import Caixa


class ErroModelo(Exception):
    pass


@dataclass
class ResumoInferencia:
    """Registro do custo da inferência, usado no relatório."""

    imagens: int = 0
    segundos: float = 0.0

    @property
    def quadros_por_segundo(self) -> float:
        return self.imagens / self.segundos if self.segundos > 0 else 0.0

    @property
    def milissegundos_por_imagem(self) -> float:
        return 1000 * self.segundos / self.imagens if self.imagens else 0.0


def carregar_modelo(pesos: str) -> Any:
    """Carrega os pesos do YOLO, baixando-os na primeira execução."""
    try:
        from ultralytics import YOLO
    except ImportError as erro:
        raise ErroModelo(
            "Dependências ausentes. Instale com "
            "'pip install -r requirements.txt'."
        ) from erro
    try:
        return YOLO(pesos)
    except Exception as erro:  # noqa: BLE001
        raise ErroModelo(
            f"Não foi possível carregar os pesos '{pesos}'. Verifique o nome do "
            "arquivo e o acesso à internet na primeira execução."
        ) from erro


def _predicoes_do_resultado(
    resultado: Any, classes_de_interesse: set[int]
) -> list[Predicao]:
    caixas = resultado.boxes
    if caixas is None or len(caixas) == 0:
        return []
    coordenadas = caixas.xyxy.tolist()
    classes = caixas.cls.tolist()
    confiancas = caixas.conf.tolist()
    predicoes: list[Predicao] = []
    for coordenada, classe, confianca in zip(
        coordenadas, classes, confiancas, strict=True
    ):
        identificador = int(classe)
        if identificador not in classes_de_interesse:
            continue
        x1, y1, x2, y2 = (float(valor) for valor in coordenada)
        predicoes.append(
            Predicao(
                classe=identificador,
                confianca=float(confianca),
                caixa=Caixa(x1, y1, x2, y2),
            )
        )
    return predicoes


def inferir(
    modelo: Any,
    caminhos: list[Path],
    classes_de_interesse: set[int],
    confianca_minima: float,
    tamanho: int,
    lote: int = 16,
    progresso: bool = True,
) -> tuple[list[list[Predicao]], ResumoInferencia]:
    """Executa a inferência sobre as imagens, em lotes.

    O filtro de classes é aplicado na própria chamada ao modelo, o que suprime
    as classes do COCO alheias ao domínio antes da supressão não máxima, e é
    reaplicado sobre o resultado por segurança.
    """
    classes = sorted(classes_de_interesse)
    predicoes: list[list[Predicao]] = []
    resumo = ResumoInferencia()

    for inicio in range(0, len(caminhos), lote):
        bloco = caminhos[inicio : inicio + lote]
        marca = time.perf_counter()
        try:
            resultados = modelo.predict(
                source=[str(caminho) for caminho in bloco],
                imgsz=tamanho,
                conf=confianca_minima,
                classes=classes,
                verbose=False,
            )
        except Exception as erro:  # noqa: BLE001
            raise ErroModelo(f"Falha durante a inferência: {erro}") from erro
        resumo.segundos += time.perf_counter() - marca
        resumo.imagens += len(bloco)
        for resultado in resultados:
            predicoes.append(
                _predicoes_do_resultado(resultado, classes_de_interesse)
            )
        if progresso:
            print(
                f"  inferência: {min(inicio + lote, len(caminhos))}/{len(caminhos)}",
                end="\r",
                flush=True,
            )

    if progresso:
        print(" " * 60, end="\r")
    return predicoes, resumo
