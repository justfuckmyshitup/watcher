# macOS Apple Silicon Setup

On Apple Silicon, keep model inference host-native when possible. Docker is useful for the backend but is usually not the best path for MLX or Metal acceleration.

## Screen Recording

macOS requires Screen Recording permission for the desktop shell. Start capture from the app and approve the OS prompt.

## Host Runtime Options

- Ollama host-native
- LM Studio host-native
- llama.cpp Metal
- Future MLX provider

## Verify Acceleration

Use the selected runtime's diagnostics and system Activity Monitor GPU/Neural Engine indicators where available. The Local Scribe UI should show mock mode, CPU fallback, or local runtime status clearly.

