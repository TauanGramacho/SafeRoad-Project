import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from transito.application import KnowledgeBase
from transito.client import Settings, TypeDBClient
from transito.integracao import ObservationStore, main
from transito.validation import validate

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@unittest.skipUnless(
    os.environ.get("TYPEDB_TEST_URL"), "Defina TYPEDB_TEST_URL para testar o banco."
)
class ObservationIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = self.new_database()
        KnowledgeBase(self.client).initialize(seed=False)
        self.store = ObservationStore(self.client)

    def new_database(self) -> TypeDBClient:
        settings = Settings(
            url=os.environ["TYPEDB_TEST_URL"],
            database=f"teste-roadguard-{uuid4().hex}",
            username=os.environ.get("TYPEDB_USER", "admin"),
            password=os.environ.get("TYPEDB_PASSWORD", "password"),
        )
        client = TypeDBClient(settings)
        client.connect()
        path = f"/v1/databases/{settings.database}"
        client.request("POST", path)
        self.addCleanup(client.request, "DELETE", path)
        return client

    def test_video_facts_feed_the_inference_rules(self) -> None:
        code, summary = self.store.register(load("relatorio_video.json"))
        self.assertEqual(summary["passagens_por_sinal"], 2)
        findings = self.store.findings(code)
        self.assertEqual(
            sorted(item["tipo"] for item in findings["objetos"]),
            ["carro", "moto", "objeto-generico", "pessoa", "pessoa", "placa-pare"],
        )
        rider = {"piloto": "Pessoa observada #1", "moto": "Moto observada #2"}
        self.assertEqual(findings["pilotos"], [rider])
        self.assertEqual(findings["pilotos_sem_capacete"], [rider])
        self.assertEqual(
            findings["passagens_por_sinal"],
            [
                {"veiculo": "Moto observada #2", "sinal": "placa-pare", "quadro": 42,
                 "tempo_s": 1.64},
                {"veiculo": "Carro observado #3", "sinal": "semaforo", "quadro": 90,
                 "tempo_s": 3.56},
            ],
        )

    def test_image_facts_feed_the_inference_rules(self) -> None:
        code, _ = self.store.register(load("relatorio_imagem.json"))
        findings = self.store.findings(code)
        self.assertEqual(len(findings["objetos"]), 5)
        self.assertEqual(
            findings["pilotos"],
            [{"piloto": "Pessoa observada (detecção 1)", "moto": "Moto observada (detecção 0)"}],
        )
        stored = self.client.query('match $a isa analise; fetch {"arquivo": $a.arquivo};')
        self.assertEqual(stored, [{"arquivo": "C:\\fotos\\avenida.jpg"}])

    def test_helmet_registration_removes_the_alert(self) -> None:
        code, _ = self.store.register(load("relatorio_video.json"))
        self.client.query(
            f'match $p isa pessoa, has codigo "{code}-T1"; '
            'insert $c isa capacete, has codigo "E100", has nome "Capacete visto"; '
            "uso-equipamento (usuario: $p, item: $c);",
            "write",
        )
        findings = self.store.findings(code)
        self.assertEqual(len(findings["pilotos"]), 1)
        self.assertEqual(findings["pilotos_sem_capacete"], [])

    def test_registering_twice_does_not_duplicate(self) -> None:
        report = load("relatorio_video.json")
        code, _ = self.store.register(report)
        before = self.store.findings(code)
        self.assertEqual(self.store.register(report), (code, None))
        self.assertEqual(self.store.findings(code), before)

    def test_analyses_are_isolated(self) -> None:
        video, _ = self.store.register(load("relatorio_video.json"))
        image, _ = self.store.register(load("relatorio_imagem.json"))
        self.assertEqual(len(self.store.findings(video)["objetos"]), 6)
        self.assertEqual(len(self.store.findings(image)["objetos"]), 5)
        self.assertEqual(self.store.findings(image)["passagens_por_sinal"], [])

    def test_text_with_quotes_and_backslashes_is_stored_verbatim(self) -> None:
        report = load("relatorio_imagem.json")
        report["arquivo"] = 'C:\\pasta "nova"\\foto.jpg'
        self.store.register(report)
        stored = self.client.query('match $a isa analise; fetch {"arquivo": $a.arquivo};')
        self.assertEqual(stored, [{"arquivo": 'C:\\pasta "nova"\\foto.jpg'}])

    def test_existing_database_is_upgraded_without_losing_data(self) -> None:
        client = self.new_database()
        base = KnowledgeBase(client)
        client.query(base.read(base.root / "schema.tql"), "schema")
        client.query(base.read(base.root / "dados.tql"), "write")
        self.assertFalse(base.initialize())
        validate(base.examples())
        code, _ = ObservationStore(client).register(load("relatorio_video.json"))
        self.assertEqual(len(ObservationStore(client).findings(code)["pilotos"]), 1)

    def test_cli_registers_report_and_saves_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = Path(directory) / "resultado.json"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(
                    [
                        "registrar",
                        str(FIXTURES / "relatorio_video.json"),
                        "--url",
                        os.environ["TYPEDB_TEST_URL"],
                        "--database",
                        self.client.settings.database,
                        "--resultado",
                        str(result),
                    ]
                )
            self.assertEqual(status, 0)
            self.assertIn("1 condução(ões), 2 passagem(ns) por sinal", output.getvalue())
            self.assertIn("Piloto sem capacete registrado: Pessoa observada #1", output.getvalue())
            saved = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["pilotos_sem_capacete"]), 1)

    def test_cli_reports_invalid_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "quebrado.json"
            report.write_text("[1, 2]", encoding="utf-8")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                status = main(["registrar", str(report), "--url", os.environ["TYPEDB_TEST_URL"]])
            self.assertEqual(status, 1)
            self.assertIn("objeto JSON", errors.getvalue())
