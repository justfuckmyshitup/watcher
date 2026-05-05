# Bring Your Own Model Guide

Local Scribe is designed to run locally without bundling model weights. The project should stay lightweight on GitHub: code, docs, scripts, tests, and configuration belong in the repo; downloaded models do not.

## Recommended Community Default

For demos and community support, describe the app as bring-your-own-model with one documented reference profile:

- Reference provider: `onnx-phi`
- Reference model: `microsoft/Phi-4-mini-reasoning-onnx`
- Expected location: `models/llm/microsoft--Phi-4-mini-reasoning-onnx/gpu/gpu-int4-rtn-block-32`
- Runtime: ONNX Runtime GenAI CUDA
- Target hardware: RTX 3060-class NVIDIA GPU or better
- Download command: `.\scripts\download-models.ps1 -Profile poc`

This is a tested POC profile, not a hard dependency. Users may choose Ollama, LM Studio, another ONNX profile, or mock mode.

## Provider Options

### ONNX Phi

Use this when you want an offline, repo-local model directory after an explicit download.

```powershell
.\scripts\download-models.ps1 -Profile poc
.\scripts\check-models.ps1 -Profile poc
.\start.ps1 -ModelProvider onnx-phi -RequireGpu
```

The launcher expects files to already exist when running offline. Normal startup should not repeatedly pull from the internet.

### Ollama

Use this when a user already runs Ollama locally and wants to manage models outside this repo.

```powershell
$env:LOCAL_SCRIBE_PROVIDER="ollama"
$env:LOCAL_SCRIBE_OLLAMA_URL="http://127.0.0.1:11434"
.\start.ps1
```

### LM Studio

Use this when a user prefers LM Studio's local OpenAI-compatible server.

```powershell
$env:LOCAL_SCRIBE_PROVIDER="lmstudio"
$env:LOCAL_SCRIBE_LMSTUDIO_URL="http://127.0.0.1:1234"
.\start.ps1
```

### Mock

Use mock mode for CI, screenshots, launcher validation, and privacy tests that should not require GPU hardware or model downloads.

```powershell
.\start.ps1 -Mock
python -m pytest backend\tests
```

## Repository Rules

Do not commit:

- Model weights or downloaded Hugging Face snapshots
- `models/manifest.json` with local machine paths
- SQLite databases
- Raw screenshots, frame captures, OCR dumps, exports, or launcher logs
- `.env` files with local provider details

Safe to commit:

- `.env.example`
- model setup docs
- provider adapter code
- deterministic tests using mock/local fixtures
- scripts that explicitly download or validate model files

## Adding A New Model Profile

When adding a model profile, include:

- Provider name
- Model source and license
- Hardware expectation
- Approximate disk and VRAM requirements if known
- Explicit download/check command
- Offline startup behavior
- Privacy notes if prompts or outputs are cached anywhere

Keep model selection user-controlled. Do not silently install system-level runtimes, GPU drivers, or model managers.
