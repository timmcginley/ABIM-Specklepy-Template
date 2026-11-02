# ABIM-Specklepy-Template
A template repo for developing python tools with speckle in the Advanced BIM course at DTU

# Student Speckle Python template

Standalone receive -> analyse -> optionally publish example for the
[ABD-26 workspace](https://app.speckle.systems/workspaces/abd-26).
It does not change the Node application, execute in Toolbench, or load code
from GitHub.

## What it does

1. Authenticates using your local `SPECKLE_TOKEN` environment variable.
2. Receives one explicitly selected input model version, without geometry.
3. Counts Speckle objects. This is not a count of IFC building elements:
   published models may include other objects.
4. Prints structured results with a unique run ID, source version and declared
   code revision. This smoke test makes no engineering assessment.
5. With `--publish`, sends a non-geometric summary to a separate existing model
   in the same project. It waits up to 120 seconds for ingestion, reports
   failures explicitly, then receives the result to verify its run ID, source
   version and count.

The script never creates projects/models or overwrites a source version.
Each publication creates a new result version. Check an outstanding ingestion
before retrying a timed-out publication; it may still complete.
The summary has no geometry, so inspect its properties or receive it in Python;
do not expect a visible building in the 3D viewer.

## Prerequisites

- Python 3.11+; validated locally with Python 3.12.
- The pinned `specklepy[bundle]` dependency in [requirements.txt](requirements.txt).
- A source version in Speckle's 2026.9 bundle format. This example uses
  `receive3`/`send3`, not legacy `Base`/`operations.receive` workflows. Older
  object-graph versions are not supported by this template; confirm the format
  of your selected version rather than assuming all existing cloud models use it.
- Read access to the input, and publishing access to the results model.
- An existing results model, for example `student-results/your-team/object-count`,
  in the same project as the source. Do not use the source model as the target.

The workspace URL is not a project/model/version address. Open the source
project/model and copy its project ID, model ID and a specific version ID from
Speckle. Copy the separate results model ID too.

The template currently defaults to project `5616d1c8e8`,
[input model `bffe1068f7`](https://app.speckle.systems/projects/5616d1c8e8/models/bffe1068f7)
and [results model `83660f3739`](https://app.speckle.systems/projects/5616d1c8e8/models/83660f3739).
Students should change the commented constants near the top of the Python file
or override them with CLI arguments. An exact input version is still required.

## Local setup and first run (PowerShell)

From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\student-template\requirements.txt
```

Use your own minimally scoped Speckle personal access token for this local
script. Never share it, commit it, add it to Python source, or paste it into
Toolbench. Enter it without recording it in shell command history:

```powershell
$env:SPECKLE_TOKEN = [System.Net.NetworkCredential]::new('', (Read-Host 'Speckle token' -AsSecureString)).Password
```

With the configured model defaults, supply the input version ID and the Git
commit containing your student script. Start without publishing:

```powershell
.\.venv\Scripts\python.exe .\student-template\speckle_tool.py `
  --version-id YOUR_INPUT_VERSION_ID `
  --code-revision YOUR_SCRIPT_GIT_COMMIT_SHA
```

To also publish, repeat that command with:

```text
--publish
```

Use `--project-id`, `--model-id` and `--output-model-id` to override the defaults
when using other models.

Remove the token from this shell when finished:

```powershell
Remove-Item Env:SPECKLE_TOKEN
```

Authentication, permissions, format and network errors terminate the script;
they are not converted into a successful zero count. Do not share unredacted
error output if it contains private project information.

## Adapt it to your tool

Copy [speckle_tool.py](speckle_tool.py) into your team's GitHub repository.
Give `FUNCTION_ID` a stable team/function name and update `FUNCTION_VERSION`
when behaviour changes. Replace `analyse_model` with your own calculation and
update its result schema, publisher/readback and tests together.

The reusable analysis takes a caller-supplied Speckle `Model`, not an
IfcOpenShell model. Importing the file does not authenticate, download or
publish. Local orchestration runs only under the main guard. Keep tokens and
model selection outside the reusable analysis. Geometry-dependent work would
need geometry loading explicitly enabled.

The `code_revision` is a caller-declared provenance value, not automatically
verified by this template. Commit your script and supply that commit SHA when
running it. A future Toolbench integration could record a GitHub file URL and
commit plus function name; fetching or executing that code is not implemented.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s student-template -p "test_*.py" -v
```

Offline tests exercise the installed SDK's real bundle serialization/readback,
import safety, provenance, publication status handling and CLI safeguards.
Network orchestration is mocked. A live round trip in the academic workspace
still requires an authorized user, actual model/version IDs and a local token.

SDK reference:
[Speckle Python quickstart](https://docs.speckle.systems/developers/sdks/python/getting-started/quickstart.md).

