# Windows NVIDIA Setup

Windows with an NVIDIA RTX GPU is the primary acceleration target.

## Checks

```powershell
nvidia-smi
.\scripts\check-gpu.ps1
docker version
```

Confirm driver version and VRAM. For an RTX 3060 12GB, choose models that fit within available VRAM.

For the hardware-first POC gate:

```powershell
.\scripts\check-gpu.ps1 -RequireGpu
```

This must pass before live OCR/LLM POC profiles should run. It does not install NVIDIA drivers, CUDA, cuDNN, ONNX Runtime, or PaddlePaddle. It reports what is missing and leaves system-level installs to the user.

Strict provider checks are available once the OCR/LLM packages are installed:

```powershell
.\scripts\check-gpu.ps1 -RequireGpu -RequireCudaProvider
.\scripts\check-gpu.ps1 -RequireGpu -RequirePaddleGpu
.\scripts\check-ocr.ps1 -Provider paddle -RequireGpu
```

PaddleOCR GPU packages are not installed silently. Review the CUDA profile first, then install inside `.venv` with a compatible PaddlePaddle GPU wheel and the PaddleOCR package. For CUDA 12.6-class setups, the current documented Paddle package index is:

```powershell
.\.venv\Scripts\python.exe -m pip install paddlepaddle-gpu==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
.\.venv\Scripts\python.exe -m pip install paddleocr
```

Use the `cu118` index instead if your local CUDA/driver stack requires CUDA 11.8.

PaddlePaddle currently documents support for Python versions below Python 3.14. If your repo `.venv` was created with Python 3.14, recreate it with a supported Python such as Python 3.12 before installing PaddleOCR GPU packages.

The live POC helper checks this without installing system-level Python:

```powershell
.\scripts\setup-live-poc.ps1
```

After installing Python 3.12 manually, use:

```powershell
.\scripts\setup-live-poc.ps1 -ForceRecreateVenv -InstallRuntimePackages -DownloadModels
```

For the local ONNX reasoning model, download files explicitly and install ONNX Runtime GenAI CUDA only after confirming the Python/CUDA environment:

```powershell
.\scripts\download-models.ps1 -Profile poc
.\scripts\check-models.ps1 -Profile poc
.\.venv\Scripts\python.exe -m pip install --pre onnxruntime-genai-cuda
```

ONNX Runtime GenAI CUDA on Windows may need CUDA runtime DLLs from the local Python environment. The backend automatically exposes `.venv\Lib\site-packages\nvidia\*\bin`, `.venv\Lib\site-packages\onnxruntime\capi`, and `.venv\Lib\site-packages\onnxruntime_genai` before loading the CUDA provider. This keeps the POC repo-local when the installed GPU wheels include the needed CUDA DLLs, and avoids requiring a global CUDA Toolkit install for this profile.

Known warning on the current target machine: PaddleOCR may report that Paddle was compiled with cuDNN 9.9 while the visible runtime is cuDNN 9.5. The benchmark still passes, but this warning should be revisited if OCR crashes, produces inconsistent output, or becomes unstable under repeated runs.

## Recommended Path A: Host Runtime

Run the app with the Windows launcher. Run Ollama or LM Studio on Windows with GPU acceleration. Set:

```powershell
$env:LOCAL_SCRIBE_OLLAMA_URL="http://127.0.0.1:11434"
.\start.ps1 -ModelProvider ollama
```

or:

```powershell
$env:LOCAL_SCRIBE_LMSTUDIO_URL="http://127.0.0.1:1234"
.\start.ps1 -ModelProvider lmstudio
```

## Docker Backend

The backend can run in Docker while inference stays host-native:

```powershell
.\start.ps1 -DockerBackend
```

Use `host.docker.internal` for model URLs from inside the container.

## Confirm GPU Usage

- Use Ollama or LM Studio runtime diagnostics.
- Use `.\scripts\check-gpu.ps1` before launching live OCR/LLM profiles.
- Use `.\scripts\check-ocr.ps1 -Provider paddle -RequireGpu` before launching live OCR.
- Use `.\start.ps1 -RequireGpu` to make the launcher fail if no NVIDIA GPU is detected.
- Use `.\start.ps1 -OcrProvider paddle -OcrProfile screen-fast -RequireGpu` to make OCR startup require GPU readiness.
- Use `.\scripts\benchmark-poc.ps1 -OcrProvider paddle -ModelProvider onnx-phi -RequireGpu -Offline` to prove OCR/LLM throughput and temp cleanup.
- Watch `nvidia-smi` while generating.
- Confirm the UI does not show silent CPU fallback.
- Use `.\scripts\check-deps.ps1 -DockerBackend` to check Docker mode before launching.

## CPU Fallback

CPU fallback is explicit only for the live POC path:

```powershell
.\start.ps1 -AllowCpuFallback
```

If CPU fallback appears unexpectedly, verify the local model runtime has GPU support, the model fits VRAM, and Docker is not hiding host GPU access.
