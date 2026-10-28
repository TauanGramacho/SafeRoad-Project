"""Parâmetros da prova de conceito.

Reúne em um único lugar as decisões que afetam o resultado da avaliação, de modo
que cada execução possa ser descrita no texto do trabalho pelos valores aqui
registrados.
"""

from pathlib import Path

# ---------------------------------------------------------------- modelo
MODELO_PADRAO = "yolo11n.pt"

# Limiar de confiança abaixo do qual as detecções são descartadas.
# Valor baixo favorece a revocação, o que é desejável em uma avaliação, pois
# permite traçar a curva de precisão e revocação em toda a sua extensão.
CONFIANCA_MINIMA = 0.001

# Limiar de confiança usado apenas no relatório de precisão e revocação pontuais.
CONFIANCA_OPERACIONAL = 0.25

# Resolução de inferência, em pixels. O YOLO redimensiona a imagem para este
# tamanho antes de processá-la.
TAMANHO_INFERENCIA = 640

# ------------------------------------------------------------- avaliação
# Limiar de sobreposição (IoU) a partir do qual uma detecção é considerada
# correspondente a uma anotação de referência.
IOU_PADRAO = 0.5

# Faixa de limiares usada no cálculo do mAP médio, seguindo a convenção do COCO.
IOU_FAIXA = [round(0.5 + 0.05 * i, 2) for i in range(10)]  # 0.50 a 0.95

# ------------------------------------------------------------- caminhos
RAIZ = Path(__file__).resolve().parent
PASTA_RESULTADOS = RAIZ / "resultados"
