# Linux NVIDIA Setup

Linux support depends on desktop environment and capture protocol.

## Capture Caveats

Wayland and X11 have different capture permission models. Electron `getDisplayMedia` support may vary by compositor and portal configuration.

## NVIDIA Checks

```sh
nvidia-smi
docker info
```

For Dockerized GPU inference, install NVIDIA Container Toolkit and verify passthrough separately.

## Recommended Path

Run screen capture in the desktop shell and use a host-local model runtime such as Ollama or llama.cpp with CUDA. Keep Docker limited to backend API/storage/workers unless GPU passthrough is deliberately configured.

## Verify Acceleration

Monitor `nvidia-smi` during generation and confirm the UI diagnostics. Do not treat CPU fallback as GPU success.

