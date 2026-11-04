"""Teste de ponta a ponta do fluxo, com um modelo simulado.

Verifica o carregamento das anotações, a exclusão das classes sem equivalente,
a avaliação e a gravação dos resultados, sem depender do Ultralytics.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import modelo as modulo_modelo  # noqa: E402
from avaliacao import Predicao  # noqa: E402
from dataset import Caixa, carregar  # noqa: E402
from modelo import ResumoInferencia  # noqa: E402


def montar_conjunto(pasta: Path) -> tuple[Path, Path]:
    """Cria um conjunto sintético no formato do BDD100K."""
    imagens = pasta / "images"
    imagens.mkdir(parents=True)
    for nome in ("a.jpg", "b.jpg"):
        (imagens / nome).write_bytes(b"")

    rotulos = [
        {
            "name": "a.jpg",
            "attributes": {"weather": "clear", "timeofday": "daytime"},
            "labels": [
                {"category": "car", "box2d": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}},
                {
                    "category": "pedestrian",
                    "box2d": {"x1": 50, "y1": 50, "x2": 60, "y2": 80},
                },
                {
                    "category": "traffic sign",
                    "box2d": {"x1": 90, "y1": 10, "x2": 99, "y2": 20},
                },
            ],
        },
        {
            "name": "b.jpg",
            "attributes": {"weather": "rainy", "timeofday": "night"},
            "labels": [
                {"category": "car", "box2d": {"x1": 20, "y1": 20, "x2": 40, "y2": 40}},
                {"category": "train", "box2d": {"x1": 0, "y1": 0, "x2": 5, "y2": 5}},
            ],
        },
    ]
    arquivo = pasta / "rotulos.json"
    arquivo.write_text(json.dumps(rotulos), encoding="utf-8")
    return imagens, arquivo


def test_carregamento_e_exclusoes():
    with tempfile.TemporaryDirectory() as temporario:
        imagens, arquivo = montar_conjunto(Path(temporario))
        conjunto = carregar(pasta_imagens=imagens, arquivo_rotulos=arquivo)

        assert len(conjunto.amostras) == 2
        # 2 carros + 1 pedestre aproveitados; placa e trem excluídos.
        assert conjunto.anotacoes_aproveitadas == 3
        assert conjunto.anotacoes_excluidas == {"traffic sign": 1, "train": 1}
        assert conjunto.amostras[0].atributos["weather"] == "clear"
        print("  ok    test_carregamento_e_exclusoes")


def test_fluxo_completo_com_modelo_simulado():
    """Executa o programa inteiro substituindo a inferência por um simulacro."""
    with tempfile.TemporaryDirectory() as temporario:
        pasta = Path(temporario)
        imagens, arquivo = montar_conjunto(pasta)
        saida = pasta / "resultados"

        def carregar_falso(pesos: str):
            del pesos
            return object()

        def inferir_falso(modelo, caminhos, classes_de_interesse, **kwargs):
            """Acerta o carro da imagem a, erra o da imagem b."""
            del modelo, classes_de_interesse, kwargs
            resposta = []
            for caminho in caminhos:
                if caminho.name == "a.jpg":
                    resposta.append(
                        [Predicao(2, 0.95, Caixa(0, 0, 10, 10))]  # carro correto
                    )
                else:
                    resposta.append(
                        [Predicao(2, 0.80, Caixa(500, 500, 520, 520))]  # falso
                    )
            return resposta, ResumoInferencia(imagens=len(caminhos), segundos=0.5)

        original_carregar = modulo_modelo.carregar_modelo
        original_inferir = modulo_modelo.inferir
        modulo_modelo.carregar_modelo = carregar_falso
        modulo_modelo.inferir = inferir_falso

        # executar.py importa os nomes diretamente, então é preciso substituí-los
        # também no módulo que os consome.
        import executar

        executar.carregar_modelo = carregar_falso
        executar.inferir = inferir_falso

        try:
            codigo = executar.main(
                [
                    "--imagens",
                    str(imagens),
                    "--rotulos",
                    str(arquivo),
                    "--saida",
                    str(saida),
                ]
            )
        finally:
            modulo_modelo.carregar_modelo = original_carregar
            modulo_modelo.inferir = original_inferir

        assert codigo == 0, f"código de saída inesperado: {codigo}"

        relatorio = json.loads((saida / "relatorio.json").read_text("utf-8"))
        carro = relatorio["metricas_por_classe"]["carro"]
        assert carro["referencias"] == 2
        assert carro["verdadeiros_positivos"] == 1
        assert carro["falsos_positivos"] == 1
        assert carro["falsos_negativos"] == 1
        assert abs(carro["precisao"] - 0.5) < 1e-6
        assert abs(carro["revocacao"] - 0.5) < 1e-6

        pessoa = relatorio["metricas_por_classe"]["pessoa"]
        assert pessoa["referencias"] == 1
        assert pessoa["verdadeiros_positivos"] == 0

        exclusoes = relatorio["anotacoes_excluidas_por_ausencia_de_equivalente"]
        assert exclusoes == {"traffic sign": 1, "train": 1}

        # O recorte por condição deve separar dia e noite.
        condicoes = relatorio["map_por_condicao"]
        assert "timeofday: daytime" in condicoes
        assert "timeofday: night" in condicoes
        assert "weather: rainy" in condicoes

        assert (saida / "metricas-por-classe.csv").is_file()
        linhas = (saida / "metricas-por-classe.csv").read_text("utf-8").splitlines()
        assert linhas[0].startswith("classe,referencias")
        assert len(linhas) == 1 + 8  # cabeçalho + 8 classes de interesse
        print("  ok    test_fluxo_completo_com_modelo_simulado")


if __name__ == "__main__":
    falhas = 0
    for nome, funcao in sorted(globals().items()):
        if nome.startswith("test_") and callable(funcao):
            try:
                funcao()
            except AssertionError as erro:
                falhas += 1
                print(f"  FALHA {nome}: {erro}")
            except Exception as erro:  # noqa: BLE001
                falhas += 1
                print(f"  ERRO  {nome}: {type(erro).__name__}: {erro}")
    print("\nfalhas:", falhas)
    raise SystemExit(1 if falhas else 0)
