import unittest
from pathlib import Path

from transito.visao import (
    assign_lane_estimates,
    default_output,
    describe_detection,
    detections_from_result,
    find_signal_events,
    is_probable_rider,
    position_in_frame,
    report_path,
    rider_pairs,
    select_riders,
)


class FakeValues(list):
    def tolist(self) -> list:
        return list(self)


class FakeBoxes:
    def __init__(self, boxes: list[tuple[int, list[float], float, int | None]]) -> None:
        self.cls = FakeValues(float(item[0]) for item in boxes)
        self.xyxy = FakeValues(item[1] for item in boxes)
        self.conf = FakeValues(item[2] for item in boxes)
        ids = [item[3] for item in boxes]
        self.id = None if all(value is None for value in ids) else FakeValues(ids)

    def __len__(self) -> int:
        return len(self.cls)


class FakeResult:
    def __init__(self, boxes: list[tuple[int, list[float], float, int | None]]) -> None:
        self.boxes = FakeBoxes(boxes)


def detection(class_id: int, box: list[float], track_id: int | None = None) -> dict:
    names = {0: "pessoa", 2: "carro", 3: "moto", 9: "semáforo", 11: "placa de pare"}
    return {
        "classe_id": class_id,
        "classe": names[class_id],
        "confianca": 0.9,
        "caixa_xyxy": box,
        "posicao_no_quadro": "centro",
        "id_rastreamento": track_id,
    }


class FrameGeometryTests(unittest.TestCase):
    def test_position_in_frame_splits_width_in_thirds(self) -> None:
        self.assertEqual(position_in_frame(10, 300), "esquerda")
        self.assertEqual(position_in_frame(150, 300), "centro")
        self.assertEqual(position_in_frame(290, 300), "direita")
        self.assertEqual(position_in_frame(0, 0), "esquerda")

    def test_detections_keep_only_selected_classes(self) -> None:
        result = FakeResult(
            [
                (2, [10, 10, 50, 50], 0.81234, None),
                (63, [0, 0, 5, 5], 0.99, None),
                (11, [250, 10, 290, 50], 0.7, None),
            ]
        )
        detections = detections_from_result(result, 300)
        self.assertEqual([item["classe"] for item in detections], ["carro", "placa de pare"])
        self.assertEqual(detections[0]["confianca"], 0.8123)
        self.assertEqual(detections[1]["posicao_no_quadro"], "direita")
        self.assertIsNone(detections[0]["id_rastreamento"])

    def test_lane_is_assigned_between_estimated_boundaries(self) -> None:
        # Três limites verticais (x = 100, 200, 300) definem duas faixas.
        boundaries = [{"slope": 1e6, "intercept": -1e6 * x, "x": x} for x in (100, 200, 300)]
        car = detection(2, [120, 300, 180, 399])
        person = detection(0, [120, 300, 180, 399])
        assign_lane_estimates([car, person], boundaries, 400, 400)
        self.assertEqual(car["faixa_estimada"], {"posicao": "esquerda", "quantidade_estimada": 2})
        self.assertNotIn("faixa_estimada", person)

    def test_lane_is_not_assigned_with_too_few_boundaries(self) -> None:
        car = detection(2, [120, 300, 180, 399])
        boundaries = [{"slope": 1e6, "intercept": -1e6 * x, "x": x} for x in (100, 200)]
        assign_lane_estimates([car], boundaries, 400, 400)
        self.assertNotIn("faixa_estimada", car)
        self.assertIn("à esquerda", describe_detection({**car, "posicao_no_quadro": "esquerda"}))

    def test_description_mentions_lane_when_available(self) -> None:
        car = detection(2, [0, 0, 1, 1])
        car["faixa_estimada"] = {"posicao": "direita", "quantidade_estimada": 3}
        self.assertEqual(describe_detection(car), "Carro detectado na faixa direita estimada "
                         "(confiança 90%).")

    def test_default_output_paths(self) -> None:
        self.assertEqual(default_output(Path("a/foto.png"), "imagem"), Path("a/foto_anotada.png"))
        self.assertEqual(default_output(Path("a/v.avi"), "video"), Path("a/v_anotado.mp4"))
        self.assertEqual(report_path(Path("a/v_anotado.mp4")), Path("a/v_anotado_relatorio.json"))


class SignalEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous: dict = {}
        self.signals: dict = {}
        self.emitted: set = set()

    def frame(self, number: int, detections: list[dict]) -> list[dict]:
        return find_signal_events(
            number, 640, 25.0, detections, self.previous, self.signals, self.emitted
        )

    def test_tracked_vehicle_does_not_crash(self) -> None:
        # Regressão do defeito D01: y1/y2 não eram lidos da caixa do veículo.
        self.assertEqual(self.frame(1, [detection(2, [10, 20, 50, 60], 1)]), [])

    def test_vehicle_moving_down_past_signal_creates_one_event(self) -> None:
        sign = detection(11, [300, 40, 340, 80], 7)
        self.frame(1, [sign, detection(2, [290, 30, 350, 90], 1)])
        events = self.frame(2, [sign, detection(2, [290, 60, 350, 120], 1)])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["id_rastreamento"], 1)
        self.assertEqual(events[0]["id_rastreamento_sinal"], 7)
        self.assertEqual(events[0]["sinal"], "placa de pare")
        self.assertEqual(events[0]["tempo_s"], 0.04)
        self.assertEqual(self.frame(3, [sign, detection(2, [290, 90, 350, 150], 1)]), [])

    def test_vehicle_moving_up_creates_no_event(self) -> None:
        sign = detection(9, [300, 40, 340, 80])
        self.frame(1, [sign, detection(2, [290, 60, 350, 120], 1)])
        self.assertEqual(self.frame(2, [sign, detection(2, [290, 30, 350, 90], 1)]), [])

    def test_vehicle_far_from_signal_creates_no_event(self) -> None:
        sign = detection(9, [600, 40, 630, 80])
        self.frame(1, [sign, detection(2, [10, 30, 70, 90], 1)])
        self.assertEqual(self.frame(2, [sign, detection(2, [10, 60, 70, 120], 1)]), [])

    def test_old_signals_expire(self) -> None:
        self.frame(1, [detection(9, [300, 40, 340, 80])])
        self.frame(2, [detection(2, [290, 30, 350, 90], 1)])
        self.assertEqual(self.frame(60, [detection(2, [290, 60, 350, 120], 1)]), [])


class RiderTests(unittest.TestCase):
    motorcycle = [600.0, 380.0, 700.0, 520.0]

    def test_person_seated_on_motorcycle_is_rider(self) -> None:
        self.assertTrue(is_probable_rider([610, 300, 690, 470], self.motorcycle))

    def test_pedestrian_beside_motorcycle_is_not_rider(self) -> None:
        self.assertFalse(is_probable_rider([690, 300, 770, 520], self.motorcycle))

    def test_pedestrian_in_front_of_motorcycle_is_not_rider(self) -> None:
        self.assertFalse(is_probable_rider([620, 300, 680, 600], self.motorcycle))

    def test_person_above_without_overlap_is_not_rider(self) -> None:
        self.assertFalse(is_probable_rider([620, 200, 680, 370], self.motorcycle))

    def test_rider_pairs_only_match_people_and_motorcycles(self) -> None:
        detections = [
            detection(3, self.motorcycle),
            detection(0, [610, 300, 690, 470]),
            detection(2, [600, 380, 700, 520]),
        ]
        self.assertEqual(rider_pairs(detections), [(1, 0)])

    def test_select_riders_is_one_to_one_and_requires_frames(self) -> None:
        counts = {(1, 2): 10, (6, 2): 4, (1, 8): 3, (9, 8): 2, (5, 5): 3}
        self.assertEqual(select_riders(counts, 3), [(1, 2, 10), (5, 5, 3)])
        self.assertEqual(select_riders({(1, 2): 2}, 3), [])
