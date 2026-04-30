# System Requirements

This project is designed to run locally, in Docker, or on a VM. The tables
below describe practical minimum and recommended host combinations for the
combined ManuscriptPrep and Narrator's Toolkit stack.

The default deployment model is **local inference**. Manuscripts stay on the
host, and the narrator workflow uses local Ollama models unless a user
explicitly opts into a cloud LLM path.

## 1. Local inference mode

This is the normal, private deployment model.

### Inference backends

Ollama can use different acceleration paths depending on the host operating
system and hardware. The practical combinations for this project are:

| Hardware / platform | Primary inference path | Notes |
| --- | --- | --- |
| NVIDIA GPU on Linux or Windows | CUDA | Ollama documents NVIDIA support for GPUs with compute capability 5.0+ and driver version 531+ on its hardware support page. |
| AMD GPU on Linux or Windows | ROCm, with Vulkan as an additional path | Ollama documents ROCm support for AMD GPUs and notes Vulkan as an additional GPU path. ROCm support on Linux requires the ROCm driver stack. |
| Apple Silicon on macOS | Metal | Ollama documents Metal-based GPU acceleration on Apple devices. |
| Intel GPU on Linux or Windows | Vulkan | Ollama documents Vulkan as an experimental GPU path and links Linux Intel driver guidance for Vulkan-capable systems. |
| Intel Mac or CPU-only host | CPU fallback | Ollama supports x86 macOS as CPU-only. CPU-only inference is usable for experimentation but is not the preferred production profile for this project. |

The relevant APIs are:

- CUDA for NVIDIA
- ROCm for AMD where supported
- Metal for Apple Silicon
- Vulkan for cross-vendor Linux and Windows GPU paths

Ollama's current public documentation does not describe an OpenCL inference
backend. For this stack, the documented acceleration paths to plan around are
CUDA, ROCm, Metal, and Vulkan.

Ollama also provides a cloud model option, but that is a separate deployment
choice and not the default for ManuscriptPrep.

### Minimum supported local-LLM setup

Use this if you want the stack to run on a single machine and you are willing to
accept slower model execution on larger books.

| Component | Minimum |
| --- | --- |
| Operating system | macOS 13+ on Apple Silicon, Ubuntu 22.04 LTS / 24.04 LTS, or Windows 11 with WSL2 / Docker |
| CPU | 8 logical cores |
| Memory | 32 GB RAM |
| Storage | 30 GB free SSD space |
| Browser | Current Chromium, Firefox, or Safari |
| GPU | NVIDIA 8 GB VRAM+, AMD 8 GB VRAM+, Apple Silicon unified memory equivalent, or Vulkan-capable Intel iGPU for lighter workloads |

This minimum profile is suitable for:

- the web UI
- manuscript ingest and cleaning
- narrator viewing
- smaller or text-based PDFs

Expect OCR, large books, and local Ollama models to run slowly on this profile.
CPU-only operation is possible for experimentation, but it is not the expected
production baseline for local inference.

### Recommended local-LLM setup

Use this for day-to-day authoring, narration prep, and model-heavy workflows.

| Component | Recommended |
| --- | --- |
| Operating system | macOS 14+ on Apple Silicon, Ubuntu 24.04 LTS, or Windows 11 Pro with Docker / WSL2 |
| CPU | 8 to 16 physical cores |
| Memory | 64 GB RAM |
| Storage | 100 GB free SSD space |
| Browser | Current Chromium, Firefox, or Safari |
| GPU | NVIDIA 12 to 24 GB VRAM, AMD 12 to 24 GB VRAM, Apple Silicon unified memory equivalent, or higher-end Vulkan-capable Intel graphics |

This recommended profile is suitable for:

- the full ManuscriptPrep pipeline
- Ollama model execution on the same machine
- OCR-heavy PDFs
- multiple books or long manuscripts
- the Narrator's Toolkit queue and reader experience

## 2. Cloud-assisted mode

This mode is opt-in and should only be used when the user explicitly accepts
cloud processing of manuscript-derived text.

| Component | Minimum |
| --- | --- |
| Operating system | Any modern OS with a current browser and network access |
| CPU | 4 logical cores |
| Memory | 8 GB RAM |
| Storage | 10 GB free SSD space |
| Browser | Current Chromium, Firefox, or Safari |
| GPU | Not required |

This mode can reduce local hardware requirements because the LLM runs in a
trusted cloud service rather than on the local host. The manuscript ingest and
cleaning pipeline still runs locally unless explicitly reconfigured.

## Docker and VM guidance

- For a Docker host, use the recommended local-LLM profile if Ollama and the
  gateway run on the same machine.
- For a VM, allocate the same CPU and memory as the recommended local-LLM setup
  if the VM is responsible for ingest, orchestration, and model execution.
- If Ollama runs on a different host, the local machine can be smaller, but the
  remote Ollama host still needs the recommended local-LLM resources.

## Practical notes

- SSD storage matters more than raw CPU once the pipeline starts writing chunks,
  manifests, reports, and Ollama model layers.
- The Narrator's Toolkit viewer itself is light; the heavy requirements come from
  PDF extraction, OCR, and local model execution.
- If you only use the web UI against a remote gateway, the browser machine can
  be much smaller than the processing host.
- The cloud-assisted mode is a deployment choice, not the default privacy model.
  Keep it opt-in and document exactly which text leaves the local machine if you
  enable it.
