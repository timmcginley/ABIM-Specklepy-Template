"""Receive a Speckle version, count its objects, and optionally publish a summary."""

import argparse
from datetime import datetime, timezone
import json
import os
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

from specklepy.api import operations
from specklepy.api.client import SpeckleClient
from specklepy.api.models.current import ModelIngestionStatus
from specklepy.bundle import BundleBuilder, Producer
from specklepy.bundle.model import Model
from specklepy.bundle.send import SendResult


FUNCTION_ID = "student-template/count-model-objects"
FUNCTION_VERSION = "1.0.0"

# Change these example IDs to your team's project, input model and results model.
# Command-line arguments can override them. Never put an access token here.
PROJECT_ID = "5616d1c8e8"
INPUT_MODEL_ID = "bffe1068f7"
OUTPUT_MODEL_ID = "83660f3739"


def analyse_model(model: Model) -> dict[str, int]:
    """Replace this calculation with your own; do not load or modify inputs here.

    Counts Speckle objects, including non-building objects if present. This is
    a connection smoke test, not a count of IFC elements or a design assessment.
    """
    return {"objectCount": len(model.objects)}


def build_result(
    metrics: dict[str, int],
    server: str,
    project_id: str,
    model_id: str,
    version_id: str,
    code_revision: str,
) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "runId": str(uuid4()),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "functionId": FUNCTION_ID,
        "functionVersion": FUNCTION_VERSION,
        "codeRevision": code_revision,
        "sourceServer": server,
        "sourceProjectId": project_id,
        "sourceModelId": model_id,
        "sourceVersionId": version_id,
        "executionStatus": "completed",
        "assessment": "not-applicable",
        "purpose": "Connection smoke test; object count is not an IFC element count.",
        **metrics,
    }


def build_summary(result: dict[str, object], output_dir: str) -> BundleBuilder:
    builder = BundleBuilder(
        Producer("masterbpmn-student-template", FUNCTION_VERSION),
        "m",
        output_dir=output_dir,
    )
    builder.get_or_add_object(f"run-{result['runId']}").set_properties(
        result, name="Model object count (smoke test)"
    )
    return builder


def wait_for_publication(
    client: SpeckleClient, sent: SendResult, timeout: float = 120
) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ingestion = client.model_ingestion.get_ingestion(
            sent.project_id, sent.ingestion_id
        )
        state = ingestion.status_data
        if state.status == ModelIngestionStatus.SUCCESS:
            if state.version_id != sent.version_id:
                raise RuntimeError("Published version does not match the upload.")
            return sent.version_id
        if state.status in (
            ModelIngestionStatus.FAILED,
            ModelIngestionStatus.CANCELLED,
        ):
            raise RuntimeError(
                f"Publication {state.status.value}: "
                f"{state.progress_message or 'No server explanation supplied.'}"
            )
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise TimeoutError(
        f"Publication is still pending after {timeout:g}s. Inspect ingestion "
        f"{sent.ingestion_id} / reserved version {sent.version_id} before retrying; "
        "the upload may still complete."
    )


def publish_result(
    client: SpeckleClient,
    project_id: str,
    output_model_id: str,
    result: dict[str, object],
) -> str:
    with TemporaryDirectory(prefix="student-speckle-result-") as directory:
        builder = build_summary(result, directory)
        # Close SDK writers even if authentication/upload fails before build().
        with builder.pipeline:
            sent = operations.send3(
                client.account, project_id, output_model_id, builder
            )
    print(
        f"Uploaded ingestion {sent.ingestion_id}; "
        f"waiting for reserved version {sent.version_id}.",
        flush=True,
    )
    version_id = wait_for_publication(client, sent)
    with operations.receive3(
        client.account, project_id, output_model_id, version_id,
        include_geometry=False,
    ) as published:
        summary = published.object_by_application_id(f"run-{result['runId']}")
        if (
            summary is None
            or summary.get_string("runId") != result["runId"]
            or summary.get_string("sourceVersionId") != result["sourceVersionId"]
            or summary.get_double("objectCount") != result["objectCount"]
        ):
            raise RuntimeError(
                f"Version {version_id} was published but result readback failed."
            )
    return version_id


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="https://app.speckle.systems")
    parser.add_argument("--project-id", default=PROJECT_ID)
    parser.add_argument("--model-id", default=INPUT_MODEL_ID, help="Input model ID.")
    parser.add_argument("--version-id", required=True, help="Exact input version ID.")
    parser.add_argument(
        "--code-revision", required=True,
        help="Git commit SHA of this file in your repository.",
    )
    parser.add_argument(
        "--output-model-id", default=OUTPUT_MODEL_ID,
        help="Separate, existing results model.",
    )
    parser.add_argument(
        "--publish", action="store_true",
        help="Explicitly upload a new result version; otherwise only print results.",
    )
    args = parser.parse_args(argv)
    if not args.server.startswith("https://"):
        parser.error("--server must use HTTPS.")
    if args.publish and not args.output_model_id:
        parser.error("--publish requires --output-model-id.")
    if args.output_model_id == args.model_id:
        parser.error("Use a separate output model to preserve the input model's history.")
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    token = os.environ.get("SPECKLE_TOKEN")
    if not token:
        raise SystemExit(
            "Set SPECKLE_TOKEN locally to your own token. "
            "Never put it in this file, GitHub, Toolbench or a command argument."
        )
    client = SpeckleClient(host=args.server)
    client.authenticate_with_token(token)
    client.model.get(args.model_id, args.project_id)
    if args.publish:
        client.model.get(args.output_model_id, args.project_id)
    with operations.receive3(
        client.account, args.project_id, args.model_id, args.version_id,
        include_geometry=False,
    ) as model:
        result = build_result(
            analyse_model(model), args.server, args.project_id,
            args.model_id, args.version_id, args.code_revision,
        )
    print(json.dumps(result, indent=2))
    if args.publish:
        version_id = publish_result(
            client, args.project_id, args.output_model_id, result
        )
        print(f"Published and read back result version: {version_id}")
        print(
            f"{args.server.rstrip('/')}/projects/{args.project_id}"
            f"/models/{args.output_model_id}"
        )
    else:
        print("Read-only run. Add --publish to send results to the configured output model.")


if __name__ == "__main__":
    main()
