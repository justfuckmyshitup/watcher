# Local Model Setup

Local Scribe is a bring-your-own-model project. The repository documents a tested reference profile, but model weights are not bundled and should not be committed. See `docs/BYOM_MODEL_GUIDE.md` for the community-facing model policy.

The backend supports a provider abstraction:

- `mock`: deterministic placeholder generation, no real AI analysis.
- `ollama`: host-local Ollama endpoint.
- `lmstudio`: host-local LM Studio OpenAI-compatible endpoint.
- `onnx-phi`: local ONNX Runtime GenAI provider. The reference POC profile uses `microsoft/Phi-4-mini-reasoning-onnx`.

Set `LOCAL_SCRIBE_PROVIDER=mock`, `ollama`, `lmstudio`, or `onnx-phi`, or pass `-ModelProvider` to the Windows launcher.

## Hugging Face ONNX Phi Reference POC

The reference POC reasoning model is downloaded only when explicitly requested:

```powershell
.\scripts\download-models.ps1 -Profile poc
.\scripts\check-models.ps1 -Profile poc
```

The `poc` profile selects:

- Repo: `microsoft/Phi-4-mini-reasoning-onnx`
- Include pattern: `gpu/*`
- Selected model path: `models/llm/microsoft--Phi-4-mini-reasoning-onnx/gpu/gpu-int4-rtn-block-32`
- Provider: ONNX Runtime GenAI CUDA
- License: MIT

Run with the local ONNX provider:

```powershell
.\start.ps1 -ModelProvider onnx-phi -RequireGpu
```

The launcher sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` for the ONNX Phi provider after model files are expected to be local.

Install the runtime package explicitly inside `.venv` after confirming Python/CUDA compatibility:

```powershell
.\.venv\Scripts\python.exe -m pip install --pre onnxruntime-genai-cuda
```

The launcher does not download models during normal startup. If `-ModelProvider onnx-phi` or `LOCAL_SCRIBE_PROVIDER=onnx-phi` is used and model files are missing, startup fails with the download command to run. This keeps normal operation local and repeatable.

## Ollama

Install Ollama on the host, pull a model, and start it:

```powershell
ollama pull llama3.1:8b
ollama serve
```

Use:

```powershell
$env:LOCAL_SCRIBE_PROVIDER="ollama"
$env:LOCAL_SCRIBE_OLLAMA_URL="http://127.0.0.1:11434"
```

## LM Studio

Start the LM Studio local server and load a model. Use:

```powershell
$env:LOCAL_SCRIBE_PROVIDER="lmstudio"
$env:LOCAL_SCRIBE_LMSTUDIO_URL="http://127.0.0.1:1234"
```

## Offline Runtime

After dependencies and local models are installed, the app does not require internet access for core runtime. Model providers should point only at localhost or host-local Docker bridge addresses.

For the ONNX Phi provider, startup sets or respects:

```powershell
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```
