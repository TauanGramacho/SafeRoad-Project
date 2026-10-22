import unittest
from pathlib import Path

from transito.visao import (
    assign_lane_estimates,
    default_output,
    describe_detection,
    detections_from_result,
    find_signal_events,
    position_in_frame,
    report_path,
)


class FakeTensor:
    def __init__(self, values: list) -> None:
        self.values = values

    def tolist(self) -> list:
        return self.values


class FakeBoxes:
    def __init__(self, xyxy: list, cls: list, conf: list, ids: list | None) -> None:
        self.xyxy = FakeTensor(xyxy)
        self.cls = FakeTensor(cls)
        self.conf = FakeTensor(conf)
        self.id = FakeTensor(ids) if ids is not None else None

    def __len__(self) -> int:
        return len(self.cls.values)


class FakeResult:
    def __init__(self, boxes: FakeBoxes | None) -> None:
        self.boxes = boxes


def detection(class_id: int, box: list[float], track_id: int | None = None) -> dict:
    names = {2: "carro", 3: "moto", 9: "semáforo", 11: "placa de pare"}
    return {
        "classe_id": class_id,
        "classe": names[class_id],
        "confianca": 0.9,
        "caixa_xyxy": box,
        "posicao_no_quadro": "centro",
        "id_rastreamento": track_id,
    }


def vertical_boundary(x: float) -> dict[str, float]:
    slope = 50.0
    return {"slope": slope, "intercept": 719 - slope * x, "x": x}


class PositionTests(unittest.TestCase):
    def test_divides_frame_in_three_parts(self) -> None:
        self.assertEqual(position_in_frame(100, 900), "esquerda")
        self.assertEqual(position_in_frame(300, 900), "centro")
        self.assertEqual(position_in_frame(599, 900), "centro")
        self.assertEqual(position_in_frame(600, 900), "direita")

    def test_zero_width_does_not_divide_by_zero(self) -> None:
        self.assertEqual(position_in_frame(0, 0), "esquerda")


class DetectionsTests(unittest.TestCase):
    def test_ignores_classes_outside_the_list(self) -> None:
        boxes = FakeBoxes(
            xyxy=[[0, 0, 10, 10], [100, 100, 200, 200]],
            cls=[2.0, 16.0],
            conf=[0.8, 0.95],
            ids=None,
        )
        detections = detections_from_result(FakeResult(boxes), 640)
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0]["classe"], "carro")
        self.assertIsNone(detections[0]["id_rastreamento"])

    def test_keeps_tracking_id_when_present(self) -> None:
        boxes = FakeBoxes([[500, 0, 600, 50]], [3.0], [0.51234], [7.0])
        (item,) = detections_from_result(FakeResult(boxes), 640)
        self.assertEqual(item["id_rastreamento"], 7)
        self.assertEqual(item["confianca"], 0.5123)
        self.assertEqual(item["posicao_no_quadro"], "direita")

    def test_empty_result(self) -> None:
        self.assertEqual(detections_from_result(FakeResult(None), 640), [])


class LaneTests(unittest.TestCase):
    def test_assigns_lane_with_three_boundaries(self) -> None:
        boundaries = [vertical_boundary(x) for x in (100, 500, 900)]
        car = detection(2, [150, 600, 250, 700])
        assign_lane_estimates([car], boundaries, 1000, 720)
        self.assertEqual(car["faixa_estimada"], {"posicao": "esquerda", "quantidade_estimada": 2})

    def test_needs_at_least_three_boundaries(self) -> None:
        boundaries = [vertical_boundary(x) for x in (100, 500)]
        car = detection(2, [150, 600, 250, 700])
        assign_lane_estimates([car], boundaries, 1000, 720)
        self.assertNotIn("faixa_estimada", car)

    def test_ignores_more_than_five_boundaries(self) -> None:
        boundaries = [vertical_boundary(x) for x in (50, 200, 350, 500, 650, 800)]
        car = detection(2, [210, 600, 300, 700])
        assign_lane_estimates([car], boundaries, 1000, 720)
        self.assertNotIn("faixa_estimada", car)

    def test_signals_never_receive_a_lane(self) -> None:
        boundaries = [vertical_boundary(x) for x in (100, 500, 900)]
        light = detection(9, [150, 600, 250, 700])
        assign_lane_estimates([light], boundaries, 1000, 720)
        self.assertNotIn("faixa_estimada", light)


class SignalEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous: dict = {}
        self.signals: dict = {}
        self.emitted: set = set()

    def run_frame(self, number: int, detections: list[dict]) -> list[dict]:
        return find_signal_events(
            number, 1280, 25.0, detections, self.previous, self.signals, self.emitted
        )

    def test_vehicle_crossing_the_signal_line_creates_one_event(self) -> None:
        light = detection(9, [600, 100, 640, 200], track_id=1)
        self.assertEqual(self.run_frame(1, [light, detection(2, [580, 120, 680, 160], 5)]), [])
        events = self.run_frame(2, [light, detection(2, [580, 200, 680, 260], 5)])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tipo"], "possivel_passagem_visual_por_sinal")
        self.assertEqual(events[0]["id_rastreamento"], 5)
        self.assertEqual(events[0]["tempo_s"], 0.04)
        self.assertEqual(self.run_frame(3, [light, detection(2, [580, 300, 680, 360], 5)]), [])

    def test_vehicle_without_tracking_id_is_ignored(self) -> None:
        light = detection(9, [600, 100, 640, 200], track_id=1)
        self.run_frame(1, [light, detection(2, [580, 120, 680, 160])])
        self.assertEqual(self.run_frame(2, [light, detection(2, [580, 200, 680, 260])]), [])

    def test_vehicle_far_from_the_signal_is_ignored(self) -> None:
        light = detection(9, [600, 100, 640, 200], track_id=1)
        self.run_frame(1, [light, detection(2, [0, 120, 80, 160], 5)])
        self.assertEqual(self.run_frame(2, [light, detection(2, [0, 200, 80, 260], 5)]), [])

    def test_old_signals_expire_after_two_seconds(self) -> None:
        light = detection(9, [600, 100, 640, 200], track_id=1)
        self.run_frame(1, [light])
        self.run_frame(60, [detection(2, [580, 120, 680, 160], 5)])
        self.assertEqual(self.signals, {})
        self.assertEqual(self.run_frame(61, [detection(2, [580, 200, 680, 260], 5)]), [])


class SyntheticLaneImageTests(unittest.TestCase):
    def test_finds_the_painted_lines_of_a_synthetic_road(self) -> None:
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV não instalado.")
        from transito.visao import estimate_lane_boundaries

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        for bottom_x, top_x in ((200, 560), (640, 640), (1080, 720)):
            cv2.line(frame, (bottom_x, 719), (top_x, 430), (255, 255, 255), 8)
        boundaries = estimate_lane_boundaries(frame, cv2, np)
        self.assertGreaterEqual(len(boundaries), 2)
        bottoms = sorted(boundary["x"] for boundary in boundaries)
        self.assertLess(abs(bottoms[0] - 200), 40)
        self.assertLess(abs(bottoms[-1] - 1080), 40)

    def test_blank_image_has_no_lines(self) -> None:
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV não instalado.")
        from transito.visao import estimate_lane_boundaries

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertEqual(estimate_lane_boundaries(frame, cv2, np), [])


class TextAndPathTests(unittest.TestCase):
    def test_describes_lane_when_available(self) -> None:
        car = detection(2, [0, 0, 1, 1])
        car["faixa_estimada"] = {"posicao": "direita", "quantidade_estimada": 3}
        self.assertEqual(
            describe_detection(car), "Carro detectado na faixa direita estimada (confiança 90%)."
        )

    def test_describes_frame_position_without_lane(self) -> None:
        self.assertEqual(
            describe_detection(detection(3, [0, 0, 1, 1])),
            "Moto detectada no centro do quadro (confiança 90%).",
        )

    def test_default_output_names(self) -> None:
        self.assertEqual(default_output(Path("a/foto.png"), "imagem"), Path("a/foto_anotada.png"))
        self.assertEqual(default_output(Path("a/rua.avi"), "video"), Path("a/rua_anotado.mp4"))
        self.assertEqual(
            report_path(Path("a/rua_anotado.mp4")), Path("a/rua_anotado_relatorio.json")
        )


if __name__ == "__main__":
    unittest.main()
