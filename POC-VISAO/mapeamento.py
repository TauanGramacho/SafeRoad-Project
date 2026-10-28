"""Correspondência entre as classes do conjunto de avaliação e as do COCO.

O YOLO11n é pré-treinado no COCO, cujo vocabulário de classes não coincide com o
dos conjuntos anotados para o domínio de trânsito. Este módulo torna explícita a
correspondência adotada e, sobretudo, registra as classes que não possuem
equivalente e que por isso são excluídas da avaliação. Esse registro é parte do
resultado da prova de conceito, e não um detalhe de implementação.
"""

from __future__ import annotations

# ------------------------------------------------------- classes do COCO
# Identificadores conforme a ordem do conjunto COCO, que é a utilizada pelo
# modelo pré-treinado.
COCO_PESSOA = 0
COCO_BICICLETA = 1
COCO_CARRO = 2
COCO_MOTOCICLETA = 3
COCO_ONIBUS = 5
COCO_CAMINHAO = 7
COCO_SEMAFORO = 9
COCO_PLACA_PARE = 11

# Subconjunto do COCO considerado relevante ao domínio. As demais classes do
# modelo são suprimidas na inferência.
CLASSES_DE_INTERESSE: dict[int, str] = {
    COCO_PESSOA: "pessoa",
    COCO_BICICLETA: "bicicleta",
    COCO_CARRO: "carro",
    COCO_MOTOCICLETA: "motocicleta",
    COCO_ONIBUS: "onibus",
    COCO_CAMINHAO: "caminhao",
    COCO_SEMAFORO: "semaforo",
    COCO_PLACA_PARE: "placa_pare",
}

# ---------------------------------------------- correspondência BDD100K
# O BDD100K distingue o pedestre do condutor de veículo de duas rodas
# ("rider"), distinção que o COCO não possui: ambos correspondem a "person".
# A categoria "traffic sign" do BDD abrange toda a sinalização vertical,
# enquanto o COCO contempla apenas a placa de parada obrigatória, ausente da
# sinalização brasileira na forma prevista pelo conjunto norte-americano.
# A categoria "train" não possui equivalente no subconjunto adotado.
BDD100K_PARA_COCO: dict[str, int | None] = {
    "pedestrian": COCO_PESSOA,
    "rider": COCO_PESSOA,
    "car": COCO_CARRO,
    "truck": COCO_CAMINHAO,
    "bus": COCO_ONIBUS,
    "motorcycle": COCO_MOTOCICLETA,
    "bicycle": COCO_BICICLETA,
    "traffic light": COCO_SEMAFORO,
    "traffic sign": None,  # sem equivalente: excluída da avaliação
    "train": None,  # sem equivalente: excluída da avaliação
    # Classes presentes nas redistribuições do subconjunto de segmentação.
    "caravan": None,  # sem equivalente: excluída da avaliação
    "trailer": None,  # sem equivalente: excluída da avaliação
    # Grafias alternativas encontradas em versões distintas do conjunto.
    "person": COCO_PESSOA,
    "motor": COCO_MOTOCICLETA,
    "bike": COCO_BICICLETA,
}

# Justificativa de cada exclusão, reproduzida no relatório da execução.
EXCLUSOES_JUSTIFICADAS: dict[str, str] = {
    "traffic sign": (
        "A categoria abrange toda a sinalização vertical, enquanto o COCO "
        "contempla apenas a placa de parada obrigatória no padrão "
        "norte-americano."
    ),
    "train": "Não há classe correspondente no subconjunto adotado do COCO.",
    "caravan": (
        "O COCO não distingue o reboque habitável do veículo que o traciona."
    ),
    "trailer": "O COCO não possui classe para reboques ou semirreboques.",
}


def nome_da_classe(classe_coco: int) -> str:
    """Devolve o nome em português da classe do COCO."""
    return CLASSES_DE_INTERESSE.get(classe_coco, f"classe_{classe_coco}")


def converter_rotulo(rotulo: str) -> int | None:
    """Converte um rótulo do conjunto de avaliação em classe do COCO.

    Devolve ``None`` quando o rótulo não possui equivalente, caso em que a
    anotação correspondente deve ser excluída da avaliação.
    """
    chave = rotulo.strip().lower()
    if chave not in BDD100K_PARA_COCO:
        return None
    return BDD100K_PARA_COCO[chave]


def rotulos_sem_equivalente() -> list[str]:
    """Lista os rótulos deliberadamente excluídos da avaliação."""
    return sorted(
        rotulo for rotulo, classe in BDD100K_PARA_COCO.items() if classe is None
    )
