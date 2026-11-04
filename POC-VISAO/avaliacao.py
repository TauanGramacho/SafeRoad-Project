"""Métricas de avaliação de detecção de objetos.

Implementa o pareamento entre detecções e anotações de referência por
sobreposição (IoU) e o cálculo das métricas usuais da área: precisão, revocação,
pontuação F1 e precisão média (AP), esta última por interpolação em todos os
pontos da curva, conforme a convenção adotada desde o PASCAL VOC 2010 e mantida
no COCO.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dataset import Anotacao, Caixa


@dataclass(frozen=True)
class Predicao:
    """Detecção produzida pelo modelo."""

    classe: int
    confianca: float
    caixa: Caixa


@dataclass
class ResultadoImagem:
    """Predições e referências de uma única imagem."""

    indice: int
    predicoes: list[Predicao] = field(default_factory=list)
    referencias: list[Anotacao] = field(default_factory=list)
    atributos: dict[str, str] = field(default_factory=dict)


@dataclass
class MetricasClasse:
    """Métricas de uma classe isolada."""

    classe: int
    referencias: int
    predicoes: int
    verdadeiros_positivos: int
    falsos_positivos: int
    falsos_negativos: int
    precisao: float
    revocacao: float
    f1: float
    ap: float


def interseccao_sobre_uniao(primeira: Caixa, segunda: Caixa) -> float:
    """Razão entre a área de interseção e a área de união de duas caixas."""
    x1 = max(primeira.x1, segunda.x1)
    y1 = max(primeira.y1, segunda.y1)
    x2 = min(primeira.x2, segunda.x2)
    y2 = min(primeira.y2, segunda.y2)
    largura = x2 - x1
    altura = y2 - y1
    if largura <= 0 or altura <= 0:
        return 0.0
    interseccao = largura * altura
    uniao = primeira.area + segunda.area - interseccao
    if uniao <= 0:
        return 0.0
    return interseccao / uniao


def _precisao_media(recalls: list[float], precisoes: list[float]) -> float:
    """Área sob a curva de precisão e revocação, interpolada em todos os pontos."""
    if not recalls:
        return 0.0
    rec = [0.0, *recalls, 1.0]
    pre = [0.0, *precisoes, 0.0]
    for indice in range(len(pre) - 2, -1, -1):
        pre[indice] = max(pre[indice], pre[indice + 1])
    area = 0.0
    for indice in range(len(rec) - 1):
        delta = rec[indice + 1] - rec[indice]
        if delta > 0:
            area += delta * pre[indice + 1]
    return area


def avaliar_classe(
    resultados: list[ResultadoImagem],
    classe: int,
    iou_minimo: float,
    confianca_operacional: float,
) -> MetricasClasse:
    """Calcula as métricas de uma classe sobre todo o conjunto."""
    referencias_por_imagem: dict[int, list[Caixa]] = {}
    total_referencias = 0
    for resultado in resultados:
        caixas = [
            anotacao.caixa
            for anotacao in resultado.referencias
            if anotacao.classe == classe
        ]
        referencias_por_imagem[resultado.indice] = caixas
        total_referencias += len(caixas)

    candidatas: list[tuple[float, int, Caixa]] = []
    for resultado in resultados:
        for predicao in resultado.predicoes:
            if predicao.classe == classe:
                candidatas.append(
                    (predicao.confianca, resultado.indice, predicao.caixa)
                )
    # Ordem decrescente de confiança: a detecção mais confiante reivindica
    # primeiro a anotação correspondente.
    candidatas.sort(key=lambda item: item[0], reverse=True)

    pareadas: dict[int, set[int]] = {
        indice: set() for indice in referencias_por_imagem
    }
    acertos: list[int] = []
    confiancas: list[float] = []
    for confianca, indice_imagem, caixa in candidatas:
        disponiveis = referencias_por_imagem.get(indice_imagem, [])
        melhor_iou = 0.0
        melhor_indice = -1
        for posicao, referencia in enumerate(disponiveis):
            if posicao in pareadas[indice_imagem]:
                continue
            valor = interseccao_sobre_uniao(caixa, referencia)
            if valor > melhor_iou:
                melhor_iou = valor
                melhor_indice = posicao
        if melhor_iou >= iou_minimo and melhor_indice >= 0:
            pareadas[indice_imagem].add(melhor_indice)
            acertos.append(1)
        else:
            acertos.append(0)
        confiancas.append(confianca)

    recalls: list[float] = []
    precisoes: list[float] = []
    acumulado_vp = 0
    acumulado_fp = 0
    for posicao, acerto in enumerate(acertos):
        acumulado_vp += acerto
        acumulado_fp += 1 - acerto
        precisoes.append(acumulado_vp / (acumulado_vp + acumulado_fp))
        recalls.append(
            acumulado_vp / total_referencias if total_referencias else 0.0
        )
        del posicao
    ap = _precisao_media(recalls, precisoes) if total_referencias else 0.0

    # Ponto de operação: considera apenas as detecções acima do limiar usual.
    vp_operacional = sum(
        acerto
        for acerto, confianca in zip(acertos, confiancas, strict=True)
        if confianca >= confianca_operacional
    )
    total_operacional = sum(
        1 for confianca in confiancas if confianca >= confianca_operacional
    )
    fp_operacional = total_operacional - vp_operacional
    fn_operacional = total_referencias - vp_operacional
    precisao = vp_operacional / total_operacional if total_operacional else 0.0
    revocacao = vp_operacional / total_referencias if total_referencias else 0.0
    f1 = (
        2 * precisao * revocacao / (precisao + revocacao)
        if (precisao + revocacao) > 0
        else 0.0
    )

    return MetricasClasse(
        classe=classe,
        referencias=total_referencias,
        predicoes=total_operacional,
        verdadeiros_positivos=vp_operacional,
        falsos_positivos=fp_operacional,
        falsos_negativos=fn_operacional,
        precisao=precisao,
        revocacao=revocacao,
        f1=f1,
        ap=ap,
    )


def avaliar(
    resultados: list[ResultadoImagem],
    classes: list[int],
    iou_minimo: float,
    confianca_operacional: float,
) -> dict[int, MetricasClasse]:
    """Calcula as métricas de cada classe informada."""
    return {
        classe: avaliar_classe(
            resultados, classe, iou_minimo, confianca_operacional
        )
        for classe in classes
    }


# Faixas de porte do COCO, em área de pixels.
FAIXAS_DE_PORTE: dict[str, tuple[float, float]] = {
    "pequeno": (0.0, 32.0 * 32.0),
    "medio": (32.0 * 32.0, 96.0 * 96.0),
    "grande": (96.0 * 96.0, float("inf")),
}


def filtrar_por_tamanho(
    resultados: list[ResultadoImagem], area_minima: float, area_maxima: float
) -> list[ResultadoImagem]:
    """Restringe referências e predições a uma faixa de área.

    Permite reportar o desempenho por porte de objeto, como faz o COCO, o que é
    necessário para distinguir a falha de detecção da simples insuficiência de
    resolução. Tanto as referências quanto as predições são filtradas, de modo
    que a métrica resultante responde à pergunta: entre os objetos deste porte,
    quantos o modelo encontrou?
    """
    recortados: list[ResultadoImagem] = []
    for resultado in resultados:
        recortados.append(
            ResultadoImagem(
                indice=resultado.indice,
                predicoes=[
                    predicao
                    for predicao in resultado.predicoes
                    if area_minima <= predicao.caixa.area < area_maxima
                ],
                referencias=[
                    anotacao
                    for anotacao in resultado.referencias
                    if area_minima <= anotacao.caixa.area < area_maxima
                ],
                atributos=resultado.atributos,
            )
        )
    return recortados


def filtrar_por_lado_minimo(
    resultados: list[ResultadoImagem], lado_minimo: float
) -> tuple[list[ResultadoImagem], int, int]:
    """Descarta objetos cujo menor lado fique abaixo do limite informado.

    O descarte alcança tanto as referências quanto as predições, de modo que
    objetos pequenos não se convertam em falsos positivos ao serem detectados
    nem em falsos negativos ao não serem. Devolve, além dos resultados
    recortados, quantas referências e predições foram descartadas, informação
    que deve constar do relatório por delimitar o universo avaliado.
    """
    if lado_minimo <= 0:
        return resultados, 0, 0

    def grande_o_bastante(caixa: Caixa) -> bool:
        return (
            min(caixa.x2 - caixa.x1, caixa.y2 - caixa.y1) >= lado_minimo
        )

    recortados: list[ResultadoImagem] = []
    referencias_descartadas = 0
    predicoes_descartadas = 0
    for resultado in resultados:
        referencias = [
            anotacao
            for anotacao in resultado.referencias
            if grande_o_bastante(anotacao.caixa)
        ]
        predicoes = [
            predicao
            for predicao in resultado.predicoes
            if grande_o_bastante(predicao.caixa)
        ]
        referencias_descartadas += len(resultado.referencias) - len(referencias)
        predicoes_descartadas += len(resultado.predicoes) - len(predicoes)
        recortados.append(
            ResultadoImagem(
                indice=resultado.indice,
                predicoes=predicoes,
                referencias=referencias,
                atributos=resultado.atributos,
            )
        )
    return recortados, referencias_descartadas, predicoes_descartadas


def avaliar_por_porte(
    resultados: list[ResultadoImagem],
    classes: list[int],
    iou_minimo: float,
    confianca_operacional: float,
) -> dict[str, dict[int, MetricasClasse]]:
    """Calcula as métricas separadamente para cada porte de objeto."""
    return {
        nome: avaliar(
            filtrar_por_tamanho(resultados, minima, maxima),
            classes,
            iou_minimo,
            confianca_operacional,
        )
        for nome, (minima, maxima) in FAIXAS_DE_PORTE.items()
    }


def media_das_precisoes(metricas: dict[int, MetricasClasse]) -> float:
    """Média das precisões médias (mAP), restrita às classes com referências."""
    presentes = [
        item.ap for item in metricas.values() if item.referencias > 0
    ]
    return sum(presentes) / len(presentes) if presentes else 0.0


def map_por_faixa_de_iou(
    resultados: list[ResultadoImagem],
    classes: list[int],
    limiares: list[float],
    confianca_operacional: float,
) -> dict[float, float]:
    """Calcula o mAP para cada limiar de sobreposição informado."""
    return {
        limiar: media_das_precisoes(
            avaliar(resultados, classes, limiar, confianca_operacional)
        )
        for limiar in limiares
    }
