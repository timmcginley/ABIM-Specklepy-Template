import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from specklepy.api.models.current import ModelIngestionStatus
from specklepy.bundle.bundle_reader import read_bundle
from specklepy.bundle.model import Model
from specklepy.bundle.send import SendResult

import speckle_tool as tool


class StudentTemplateTests(unittest.TestCase):
    def result(self):
        return tool.build_result(
            {"objectCount": 7}, "https://app.speckle.systems",
            "project", "input-model", "input-version", "commit-sha",
        )

    def test_import_has_no_connection_side_effects(self):
        spec = importlib.util.spec_from_file_location(
            "student_import_test", Path(tool.__file__)
        )
        with patch.object(tool.SpeckleClient, "authenticate_with_token") as auth:
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
        auth.assert_not_called()

    def test_real_sdk_bundle_roundtrip(self):
        result = self.result()
        with tempfile.TemporaryDirectory() as directory:
            files = tool.build_summary(result, directory).build()
            with Model(
                "project", "output-model", "output-version",
                directory, files.files, read_bundle(directory),
                geometry_downloaded=False,
            ) as model:
                self.assertEqual(tool.analyse_model(model), {"objectCount": 1})
                summary = model.object_by_application_id(f"run-{result['runId']}")
                self.assertEqual(summary.get_string("runId"), result["runId"])
                self.assertEqual(summary.get_string("sourceVersionId"), "input-version")
                self.assertEqual(summary.get_double("objectCount"), 7)
                self.assertEqual(summary.get_string("codeRevision"), "commit-sha")
                self.assertEqual(summary.get_string("assessment"), "not-applicable")

    def test_runs_have_distinct_ids(self):
        self.assertNotEqual(self.result()["runId"], self.result()["runId"])

    def test_publication_states_and_timeout(self):
        sent = SendResult("project", "output-model", "version", "ingestion", 1)
        for status in (ModelIngestionStatus.SUCCESS, ModelIngestionStatus.FAILED,
                       ModelIngestionStatus.CANCELLED):
            with self.subTest(status=status):
                state = SimpleNamespace(
                    status=status, version_id="version", progress_message="details"
                )
                client = SimpleNamespace(model_ingestion=SimpleNamespace(
                    get_ingestion=lambda *_: SimpleNamespace(status_data=state)
                ))
                if status == ModelIngestionStatus.SUCCESS:
                    self.assertEqual(tool.wait_for_publication(client, sent), "version")
                else:
                    with self.assertRaisesRegex(RuntimeError, status.value):
                        tool.wait_for_publication(client, sent)
        with self.assertRaises(TimeoutError):
            tool.wait_for_publication(client, sent, timeout=0)

    def test_cli_rejects_unsafe_publication(self):
        base = [
            "--project-id", "project", "--model-id", "input",
            "--version-id", "version", "--code-revision", "sha",
        ]
        for extra in (["--publish", "--output-model-id", ""],
                      ["--output-model-id", "input"],
                      ["--server", "http://example.com"]):
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    tool.parse_args(base + extra)

    def test_configured_model_defaults_and_overrides(self):
        required = ["--version-id", "version", "--code-revision", "sha"]
        args = tool.parse_args(required)
        self.assertEqual(args.project_id, "5616d1c8e8")
        self.assertEqual(args.model_id, "bffe1068f7")
        self.assertEqual(args.output_model_id, "83660f3739")
        self.assertFalse(args.publish)
        overridden = tool.parse_args(required + [
            "--project-id", "other-project", "--model-id", "other-input",
            "--output-model-id", "other-output", "--publish",
        ])
        self.assertEqual(overridden.project_id, "other-project")
        self.assertEqual(overridden.model_id, "other-input")
        self.assertEqual(overridden.output_model_id, "other-output")
        self.assertTrue(overridden.publish)

    def test_no_token_fails_before_connecting(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(tool, "SpeckleClient") as client:
                with self.assertRaisesRegex(SystemExit, "SPECKLE_TOKEN"):
                    tool.main([
                        "--project-id", "project", "--model-id", "input",
                        "--version-id", "version", "--code-revision", "sha",
                    ])
                client.assert_not_called()

    def test_receive_analyse_without_publishing_by_default(self):
        args = [
            "--project-id", "project", "--model-id", "input",
            "--version-id", "version", "--code-revision", "sha",
        ]
        with patch.dict(os.environ, {"SPECKLE_TOKEN": "test-only"}):
            with patch.object(tool, "SpeckleClient"), \
                 patch.object(tool.operations, "receive3") as receive, \
                 patch.object(tool.operations, "send3") as send:
                receive.return_value.__enter__.return_value.objects = [1, 2, 3]
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    tool.main(args)
                self.assertIn('"objectCount": 3', output.getvalue())
                self.assertIn('"sourceVersionId": "version"', output.getvalue())
                send.assert_not_called()

    def test_publishing_verifies_readback_and_reports_mismatch(self):
        result = self.result()
        client = MagicMock()
        sent = SendResult("project", "output-model", "version", "ingestion", 1)
        with patch.object(tool.operations, "send3", return_value=sent) as send, \
             patch.object(tool, "wait_for_publication", return_value="version"), \
             patch.object(tool.operations, "receive3") as receive, \
             contextlib.redirect_stdout(io.StringIO()):
            summary = receive.return_value.__enter__.return_value
            obj = summary.object_by_application_id.return_value
            obj.get_string.side_effect = lambda key: result[key]
            obj.get_double.return_value = 7
            self.assertEqual(
                tool.publish_result(client, "project", "output-model", result),
                "version",
            )
            self.assertEqual(send.call_args.args[1:3], ("project", "output-model"))
            obj.get_double.return_value = 99
            with self.assertRaisesRegex(RuntimeError, "readback failed"):
                tool.publish_result(client, "project", "output-model", result)

    def test_upload_failure_preserves_error_and_closes_files(self):
        with patch.object(
            tool.operations, "send3", side_effect=RuntimeError("Upload rejected")
        ):
            with self.assertRaisesRegex(RuntimeError, "Upload rejected"):
                tool.publish_result(MagicMock(), "project", "output", self.result())


if __name__ == "__main__":
    unittest.main()
