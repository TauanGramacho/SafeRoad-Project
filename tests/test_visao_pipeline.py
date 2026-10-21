import tempfile
import unittest
from pathlib import Path

from transito.integracao import build_insert
from transito.visao import (
    analyze_image,
    analyze_video,
    assign_lane_estimates,
    estimate_lane_boundaries,
)

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = np = None

from test_visao import FakeResult, detection

STOP_SIGN = (11, [200.0, 60.0, 220.0, 80.0], 0.7, 4)


def scripted_frame(number: int) -> list:
    # Moto (#2) e piloto (#1) descem pela imagem e cruzam a altura da placa de pare (#4).
    shift = 4.0 * number
    return [
        STOP_SIGN,
        (3, [180.0, 30.0 + shift, 240.0, 70.0 + shift], 0.88, 2),
        (0, [190.0, 10.0 + shift, 230.0, 60.0 + shift], 0.91, 1),
    ]


class ScriptedModel:
    """Substitui o YOLO: devolve caixas pré-definidas para testar o restante do fluxo."""

    def __init__(self) -> None:
        self.frame = 0

    def predict(self, **_: object) -> list:
        return [
            FakeResult(
                [
                    (3, [600.0, 380.0, 700.0, 520.0], 0.87, None),
                    (0, [610.0, 300.0, 690.0, 470.0], 0.9, None),
                    (0, [100.0, 300.0, 150.0, 450.0], 0.77, None),
                ]
            )
        ]

    def track(self, **_: object) -> list:
        self.frame += 1
        return [FakeResult(scripted_frame(self.frame))]


@unittest.skipIf(cv2 is None, "Instale opencv-python e numpy para os testes de pipeline.")
class VisionPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)

    def test_lane_boundaries_on_synthetic_road(self) -> None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        for start, end in (((100, 479), (270, 290)), ((380, 479), (330, 300)),
                           ((560, 479), (390, 290))):
            cv2.line(frame, start, end, (255, 255, 255), 6)
        boundaries = estimate_lane_boundaries(frame, cv2, np)
        self.assertEqual(len(boundaries), 3)
        car = detection(2, [140.0, 400.0, 220.0, 470.0])
        assign_lane_estimates([car], boundaries, 640, 480)
        self.assertEqual(car["faixa_estimada"]["posicao"], "esquerda")

    def test_image_pipeline_writes_annotated_image_and_report(self) -> None:
        source = self.tmp / "rua.jpg"
        cv2.imwrite(str(source), np.zeros((720, 1280, 3), dtype=np.uint8))
        output = self.tmp / "rua_anotada.jpg"
        report = analyze_image(source, output, ScriptedModel(), cv2, 0.25, 640, "falso", np)
        self.assertTrue(output.is_file())
        self.assertEqual(len(report["deteccoes"]), 3)
        self.assertEqual(
            report["associacoes"],
            [{"tipo": "possivel_conducao", "indice_pessoa": 1, "indice_veiculo": 0}],
        )
        _, summary = build_insert(report, "A-img")
        self.assertEqual(summary["conducoes"], 1)

    def test_video_pipeline_tracks_rider_and_signal_crossing(self) -> None:
        source = self.tmp / "rua.mp4"
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 25, (320, 240))
        for _ in range(20):
            writer.write(np.zeros((240, 320, 3), dtype=np.uint8))
        writer.release()
        output = self.tmp / "rua_anotado.mp4"
        report = analyze_video(source, output, ScriptedModel(), cv2, 0.25, 640, "falso", np)
        self.assertTrue(output.is_file())
        self.assertEqual(report["quadros_analisados"], 20)
        self.assertEqual(set(report["objetos_rastreados"]), {1, 2, 4})
        self.assertEqual(
            report["associacoes"],
            [{"tipo": "possivel_conducao", "id_pessoa": 1, "id_veiculo": 2, "quadros": 20}],
        )
        self.assertEqual(len(report["eventos"]), 1)
        self.assertEqual(report["eventos"][0]["id_rastreamento_sinal"], 4)
        self.assertEqual(report["eventos"][0]["quadro"], 8)
        # O relatório real da visão precisa ser aceito pela ponte com a base.
        _, summary = build_insert(report, "A-vid")
        self.assertEqual(
            summary, {"objetos": 3, "conducoes": 1, "passagens_por_sinal": 1, "ignorados": 0}
        )
