"""Testes das métricas sobre dados sintéticos de resultado conhecido."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from avaliacao import (  # noqa: E402
    Predicao,
    ResultadoImagem,
    avaliar_classe,
    filtrar_por_lado_minimo,
    interseccao_sobre_uniao,
    media_das_precisoes,
)
from dataset import Anotacao, Caixa  # noqa: E402

CARRO = 2
PESSOA = 0


def quase(obtido: float, esperado: float, tolerancia: float = 1e-6) -> bool:
    return abs(obtido - esperado) <= tolerancia


def test_iou_identicas():
    caixa = Caixa(0, 0, 10, 10)
    assert quase(interseccao_sobre_uniao(caixa, caixa), 1.0)


def test_iou_disjuntas():
    assert quase(
        interseccao_sobre_uniao(Caixa(0, 0, 10, 10), Caixa(20, 20, 30, 30)), 0.0
    )


def test_iou_meia_sobreposicao():
    # Interseção 50, união 150, IoU = 1/3
    valor = interseccao_sobre_uniao(Caixa(0, 0, 10, 10), Caixa(5, 0, 15, 10))
    assert quase(valor, 50 / 150)


def test_iou_contida():
    # Interseção 25, união 100, IoU = 0,25
    valor = interseccao_sobre_uniao(Caixa(0, 0, 10, 10), Caixa(0, 0, 5, 5))
    assert quase(valor, 0.25)


def test_deteccao_perfeita():
    caixa = Caixa(10, 10, 50, 50)
    resultados = [
        ResultadoImagem(
            indice=0,
            predicoes=[Predicao(CARRO, 0.9, caixa)],
            referencias=[Anotacao(CARRO, caixa)],
        )
    ]
    metricas = avaliar_classe(resultados, CARRO, 0.5, 0.25)
    assert metricas.verdadeiros_positivos == 1
    assert metricas.falsos_positivos == 0
    assert metricas.falsos_negativos == 0
    assert quase(metricas.precisao, 1.0)
    assert quase(metricas.revocacao, 1.0)
    assert quase(metricas.f1, 1.0)
    assert quase(metricas.ap, 1.0)


def test_sem_deteccao():
    resultados = [
        ResultadoImagem(
            indice=0,
            predicoes=[],
            referencias=[Anotacao(CARRO, Caixa(10, 10, 50, 50))],
        )
    ]
    metricas = avaliar_classe(resultados, CARRO, 0.5, 0.25)
    assert metricas.verdadeiros_positivos == 0
    assert metricas.falsos_negativos == 1
    assert quase(metricas.revocacao, 0.0)
    assert quase(metricas.ap, 0.0)


def test_apenas_falso_positivo():
    resultados = [
        ResultadoImagem(
            indice=0,
            predicoes=[Predicao(CARRO, 0.9, Caixa(10, 10, 50, 50))],
            referencias=[],
        )
    ]
    metricas = avaliar_classe(resultados, CARRO, 0.5, 0.25)
    assert metricas.falsos_positivos == 1
    assert quase(metricas.precisao, 0.0)
    assert quase(metricas.ap, 0.0)


def test_iou_abaixo_do_limiar_vira_falso_positivo():
    resultados = [
        ResultadoImagem(
            indice=0,
            # IoU = 1/3, abaixo de 0,5
            predicoes=[Predicao(CARRO, 0.9, Caixa(5, 0, 15, 10))],
            referencias=[Anotacao(CARRO, Caixa(0, 0, 10, 10))],
        )
    ]
    metricas = avaliar_classe(resultados, CARRO, 0.5, 0.25)
    assert metricas.verdadeiros_positivos == 0
    assert metricas.falsos_positivos == 1
    assert metricas.falsos_negativos == 1


def test_duas_predicoes_para_uma_referencia():
    """A segunda detecção sobre a mesma anotação é falso positivo."""
    caixa = Caixa(0, 0, 10, 10)
    resultados = [
        ResultadoImagem(
            indice=0,
            predicoes=[
                Predicao(CARRO, 0.9, caixa),
                Predicao(CARRO, 0.8, caixa),
            ],
            referencias=[Anotacao(CARRO, caixa)],
        )
    ]
    metricas = avaliar_classe(resultados, CARRO, 0.5, 0.25)
    assert metricas.verdadeiros_positivos == 1
    assert metricas.falsos_positivos == 1
    assert quase(metricas.precisao, 0.5)
    assert quase(metricas.revocacao, 1.0)


def test_classes_nao_se_misturam():
    """Uma pessoa detectada onde há um carro não conta como acerto."""
    caixa = Caixa(0, 0, 10, 10)
    resultados = [
        ResultadoImagem(
            indice=0,
            predicoes=[Predicao(PESSOA, 0.9, caixa)],
            referencias=[Anotacao(CARRO, caixa)],
        )
    ]
    assert avaliar_classe(resultados, CARRO, 0.5, 0.25).verdadeiros_positivos == 0
    assert avaliar_classe(resultados, PESSOA, 0.5, 0.25).falsos_positivos == 1


def test_imagens_nao_se_misturam():
    """Detecção na imagem 0 não pode parear com referência da imagem 1."""
    caixa = Caixa(0, 0, 10, 10)
    resultados = [
        ResultadoImagem(indice=0, predicoes=[Predicao(CARRO, 0.9, caixa)]),
        ResultadoImagem(indice=1, referencias=[Anotacao(CARRO, caixa)]),
    ]
    metricas = avaliar_classe(resultados, CARRO, 0.5, 0.25)
    assert metricas.verdadeiros_positivos == 0
    assert metricas.falsos_positivos == 1
    assert metricas.falsos_negativos == 1


def test_ap_caso_calculado_a_mao():
    """Duas referências, três detecções: acerto, erro, acerto.

    Curva: (r=0,5; p=1,0), (r=0,5; p=0,5), (r=1,0; p=2/3).
    Após a interpolação monotônica, a precisão em ambos os degraus é 2/3,
    logo AP = 0,5 x 1,0 + 0,5 x 2/3 ... não: a interpolação eleva o primeiro
    degrau ao máximo à direita, que é 2/3 apenas se menor que 1,0.
    Como p=1,0 no primeiro ponto, AP = 0,5 x 1,0 + 0,5 x (2/3) = 0,8333...
    """
    resultados = [
        ResultadoImagem(
            indice=0,
            predicoes=[
                Predicao(CARRO, 0.9, Caixa(0, 0, 10, 10)),  # acerto
                Predicao(CARRO, 0.8, Caixa(100, 100, 110, 110)),  # erro
                Predicao(CARRO, 0.7, Caixa(20, 20, 30, 30)),  # acerto
            ],
            referencias=[
                Anotacao(CARRO, Caixa(0, 0, 10, 10)),
                Anotacao(CARRO, Caixa(20, 20, 30, 30)),
            ],
        )
    ]
    metricas = avaliar_classe(resultados, CARRO, 0.5, 0.25)
    assert metricas.verdadeiros_positivos == 2
    assert metricas.falsos_positivos == 1
    assert quase(metricas.ap, 0.5 * 1.0 + 0.5 * (2 / 3), 1e-6)


def test_ordem_por_confianca_afeta_pareamento():
    """A detecção mais confiante reivindica a anotação de maior sobreposição."""
    resultados = [
        ResultadoImagem(
            indice=0,
            predicoes=[
                Predicao(CARRO, 0.6, Caixa(0, 0, 10, 10)),
                Predicao(CARRO, 0.9, Caixa(1, 1, 11, 11)),
            ],
            referencias=[Anotacao(CARRO, Caixa(0, 0, 10, 10))],
        )
    ]
    metricas = avaliar_classe(resultados, CARRO, 0.5, 0.25)
    assert metricas.verdadeiros_positivos == 1
    assert metricas.falsos_positivos == 1


def test_limiar_operacional_descarta_baixa_confianca():
    caixa = Caixa(0, 0, 10, 10)
    resultados = [
        ResultadoImagem(
            indice=0,
            predicoes=[Predicao(CARRO, 0.10, caixa)],
            referencias=[Anotacao(CARRO, caixa)],
        )
    ]
    metricas = avaliar_classe(resultados, CARRO, 0.5, 0.25)
    assert metricas.verdadeiros_positivos == 0  # abaixo do limiar operacional
    assert metricas.falsos_negativos == 1
    assert quase(metricas.ap, 1.0)  # a AP considera toda a curva


def test_map_ignora_classes_ausentes():
    caixa = Caixa(0, 0, 10, 10)
    resultados = [
        ResultadoImagem(
            indice=0,
            predicoes=[Predicao(CARRO, 0.9, caixa)],
            referencias=[Anotacao(CARRO, caixa)],
        )
    ]
    metricas = {
        CARRO: avaliar_classe(resultados, CARRO, 0.5, 0.25),
        PESSOA: avaliar_classe(resultados, PESSOA, 0.5, 0.25),
    }
    # A classe pessoa não possui referências e não deve puxar a média para baixo.
    assert quase(media_das_precisoes(metricas), 1.0)


def test_filtro_por_lado_minimo():
    """Objetos finos saem da avaliação, grandes permanecem."""
    resultados = [
        ResultadoImagem(
            indice=0,
            predicoes=[
                Predicao(CARRO, 0.9, Caixa(0, 0, 7, 17)),      # lado menor 7
                Predicao(CARRO, 0.9, Caixa(0, 0, 100, 100)),   # lado menor 100
            ],
            referencias=[
                Anotacao(CARRO, Caixa(0, 0, 7, 17)),
                Anotacao(CARRO, Caixa(0, 0, 100, 100)),
                Anotacao(CARRO, Caixa(0, 0, 200, 15)),         # lado menor 15
            ],
        )
    ]
    recortados, refs_fora, preds_fora = filtrar_por_lado_minimo(resultados, 16)
    assert refs_fora == 2       # a de 7 px e a de 15 px
    assert preds_fora == 1      # a de 7 px
    assert len(recortados[0].referencias) == 1
    assert len(recortados[0].predicoes) == 1


def test_filtro_desligado_nao_altera_nada():
    resultados = [
        ResultadoImagem(
            indice=0,
            predicoes=[Predicao(CARRO, 0.9, Caixa(0, 0, 3, 3))],
            referencias=[Anotacao(CARRO, Caixa(0, 0, 3, 3))],
        )
    ]
    recortados, refs_fora, preds_fora = filtrar_por_lado_minimo(resultados, 0)
    assert refs_fora == 0 and preds_fora == 0
    assert recortados is resultados


def executar() -> int:
    testes = [
        (nome, funcao)
        for nome, funcao in sorted(globals().items())
        if nome.startswith("test_") and callable(funcao)
    ]
    falhas = 0
    for nome, funcao in testes:
        try:
            funcao()
            print(f"  ok    {nome}")
        except AssertionError as erro:
            falhas += 1
            print(f"  FALHA {nome}: {erro}")
        except Exception as erro:  # noqa: BLE001
            falhas += 1
            print(f"  ERRO  {nome}: {type(erro).__name__}: {erro}")
    print(f"\n{len(testes) - falhas}/{len(testes)} testes aprovados")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(executar())
