"""Testes do carregador no formato Supervisely."""

from __future__ import annotations

import base64
import json
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataset import carregar, carregar_supervisely  # noqa: E402


def png_minimo(largura: int, altura: int) -> bytes:
    """Gera um PNG válido apenas no cabeçalho, suficiente para ler dimensões."""
    assinatura = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">II", largura, altura) + b"\x08\x06\x00\x00\x00"
    bloco = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr
    bloco += struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)
    return assinatura + bloco


def montar(pasta: Path) -> Path:
    divisao = pasta / "train"
    (divisao / "ann").mkdir(parents=True)
    (divisao / "img").mkdir(parents=True)

    # Imagem 1: polígono (carro), retângulo (pedestre), classe excluída.
    (divisao / "img" / "a.jpg").write_bytes(b"")
    anotacao = {
        "description": "",
        "tags": [{"name": "timeofday", "value": "daytime"}],
        "size": {"height": 720, "width": 1280},
        "objects": [
            {
                "classTitle": "car",
                "geometryType": "polygon",
                "points": {
                    "exterior": [
                        [635, 237],
                        [634, 254],
                        [641, 244],
                        [639, 252],
                    ],
                    "interior": [],
                },
            },
            {
                "classTitle": "pedestrian",
                "geometryType": "rectangle",
                "points": {"exterior": [[100, 200], [140, 300]], "interior": []},
            },
            {
                "classTitle": "trailer",
                "geometryType": "polygon",
                "points": {"exterior": [[0, 0], [10, 10]], "interior": []},
            },
        ],
    }
    (divisao / "ann" / "a.jpg.json").write_text(
        json.dumps(anotacao), encoding="utf-8"
    )

    # Imagem 2: máscara (ônibus).
    (divisao / "img" / "b.jpg").write_bytes(b"")
    bitmap = {
        "description": "",
        "tags": [],
        "size": {"height": 720, "width": 1280},
        "objects": [
            {
                "classTitle": "bus",
                "geometryType": "bitmap",
                "bitmap": {
                    "origin": [50, 60],
                    "data": base64.b64encode(png_minimo(30, 40)).decode(),
                },
            }
        ],
    }
    (divisao / "ann" / "b.jpg.json").write_text(
        json.dumps(bitmap), encoding="utf-8"
    )

    # Anotação sem imagem correspondente.
    (divisao / "ann" / "fantasma.jpg.json").write_text(
        json.dumps({"objects": []}), encoding="utf-8"
    )
    return divisao


def quase(a: float, b: float) -> bool:
    return abs(a - b) < 1e-6


def test_poligono_vira_caixa_envolvente():
    with tempfile.TemporaryDirectory() as tmp:
        divisao = montar(Path(tmp))
        conjunto = carregar_supervisely(divisao)
        amostra = next(a for a in conjunto.amostras if a.caminho.name == "a.jpg")
        carro = next(an for an in amostra.anotacoes if an.classe == 2)
        # min/max dos vértices: x de 634 a 641, y de 237 a 254
        assert quase(carro.caixa.x1, 634)
        assert quase(carro.caixa.y1, 237)
        assert quase(carro.caixa.x2, 641)
        assert quase(carro.caixa.y2, 254)
        print("  ok    test_poligono_vira_caixa_envolvente")


def test_retangulo():
    with tempfile.TemporaryDirectory() as tmp:
        divisao = montar(Path(tmp))
        conjunto = carregar_supervisely(divisao)
        amostra = next(a for a in conjunto.amostras if a.caminho.name == "a.jpg")
        pessoa = next(an for an in amostra.anotacoes if an.classe == 0)
        assert quase(pessoa.caixa.x1, 100)
        assert quase(pessoa.caixa.y2, 300)
        print("  ok    test_retangulo")


def test_bitmap():
    with tempfile.TemporaryDirectory() as tmp:
        divisao = montar(Path(tmp))
        conjunto = carregar_supervisely(divisao)
        amostra = next(a for a in conjunto.amostras if a.caminho.name == "b.jpg")
        onibus = amostra.anotacoes[0]
        assert quase(onibus.caixa.x1, 50)
        assert quase(onibus.caixa.y1, 60)
        assert quase(onibus.caixa.x2, 80)  # 50 + 30
        assert quase(onibus.caixa.y2, 100)  # 60 + 40
        print("  ok    test_bitmap")


def test_exclusoes_e_ausentes():
    with tempfile.TemporaryDirectory() as tmp:
        divisao = montar(Path(tmp))
        conjunto = carregar_supervisely(divisao)
        assert conjunto.anotacoes_excluidas == {"trailer": 1}
        assert conjunto.imagens_ausentes == 1
        assert conjunto.anotacoes_aproveitadas == 3  # carro, pedestre, ônibus
        print("  ok    test_exclusoes_e_ausentes")


def test_marcacoes_viram_atributos():
    with tempfile.TemporaryDirectory() as tmp:
        divisao = montar(Path(tmp))
        conjunto = carregar_supervisely(divisao)
        amostra = next(a for a in conjunto.amostras if a.caminho.name == "a.jpg")
        assert amostra.atributos.get("timeofday") == "daytime"
        print("  ok    test_marcacoes_viram_atributos")


def test_deteccao_automatica_pela_pasta_da_divisao():
    with tempfile.TemporaryDirectory() as tmp:
        divisao = montar(Path(tmp))
        conjunto = carregar(pasta_imagens=divisao)
        assert conjunto.formato == "supervisely"
        print("  ok    test_deteccao_automatica_pela_pasta_da_divisao")


def test_deteccao_automatica_pela_pasta_de_imagens():
    """Apontar para train/img também deve funcionar."""
    with tempfile.TemporaryDirectory() as tmp:
        divisao = montar(Path(tmp))
        conjunto = carregar(pasta_imagens=divisao / "img")
        assert conjunto.formato == "supervisely"
        assert len(conjunto.amostras) == 2
        print("  ok    test_deteccao_automatica_pela_pasta_de_imagens")


def test_limite():
    with tempfile.TemporaryDirectory() as tmp:
        divisao = montar(Path(tmp))
        conjunto = carregar_supervisely(divisao, limite=1)
        assert len(conjunto.amostras) == 1
        print("  ok    test_limite")


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
