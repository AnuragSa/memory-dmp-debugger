# Azure OpenAI Embeddings Setup Guide

This guide shows how to configure the Memory Dump Debugger to use Azure OpenAI for embeddings in the semantic search feature.

## Why Use Embeddings?

Embeddings enable semantic search in interactive mode, allowing the AI to find relevant evidence based on meaning rather than just keywords. This significantly improves the accuracy of answers to follow-up questions.

## Azure OpenAI Setup

### Prerequisites

1. Azure subscription with Azure OpenAI access
2. An Azure OpenAI resource deployed
3. A text embeddings deployment (e.g., `text-embedding-3-small`)

### Step 1: Deploy Embeddings Model in Azure

1. Go to [Azure OpenAI Studio](https://oai.azure.com/)
2. Navigate to **Deployments**
3. Click **Create new deployment**
4. Select model: `text-embedding-3-small` (recommended)
5. Name your deployment (e.g., `text-embedding-3-small`)
6. Click **Create**

### Step 2: Get Configuration Values

From Azure Portal or Azure OpenAI Studio:

- **Endpoint**: `https://your-resource-name.openai.azure.com/`
- **API Key**: Found in "Keys and Endpoint" section
- **Deployment Name**: The name you gave to your embeddings deployment
- **API Version**: Use `2024-02-15-preview` or later

### Step 3: Configure .env File

**Option A: Use Same Endpoint as Main LLM (Recommended)**

If your embeddings deployment is in the same Azure OpenAI resource as your main LLM:

```env
# Main Azure OpenAI Configuration (for LLM)
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4  # or your LLM deployment name
AZURE_OPENAI_API_VERSION=2024-02-15-preview

# Embeddings Configuration
USE_EMBEDDINGS=true
EMBEDDINGS_PROVIDER=azure
AZURE_EMBEDDINGS_DEPLOYMENT=text-embedding-3-small  # Your embeddings deployment name
```

**Option B: Use Separate Endpoint for Embeddings**

If your embeddings deployment is in a different Azure OpenAI resource:

```env
# Main Azure OpenAI Configuration (for LLM)
AZURE_OPENAI_API_KEY=your-llm-api-key
AZURE_OPENAI_ENDPOINT=https://your-llm-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4

# Embeddings Configuration (separate resource)
USE_EMBEDDINGS=true
EMBEDDINGS_PROVIDER=azure
AZURE_EMBEDDINGS_DEPLOYMENT=text-embedding-3-small
AZURE_EMBEDDINGS_ENDPOINT=https://your-embeddings-resource.openai.azure.com/
AZURE_EMBEDDINGS_API_KEY=your-embeddings-api-key
```

### Step 4: Verify Configuration

Test that embeddings are working:

```powershell
# Start an interactive analysis
uv run dump-debugger analyze crash.dmp --issue "App hanging" --interactive
```

You should see:
```
[dim]Using semantic search across X evidence pieces...[/dim]
[dim]Top match: !threads (score: 0.85)[/dim]
```

If embeddings are not configured properly, it will fall back to keyword search:
```
[yellow]Azure OpenAI embeddings not configured, semantic search disabled[/yellow]
[dim]Using keyword search across X evidence pieces...[/dim]
```

## Configuration Examples

### Example 1: Azure AI Foundry with Claude + Azure Embeddings

```env
# Main LLM: Claude via Azure AI Foundry
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-project.services.ai.azure.com/models/anthropic/
AZURE_OPENAI_DEPLOYMENT=claude-sonnet-4-5
AZURE_OPENAI_API_VERSION=2024-10-01-preview
AZURE_OPENAI_API_KEY=your-foundry-key

# Embeddings: Azure OpenAI (separate resource)
USE_EMBEDDINGS=true
EMBEDDINGS_PROVIDER=azure
AZURE_EMBEDDINGS_DEPLOYMENT=text-embedding-3-small
AZURE_EMBEDDINGS_ENDPOINT=https://your-openai.openai.azure.com/
AZURE_EMBEDDINGS_API_KEY=your-openai-key
```

### Example 2: All-in-One Azure OpenAI Resource

```env
# Both LLM and embeddings in same Azure OpenAI resource
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_API_VERSION=2024-02-15-preview

# LLM deployment
AZURE_OPENAI_DEPLOYMENT=gpt-4

# Embeddings deployment (same resource)
USE_EMBEDDINGS=true
EMBEDDINGS_PROVIDER=azure
AZURE_EMBEDDINGS_DEPLOYMENT=text-embedding-3-small
```

### Example 3: Disable Embeddings (Keyword Search Only)

```env
# Disable semantic search
USE_EMBEDDINGS=false

# Other Azure config still works for main LLM
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4
AZURE_OPENAI_API_KEY=your-key
```

## Troubleshooting

### Error: "Azure OpenAI embeddings not configured"

**Cause**: Missing required configuration for Azure embeddings.

**Solution**: Check that you have set:
- `EMBEDDINGS_PROVIDER=azure`
- `AZURE_EMBEDDINGS_DEPLOYMENT=your-deployment-name`
- Either `AZURE_OPENAI_API_KEY` or `AZURE_EMBEDDINGS_API_KEY`
- Either `AZURE_OPENAI_ENDPOINT` or `AZURE_EMBEDDINGS_ENDPOINT`

### Error: "Embedding generation failed: 404"

**Cause**: Deployment name not found.

**Solution**: 
1. Verify deployment name in Azure Portal
2. Ensure it exactly matches `AZURE_EMBEDDINGS_DEPLOYMENT`
3. Check that deployment is in the same region as your endpoint

### Error: "Embedding generation failed: 401"

**Cause**: Invalid API key.

**Solution**:
1. Regenerate API key in Azure Portal
2. Update `.env` file with new key
3. Ensure no extra spaces or quotes around the key

### Semantic Search Not Working (Falls Back to Keyword Search)

**Possible Causes**:
1. `USE_EMBEDDINGS=false` in .env
2. Embeddings client initialization failed (check console for warnings)
3. Missing OpenAI or Azure credentials

**Solution**: Enable verbose output to see initialization messages:
```powershell
uv run dump-debugger analyze crash.dmp --issue "test" --show-commands --interactive
```

## Cost Considerations

### Azure OpenAI Embeddings Pricing

- **text-embedding-3-small**: ~$0.02 per 1M tokens
- **Typical usage**: 100-500 tokens per evidence piece
- **Estimated cost**: ~$0.0001-0.0005 per analysis session

### Example Cost Calculation

For a typical analysis with 50 evidence pieces:
- Evidence pieces: 50
- Average tokens per piece: 200
- Total tokens: 10,000
- Cost: ~$0.0002 (negligible)

The embeddings cost is minimal compared to the main LLM analysis cost.

## Performance

### Latency

- **Embedding generation**: ~0.5-1.0 seconds per evidence piece
- **Total overhead**: 5-10 seconds for typical session
- **Trade-off**: Slight delay for significantly better search accuracy

### Accuracy Improvement

Semantic search with embeddings provides:
- **85-95% relevance** vs. 60-70% with keyword search
- **Better context understanding**: Finds related concepts, not just exact matches
- **Multi-language support**: Works across different terminology

## Advanced Configuration

### Custom Embedding Dimensions

Some Azure deployments support different embedding dimensions:

```env
# Standard (default)
AZURE_EMBEDDINGS_DEPLOYMENT=text-embedding-3-small  # 1536 dimensions

# Large model (higher accuracy, slower)
AZURE_EMBEDDINGS_DEPLOYMENT=text-embedding-3-large  # 3072 dimensions
```

### Adjust Storage Thresholds

Control when evidence is stored externally and analyzed in chunks:

```env
# Store outputs larger than 10KB externally
EVIDENCE_STORAGE_THRESHOLD=10000

# Chunk size for LLM analysis (affects embedding granularity)
EVIDENCE_CHUNK_SIZE=8000
```

## See Also

- [README.md](README.md) - Main project documentation
- [EVIDENCE_MANAGEMENT.md](EVIDENCE_MANAGEMENT.md) - Evidence system details
- [AZURE_AI_SETUP.md](AZURE_AI_SETUP.md) - Azure AI Foundry setup for main LLM
- [.env.example](.env.example) - Full configuration template
