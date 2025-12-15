# Using Claude Sonnet with Azure AI Foundry

This guide shows how to configure the memory dump debugger to use Claude Sonnet (or other models) hosted in Azure AI Foundry.

## Prerequisites

1. An Azure AI Foundry project with a deployed model (e.g., Claude 3.5 Sonnet)
2. API key for your Azure AI Foundry project

## Setup Instructions

### 1. Install the Azure AI Inference SDK

The tool will automatically use the Azure AI SDK when configured. First, ensure dependencies are installed:

```bash
pip install azure-ai-inference
```

Or if using uv (recommended):

```bash
uv pip install azure-ai-inference
```

### 2. Get Your Azure AI Foundry Credentials

From the Azure AI Foundry portal (https://ai.azure.com):

1. Navigate to your project
2. Go to **Settings** → **Project properties**
3. Note your **Endpoint URL** (should look like: `https://your-project.services.ai.azure.com/models`)
4. Go to **Settings** → **API keys** and copy your API key
5. Note the **Model name** you want to use (e.g., `claude-3-5-sonnet`, `gpt-4o`, etc.)

### 3. Configure Environment Variables

Create or edit your `.env` file in the project root:

```env
# Set the LLM provider to azure_ai
LLM_PROVIDER=azure_ai

# Azure AI Foundry Configuration
AZURE_AI_ENDPOINT=https://your-project.services.ai.azure.com/models
AZURE_AI_API_KEY=your-azure-ai-api-key-here
AZURE_AI_MODEL=claude-3-5-sonnet
```

**Important Notes:**
- The endpoint should end with `/models`
- The model name should match exactly what's shown in Azure AI Foundry (e.g., `claude-3-5-sonnet`, not `Claude 3.5 Sonnet`)
- Keep your API key secure and never commit it to version control

### 4. Run the Debugger

Now run the tool as normal:

```bash
dump-debugger analyze path\to\your\dump.dmp
```

The tool will now use Claude Sonnet hosted in your Azure AI Foundry instance!

## Supported Models

Azure AI Foundry supports various models depending on your deployment:

- **Claude Models**: `claude-3-5-sonnet`, `claude-3-opus`, `claude-3-sonnet`, `claude-3-haiku`
- **OpenAI Models**: `gpt-4o`, `gpt-4-turbo`, `gpt-4`, `gpt-35-turbo`
- **Meta Models**: `llama-3-70b`, `llama-3-8b`
- **Mistral Models**: `mistral-large`, `mistral-small`

Simply set `AZURE_AI_MODEL` to the model you want to use.

## Troubleshooting

### "Azure AI Inference SDK not installed"
Run: `pip install azure-ai-inference` or `uv pip install azure-ai-inference`

### "Azure AI Foundry not configured"
Check that both `AZURE_AI_ENDPOINT` and `AZURE_AI_API_KEY` are set in your `.env` file

### Authentication errors
- Verify your API key is correct
- Ensure your Azure AI project has the model deployed
- Check that your endpoint URL is correct (should end with `/models`)

### Model not found errors
- Verify the model name matches exactly what's in Azure AI Foundry
- Ensure the model is deployed in your project
- Check the model name doesn't have extra spaces or capitalization differences

## Cost Considerations

When using Azure AI Foundry:
- You're charged based on token usage (input + output tokens)
- Claude models typically cost more than smaller models like GPT-3.5
- Monitor your usage in the Azure portal
- Consider setting budget alerts in Azure

## Switching Between Providers

You can easily switch between different LLM providers by changing `LLM_PROVIDER`:

```env
# Use Azure AI Foundry (Claude, GPT-4o, etc.)
LLM_PROVIDER=azure_ai

# Use direct Anthropic API
LLM_PROVIDER=anthropic

# Use OpenAI directly
LLM_PROVIDER=openai

# Use Azure OpenAI Service
LLM_PROVIDER=azure
```

Each provider requires its own set of credentials to be configured.
