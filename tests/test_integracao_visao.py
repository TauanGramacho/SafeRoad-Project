import unittest

from transito.application import KNOWLEDGE_BASE_ROOT
from transito.integracao import TYPES_QUERY, match_types

TYPES = {"carro", "moto", "caminhao"}


class VisionKnowledgeBaseTests(unittest.TestCase):
    def test_knowledge_base_files_exist(self) -> None:
        for name in ("schema.tql", "dados.tql", "compose.yaml"):
            with self.subTest(file=name):
                self.assertTrue((KNOWLEDGE_BASE_ROOT / name).is_file())
        self.assertTrue(TYPES_QUERY.is_file())

    def test_image_report(self) -> None:
        report = {
            "arquivo": "rua.jpg",
            "deteccoes": [
                {"classe": "carro"},
                {"classe": "carro"},
                {"classe": "caminhão"},
                {"classe": "ônibus"},
            ],
        }
        self.assertEqual(
            match_types(report, TYPES),
            {
                "relatorio": "rua.jpg",
                "tipos_na_base": {"caminhao": 1, "carro": 2},
                "sem_correspondencia": {"ônibus": 1},
            },
        )

    def test_video_report_counts_each_track_once(self) -> None:
        report = {
            "objetos_rastreados": {
                "1": {"classe": "moto", "quadros_detectados": 40},
                "2": {"classe": "pessoa", "quadros_detectados": 3},
            }
        }
        result = match_types(report, TYPES)
        self.assertEqual(result["tipos_na_base"], {"moto": 1})
        self.assertEqual(result["sem_correspondencia"], {"pessoa": 1})

    def test_type_missing_from_base(self) -> None:
        result = match_types({"deteccoes": [{"classe": "moto"}]}, {"carro"})
        self.assertEqual(result["sem_correspondencia"], {"moto": 1})

    def test_rejects_unknown_file(self) -> None:
        with self.assertRaises(ValueError):
            match_types({"outro": 1}, TYPES)


if __name__ == "__main__":
    unittest.main()
