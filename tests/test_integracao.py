import copy
import json
import unittest
from pathlib import Path

from transito.application import KNOWLEDGE_BASE_ROOT, PROJECT_ROOT
from transito.integracao import (
    IngestionError,
    analysis_code,
    build_insert,
    describe_findings,
    tql_string,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ProjectLayoutTests(unittest.TestCase):
    def test_knowledge_base_files_are_found(self) -> None:
        # Regressão do defeito D02: a raiz apontava para perception/ após a reorganização.
        for name in ("schema.tql", "observacoes.tql", "dados.tql"):
            with self.subTest(arquivo=name):
                self.assertTrue((KNOWLEDGE_BASE_ROOT / name).is_file())
        self.assertEqual(len(list((KNOWLEDGE_BASE_ROOT / "consultas").glob("*.tql"))), 7)
        self.assertTrue((PROJECT_ROOT / "resultados-verificados.json").is_file())


class TypeQLLiteralTests(unittest.TestCase):
    def test_string_escapes_backslashes_and_quotes(self) -> None:
        self.assertEqual(tql_string('C:\\pasta\\"x".mp4'), '"C:\\\\pasta\\\\\\"x\\".mp4"')
        self.assertEqual(tql_string("ônibus"), '"ônibus"')

    def test_analysis_code_is_stable_and_depends_on_content(self) -> None:
        report = load("relatorio_video.json")
        self.assertEqual(analysis_code(report), analysis_code(copy.deepcopy(report)))
        self.assertRegex(analysis_code(report), r"^A-[0-9a-f]{12}$")
        changed = copy.deepcopy(report)
        changed["arquivo"] = "outro.mp4"
        self.assertNotEqual(analysis_code(report), analysis_code(changed))


class BuildInsertTests(unittest.TestCase):
    def test_image_report_becomes_typed_facts(self) -> None:
        query, summary = build_insert(load("relatorio_imagem.json"), "A-1")
        self.assertEqual(
            summary, {"objetos": 5, "conducoes": 1, "passagens_por_sinal": 0, "ignorados": 0}
        )
        self.assertIn('$o0 isa moto, has codigo "A-1-D0", has modelo "Moto observada (detecção 0)"',
                      query)
        self.assertIn('$o1 isa pessoa, has codigo "A-1-D1"', query)
        self.assertIn('$o3 isa caminhao, has codigo "A-1-D3"', query)
        self.assertIn('$o4 isa objeto-generico, has codigo "A-1-D4", '
                      'has classe-detectada "bicicleta"', query)
        self.assertIn('has faixa-estimada "centro"', query)
        self.assertIn("conducao (condutor: $o1, veiculo-conduzido: $o0);", query)
        self.assertIn('has arquivo "C:\\\\fotos\\\\avenida.jpg"', query)

    def test_video_report_links_tracks_events_and_riders(self) -> None:
        query, summary = build_insert(load("relatorio_video.json"), "A-2")
        self.assertEqual(
            summary, {"objetos": 6, "conducoes": 1, "passagens_por_sinal": 2, "ignorados": 1}
        )
        self.assertIn("has id-rastreamento 2, has quadros-detectados 42", query)
        self.assertIn("conducao (condutor: $o0, veiculo-conduzido: $o1);", query)
        # O sinal rastreado (#4) é reaproveitado; o semáforo sem ID ganha uma entidade própria.
        self.assertIn("links (veiculo-passante: $o1, sinal-cruzado: $o3), has quadro 42", query)
        self.assertIn('$s1 isa semaforo, has codigo "A-2-E1";', query)
        self.assertIn("links (veiculo-passante: $o2, sinal-cruzado: $s1), has quadro 90", query)
        self.assertNotIn("has quadro 120", query)

    def test_rider_with_swapped_class_is_ignored(self) -> None:
        report = load("relatorio_video.json")
        report["associacoes"][0]["id_veiculo"] = 6
        query, summary = build_insert(report, "A-3")
        self.assertEqual(summary["conducoes"], 0)
        self.assertEqual(summary["ignorados"], 2)
        self.assertNotIn("conducao", query)

    def test_unknown_reference_is_rejected(self) -> None:
        report = load("relatorio_video.json")
        report["associacoes"][0]["id_pessoa"] = 99
        with self.assertRaisesRegex(IngestionError, "T99"):
            build_insert(report, "A-4")

    def test_malformed_reports_are_rejected(self) -> None:
        missing_class = load("relatorio_imagem.json")
        del missing_class["deteccoes"][0]["classe"]
        for report in ({"arquivo": "x"}, {"deteccoes": []}, missing_class):
            with self.subTest(report=str(report)[:40]):
                with self.assertRaises(IngestionError):
                    build_insert(report, "A-5")

    def test_report_without_detections_registers_only_the_analysis(self) -> None:
        report = {"arquivo": "vazio.jpg", "modelo": "yolo11n.pt", "deteccoes": []}
        query, summary = build_insert(report, "A-6")
        self.assertEqual(summary["objetos"], 0)
        self.assertEqual(query.count(" isa "), 1)


class DescribeFindingsTests(unittest.TestCase):
    def test_alerts_are_listed(self) -> None:
        lines = describe_findings(
            {
                "objetos": [{"tipo": "moto"}, {"tipo": "pessoa"}, {"tipo": "moto"}],
                "pilotos": [{"piloto": "Pessoa observada #1", "moto": "Moto observada #2"}],
                "pilotos_sem_capacete": [
                    {"piloto": "Pessoa observada #1", "moto": "Moto observada #2"}
                ],
                "passagens_por_sinal": [
                    {"veiculo": "Moto observada #2", "sinal": "placa-pare", "quadro": 42,
                     "tempo_s": 1.64}
                ],
            }
        )
        self.assertEqual(lines[0], "Objetos: moto 2, pessoa 1")
        self.assertIn("  - Pessoa observada #1 conduz Moto observada #2", lines)
        self.assertTrue(any("Piloto sem capacete registrado" in line for line in lines))
        self.assertTrue(any("quadro 42 (1.64 s)" in line for line in lines))

    def test_no_alerts(self) -> None:
        lines = describe_findings(
            {"objetos": [], "pilotos": [], "pilotos_sem_capacete": [], "passagens_por_sinal": []}
        )
        self.assertEqual(lines[0], "Objetos: nenhum")
        self.assertEqual(lines[-1], "  - nenhum")
