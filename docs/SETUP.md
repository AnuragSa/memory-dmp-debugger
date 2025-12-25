# Setup and Configuration Guide

Complete guide for setting up and configuring the Memory Dump Debugger with various LLM providers and optional features.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Package Manager (uv)](#package-manager-uv)
3. [LLM Provider Setup](#llm-provider-setup)
   - [Azure AI Foundry (Claude)](#azure-ai-foundry-claude)
   - [Azure OpenAI](#azure-openai)
   - [OpenAI](#openai)
   - [Anthropic](#anthropic)
   - [Ollama (Local)](#ollama-local)
4. [Tiered LLM Strategy](#tiered-llm-strategy)
5. [Embeddings for Semantic Search](#embeddings-for-semantic-search)
6. [WinDbg Configuration](#windbg-configuration)

---

## Quick Start

### 1. Install uv (Package Manager)

```powershell
# Install uv
pip install uv

# Or use the installer (recommended)
irm https://astral.sh/uv/install.ps1 | iex
```

### 2. Install Dependencies

```powershell
# Install dependencies from pyproject.toml
uv sync
```

### 3. Configure LLM Provider

Choose one of the options below and update your `.env` file.

### 4. Run Analysis

```bash
uv run dump-debugger analyze crash.dmp --issue "Why is the app slow?"
```

---

## Package Manager (uv)

This project uses **uv** - a fast Python package manager written in Rust.

### Why uv?

- ⚡ **10-100x faster** than pip/poetry
- 🎯 **Simple**: No complex configuration
- 🔒 **Reliable**: Lockfile for reproducible installs
- 🐍 **Python version management**: Built-in Python installation

### Common Commands

```powershell
# Install dependencies
uv sync

# Run the CLI
uv run dump-debugger analyze "C:\dumps\crash.dmp" --issue "Investigate issues"

# Run tests
uv run pytest

# Add a dependency
uv add langchain-anthropic

# Add a dev dependency
uv add --dev pytest

# Show installed packages
uv pip list
```

### Project Files

- **pyproject.toml**: Project metadata and dependencies
- **uv.lock**: Lockfile (auto-generated, commit to git)
- **.venv/**: Virtual environment (auto-created, don't commit)

### Troubleshooting

**"uv: command not found"**
```powershell
pip install uv
# Or reinstall: irm https://astral.sh/uv/install.ps1 | iex
```

**Clear cache**
```powershell
uv cache clean
```

**Force reinstall**
```powershell
Remove-Item -Recurse -Force .venv
uv sync
```

---

## LLM Provider Setup

### Azure AI Foundry

Recommended for enterprise deployments using Claude Sonnet 3.5+ or a model capable of reasoning over code.

#### Prerequisites
1. Azure AI Foundry project with deployed model (e.g., Claude 3.5 Sonnet)
2. API key for your project

#### Configuration

```env
# .env
LLM_PROVIDER=azure

# Azure AI Foundry credentials
AZURE_OPENAI_ENDPOINT=https://your-project.services.ai.azure.com/models
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_DEPLOYMENT=claude-3-5-sonnet
AZURE_OPENAI_API_VERSION=2024-10-01-preview
```

#### Get Credentials

From Azure AI Foundry portal (https://ai.azure.com):
1. Navigate to your project
2. Go to **Settings** → **Project properties** for endpoint
3. Go to **Settings** → **API keys** for API key
4. Note the **Model name** (e.g., `claude-3-5-sonnet`)

---

### Azure OpenAI

For GPT-4 or other OpenAI models hosted in Azure.

#### Configuration

```env
# .env
LLM_PROVIDER=azure

# Azure OpenAI credentials
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4
AZURE_OPENAI_API_VERSION=2024-02-15-preview
```

---

### OpenAI

Direct OpenAI API access.

#### Configuration

```env
# .env
LLM_PROVIDER=openai

OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=gpt-4-turbo-preview
```

---

### Anthropic

Direct Anthropic API access for Claude.

#### Configuration

```env
# .env
LLM_PROVIDER=anthropic

ANTHROPIC_API_KEY=your-api-key-here
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```

---

### Ollama (Local)

Run LLMs locally for cost savings and privacy.

#### What is Ollama?

- **Cost savings**: No API charges
- **Speed**: Fast for simple tasks
- **Privacy**: Data stays on your machine

#### Installation

**Windows:**
- Download from: https://ollama.com/download
- Run installer
- Ollama starts automatically on `http://localhost:11434`

**macOS/Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

#### Pull a Model

```bash
# Recommended: balanced speed and quality
ollama pull qwen2.5-coder:7b

# Alternatives
ollama pull llama3.1:8b    # Smaller, faster
ollama pull llama3.1:14b   # Larger, better quality
```

#### Configuration

**Local Only:**
```env
# .env
LLM_PROVIDER=ollama
USE_LOCAL_LLM=true
LOCAL_LLM_MODEL=qwen2.5-coder:7b
LOCAL_LLM_BASE_URL=http://localhost:11434
LOCAL_LLM_TIMEOUT=120
LOCAL_LLM_CONTEXT_SIZE=32768
```

#### Troubleshooting

**Connection refused**
```bash
# Start Ollama manually
ollama serve
```

**Model not found**
```bash
ollama pull qwen2.5-coder:7b
```

**Out of memory**
- Use smaller model: `llama3.1:8b`
- Close other applications
- Reduce `LOCAL_LLM_TIMEOUT`

---

## Tiered LLM Strategy

**Recommended setup** for optimal cost/quality balance.

### How It Works

Routes tasks to appropriate LLM based on complexity:

| Complexity | LLM Used | Cost | Speed | Example Commands |
|------------|----------|------|-------|-----------------|
| Simple | Local (Ollama) | Free | Fast | `!threads`, `!syncblk` |
| Moderate | Local (Ollama) | Free | Fast | `!dumpheap -stat` |
| Complex | Cloud (Azure/OpenAI) | $$$ | Moderate | `!CLRStack`, `~*e !CLRStack` |

### Configuration

```env
# .env - Tiered Strategy
USE_LOCAL_LLM=true
USE_TIERED_LLM=true
LOCAL_LLM_MODEL=qwen2.5-coder:7b
CLOUD_LLM_PROVIDER=azure

# Cloud credentials (for complex tasks)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_DEPLOYMENT=gpt-4
```

### Benefits

- **70% cost reduction** (simple tasks use free local LLM)
- **40% speed improvement** (local LLM is faster)
- **Same quality** for complex tasks (uses cloud LLM)

### Performance Comparison

| Setup | Cost/Analysis | Speed | Quality |
|-------|--------------|-------|---------|
| Cloud Only | $0.15 | 15 sec | High |
| Local Only | $0.00 | 10 sec | Medium |
| **Tiered** | **$0.05** | **9 sec** | **High** |

---

## Embeddings for Semantic Search

Optional feature for better context retrieval in interactive mode.

### Why Use Embeddings?

- **Better search accuracy**: 85-95% vs 60-70% keyword search
- **Semantic understanding**: Finds related concepts, not just exact matches
- **Cost**: Minimal (~$0.0002 per analysis)

### Azure OpenAI Setup

#### Deploy Embeddings Model

1. Go to [Azure OpenAI Studio](https://oai.azure.com/)
2. Navigate to **Deployments**
3. Create new deployment: `text-embedding-3-small`

#### Configuration

**Option A: Same Endpoint as Main LLM**
```env
# .env
# Main LLM config (above)
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4

# Embeddings (same resource)
USE_EMBEDDINGS=true
EMBEDDINGS_PROVIDER=azure
AZURE_EMBEDDINGS_DEPLOYMENT=text-embedding-3-small
```

**Option B: Separate Endpoint**
```env
# .env
# Main LLM config...

# Embeddings (separate resource)
USE_EMBEDDINGS=true
EMBEDDINGS_PROVIDER=azure
AZURE_EMBEDDINGS_DEPLOYMENT=text-embedding-3-small
AZURE_EMBEDDINGS_ENDPOINT=https://your-embeddings-resource.openai.azure.com/
AZURE_EMBEDDINGS_API_KEY=your-embeddings-key
```

### OpenAI Setup

```env
# .env
USE_EMBEDDINGS=true
EMBEDDINGS_PROVIDER=openai
EMBEDDINGS_MODEL=text-embedding-3-small
OPENAI_API_KEY=sk-...
```

### Disable Embeddings

```env
# .env
USE_EMBEDDINGS=false
# Falls back to keyword search
```

---

## WinDbg Configuration

### Install Windows Debugging Tools

Download from: https://aka.ms/windowssdk

Or install Windows SDK and select only "Debugging Tools for Windows"

### Configure Paths

```env
# .env
CDB_PATH=C:\\Program Files (x86)\\Windows Kits\\10\\Debuggers\\x64\\cdb.exe
WINDBG_PATH=C:\\Program Files (x86)\\Windows Kits\\10\\Debuggers\\x64\\windbg.exe
```

### Symbol Server

```env
# .env
# Format: SRV*local_cache*https://symbol_server
SYMBOL_PATH=SRV*c:\\symbols*https://msdl.microsoft.com/download/symbols
```

The cache directory (`c:\symbols`) will be created automatically.

### Command Timeout

```env
# .env
# Default: 1800 seconds (30 minutes)
COMMAND_TIMEOUT=1800
```

### Optional: Custom SOS/DAC Paths

For analyzing dumps from specific .NET versions:

```env
# .env
# Example for .NET 6.0
#SOS_DLL_PATH=C:\\Program Files\\dotnet\\shared\\Microsoft.NETCore.App\\6.0.x\\sos.dll

# Example for .NET Framework 4.8
#MSCORDACWKS_PATH=C:\\Windows\\Microsoft.NET\\Framework64\\v4.0.30319\\mscordacwks.dll
```

Leave commented to auto-detect from symbol server (recommended).

---

## Configuration Examples

### Minimal (Cloud Only)
```env
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_DEPLOYMENT=gpt-4
```

### Recommended (Tiered + Embeddings)
```env
# Tiered LLM
USE_LOCAL_LLM=true
USE_TIERED_LLM=true
LOCAL_LLM_MODEL=qwen2.5-coder:7b
CLOUD_LLM_PROVIDER=azure

# Azure OpenAI (for complex tasks + embeddings)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_DEPLOYMENT=gpt-4

# Embeddings
USE_EMBEDDINGS=true
EMBEDDINGS_PROVIDER=azure
AZURE_EMBEDDINGS_DEPLOYMENT=text-embedding-3-small
```

### Enterprise (Azure AI Foundry + Embeddings)
```env
# Claude via Azure AI Foundry
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-project.services.ai.azure.com/models
AZURE_OPENAI_API_KEY=your-foundry-key
AZURE_OPENAI_DEPLOYMENT=claude-sonnet-4-5

# Embeddings (separate Azure OpenAI resource)
USE_EMBEDDINGS=true
EMBEDDINGS_PROVIDER=azure
AZURE_EMBEDDINGS_DEPLOYMENT=text-embedding-3-small
AZURE_EMBEDDINGS_ENDPOINT=https://your-openai.openai.azure.com/
AZURE_EMBEDDINGS_API_KEY=your-openai-key
```

---

## Next Steps

1. ✅ Choose LLM provider and configure `.env`
2. ✅ Run your first analysis
3. 💰 Optional: Install Ollama for cost savings
4. 🔍 Optional: Enable embeddings for better search
5. 📚 Read [ARCHITECTURE.md](ARCHITECTURE.md) to understand how it works

## Support

- Project documentation: [README.md](../README.md)
- Architecture details: [ARCHITECTURE.md](ARCHITECTURE.md)
- Report issues: GitHub Issues
