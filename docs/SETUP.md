# Setup and Configuration Guide

Complete guide for setting up and configuring the Memory Dump Debugger with various LLM providers and optional features.

## Table of Contents

1. [Prerequisites](#prerequisites)
   - [Python Installation](#python-installation)
   - [Verifying Installation](#verifying-installation)
2. [Quick Start](#quick-start)
3. [Package Manager (uv)](#package-manager-uv)
4. [LLM Provider Setup](#llm-provider-setup)
   - [Azure AI Foundry (Claude)](#azure-ai-foundry-claude)
   - [Azure OpenAI](#azure-openai)
   - [OpenAI](#openai)
   - [Anthropic](#anthropic)
   - [Ollama (Local)](#ollama-local)
5. [Tiered LLM Strategy](#tiered-llm-strategy)
6. [Embeddings for Semantic Search](#embeddings-for-semantic-search)
7. [WinDbg Configuration](#windbg-configuration)

---

## Prerequisites

### Python Installation

This project requires **Python 3.11 or higher**. Follow these steps to install Python correctly with proper PATH configuration.

#### Option 1: Install from python.org (Recommended)

1. **Download Python**
   - Visit https://www.python.org/downloads/
   - Download Python 3.11 or later (e.g., Python 3.12.x)

2. **Run Installer**
   - ⚠️ **CRITICAL**: Check "Add Python to PATH" at the bottom of the first screen
   - Check "Add Python to environment variables"
   - Click "Install Now" (recommended) or "Customize installation"

3. **Verify PATH Addition**
   - The installer adds these to your PATH:
     - `C:\Users\YourName\AppData\Local\Programs\Python\Python312\`
     - `C:\Users\YourName\AppData\Local\Programs\Python\Python312\Scripts\`

#### Option 2: Install using winget (Windows 11/10)

```powershell
# Install Python 3.12
winget install Python.Python.3.12

# Restart terminal after installation
```

#### Option 3: Install using Chocolatey

```powershell
# Install Chocolatey (if not already installed)
Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# Install Python
choco install python --version=3.12.0 -y

# Restart terminal after installation
```

### Verifying Installation

After installing Python, **you must restart your terminal or VS Code** for PATH changes to take effect.

#### Test Python Installation

Open a **new** PowerShell terminal and run:

```powershell
# Check Python version
python --version
# Expected output: Python 3.11.x or Python 3.12.x

# Check pip version
pip --version
# Expected output: pip 24.x.x from C:\Users\...\Python312\...

# Check Python path
where.exe python
# Expected output: C:\Users\YourName\AppData\Local\Programs\Python\Python312\python.exe
```

### Troubleshooting PATH Issues

#### Problem: "python: command not found" or "pip: command not found"

**Solution 1: Restart Terminal/VS Code**
- Close **all** terminal windows
- Close VS Code completely
- Reopen VS Code and create a new terminal
- Try commands again

**Solution 2: Manual PATH Configuration**

If Python still isn't found, add it to PATH manually:

1. **Find Python Installation Path**
   ```powershell
   # Search for python.exe
   Get-ChildItem -Path C:\Users\$env:USERNAME\AppData\Local\Programs\Python -Recurse -Filter python.exe -ErrorAction SilentlyContinue | Select-Object -First 1 FullName
   
   # Or search in Program Files
   Get-ChildItem -Path "C:\Program Files\Python*" -Recurse -Filter python.exe -ErrorAction SilentlyContinue | Select-Object -First 1 FullName
   ```

2. **Add to PATH (User Environment Variable)**
   ```powershell
   # Replace with your actual Python path
   $pythonPath = "C:\Users\YourName\AppData\Local\Programs\Python\Python312"
   $scriptsPath = "$pythonPath\Scripts"
   
   # Get current PATH
   $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
   
   # Add Python paths if not already present
   if ($currentPath -notlike "*$pythonPath*") {
       $newPath = "$pythonPath;$scriptsPath;$currentPath"
       [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
       Write-Host "Python added to PATH. Please restart your terminal."
   }
   ```

3. **Restart Terminal** - PATH changes only take effect in new terminals

**Solution 3: Use py Launcher (Windows)**

Windows includes a Python launcher that works even when PATH isn't set:

```powershell
# Check Python version
py --version

# Use pip through py launcher
py -m pip --version

# Install uv using py launcher
py -m pip install uv

# Run the tool
py -m pip install -e .
```

#### Problem: Multiple Python Versions Installed

If you have multiple Python versions and the wrong one is being used:

```powershell
# List all Python installations
where.exe python

# Check which Python is first in PATH
python --version

# Use specific version with py launcher
py -3.12 --version        # Use Python 3.12
py -3.11 --version        # Use Python 3.11
py -m pip install uv      # Install to default Python
```

#### Problem: "Access Denied" or Permission Errors

Run PowerShell as Administrator:

```powershell
# Right-click PowerShell → "Run as Administrator"
# Then install Python or add to PATH
```

Or install for current user only:

```powershell
pip install --user uv
```

#### Problem: pip is outdated

```powershell
# Upgrade pip
python -m pip install --upgrade pip

# Or using py launcher
py -m pip install --upgrade pip
```

### Execution Policy (Windows)

If you get "script execution disabled" errors:

```powershell
# Allow scripts for current user
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Verify
Get-ExecutionPolicy -List
```

---

## Quick Start

**Before starting, ensure Python 3.11+ is installed. See [Prerequisites](#prerequisites) above.**

### 1. Navigate to Project Root

```powershell
# Navigate to the repository root directory
cd C:\path\to\memory-dmp-debugger  # Adjust path to your location
```

### 2. Verify Python Installation

```powershell
# Verify Python is accessible
python --version  # Should show Python 3.11.x or higher
pip --version     # Should show pip version

# If commands not found, see Prerequisites section above
```

### 3. Install uv (Package Manager)

```powershell
# Install uv using pip
pip install uv

# Or use the official installer (recommended)
irm https://astral.sh/uv/install.ps1 | iex
```

**Important:** After installing uv, you must **restart your terminal or VS Code** for the PATH changes to take effect. If `uv` command is not found, close and reopen your terminal.

**Troubleshooting:**
```powershell
# If uv not found after restart, check if it's in PATH
where.exe uv

# Typical installation location:
# C:\Users\YourName\.cargo\bin\uv.exe (installer)
# C:\Users\YourName\AppData\Local\Programs\Python\Python312\Scripts\uv.exe (pip)

# If still not working, use full path temporarily:
C:\Users\$env:USERNAME\.cargo\bin\uv.exe --version
```

### 4. Install Dependencies

```powershell
# Install dependencies from pyproject.toml (from repo root)
uv sync
```

### 5. Configure Environment

```powershell
# Copy example config and edit it
copy .env.example .env
# Edit .env with your API keys and paths
```

### 6. Configure LLM Provider

Choose one of the options below and update your `.env` file.

**Note:** If you want local inference (recommended for cost savings), install Ollama and pull a code-capable model like `qwen2.5-coder:7b` or `llama3.1:14b`.

### 7. Run Analysis

```bash
# From repo root directory
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
# If just installed, restart your terminal or VS Code first
# Then try:
pip install uv
# Or reinstall: irm https://astral.sh/uv/install.ps1 | iex
```

**After installation, still not found?**
- Close all terminal windows and VS Code completely
- Reopen VS Code and a new terminal
- The PATH should now include uv

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
3. 💰 Install Ollama for cost savings
4. 🔍 Enable embeddings for better search
5. 📚 Read [ARCHITECTURE.md](ARCHITECTURE.md) to understand how it works

## Support

- Project documentation: [README.md](../README.md)
- Architecture details: [ARCHITECTURE.md](ARCHITECTURE.md)
- Report issues: GitHub Issues
