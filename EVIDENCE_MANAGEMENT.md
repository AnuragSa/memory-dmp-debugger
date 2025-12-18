# Evidence Management System

## Overview

The Evidence Management System automatically handles large debugger outputs to ensure complete and accurate analysis without hitting token limits or losing critical information.

## Key Features

### 1. Automatic External Storage

When a debugger command produces output larger than the threshold (default: 10KB):
- Output is stored in a file in the session's evidence directory
- Metadata is tracked in SQLite database
- Reference ID is used instead of full content in state

### 2. Chunked LLM Analysis

Large outputs are intelligently chunked and analyzed:
- **Smart Chunking**: Splits at line boundaries to preserve context
- **Chunk Analysis**: Each chunk analyzed separately by LLM
- **Finding Extraction**: Extracts blocking operations, thread states, exceptions
- **Synthesis**: Combines chunk findings into overall conclusion

### 3. Session Isolation

Each dump analysis gets its own isolated session:
- **Unique Directory**: `session_TIMESTAMP_DUMPNAME/`
- **Isolated Database**: Separate SQLite DB per session
- **No Cross-Contamination**: Evidence never mixes between analyses
- **Persistence**: Session data saved for future reference

### 4. Semantic Search (Optional)

When enabled with OpenAI API:
- **Embeddings**: OpenAI text-embedding-3-small model
- **Vector Search**: Cosine similarity for relevance ranking
- **Accurate Retrieval**: Finds most relevant evidence for questions
- **Fallback**: LLM reranking if embeddings unavailable

## Architecture

### Components

```
dump_debugger/
├── evidence/
│   ├── storage.py      # EvidenceStore - SQLite + file storage
│   ├── analyzer.py     # EvidenceAnalyzer - Chunked LLM analysis
│   └── retrieval.py    # EvidenceRetriever - Semantic search
├── session/
│   └── __init__.py     # SessionManager - Session lifecycle
└── core/
    └── debugger.py     # DebuggerWrapper - Integration point
```

### Data Flow

```
1. Command Execution
   DebuggerWrapper.execute_command_with_analysis()
   ↓
   
2. Check Size
   If output > threshold (10KB):
   ↓
   
3. Analyze in Chunks
   EvidenceAnalyzer.analyze_evidence()
   - Split into 8KB chunks
   - Analyze each chunk with LLM
   - Synthesize overall findings
   ↓
   
4. Store Evidence
   EvidenceStore.store_evidence()
   - Save full output to file
   - Store metadata + findings in SQLite
   - Store chunk analyses
   - Return evidence ID
   ↓
   
5. Update State
   Evidence dict includes:
   - evidence_type: "external"
   - evidence_id: "ev_threads_20251217_..."
   - summary: "Overall findings..."
   - output: (summarized, not full)
```

### Interactive Mode Search

```
1. User Asks Question
   InteractiveChatAgent.answer_question()
   ↓
   
2. Build Context
   _build_context_for_question()
   ↓
   
3. Semantic Search (if enabled)
   EvidenceRetriever.find_relevant_evidence()
   - Generate embedding for question
   - Compute cosine similarity
   - Return top K most relevant
   ↓
   
4. Assess Sufficiency
   Check if existing evidence answers question
   ↓
   
5. Investigate (if needed)
   Execute new commands with evidence storage
```

## Session Directory Structure

Each analysis creates a session directory:

```
.sessions/
└── session_20251217_143052_crash_dmp/
    ├── metadata.json          # Session info (dump path, created, etc.)
    ├── session.log            # Full console output
    ├── evidence.db            # SQLite database
    │   ├── evidence table     # Metadata, summaries, embeddings
    │   └── chunks table       # Individual chunk analyses
    └── evidence/              # Large output files
        ├── ev_threads_001.txt
        ├── ev_clrstack_002.txt
        └── ev_syncblk_003.txt
```

## Database Schema

### Evidence Table

```sql
CREATE TABLE evidence (
    id TEXT PRIMARY KEY,              -- ev_command_timestamp
    session_id TEXT NOT NULL,         -- session_YYYYMMDD_HHMMSS_dumpname
    command TEXT NOT NULL,            -- Debugger command executed
    file_path TEXT,                   -- Path to output file
    size INTEGER,                     -- Output size in bytes
    summary TEXT,                     -- LLM-generated summary
    key_findings TEXT,                -- JSON array of findings
    embedding TEXT,                   -- JSON array (optional, for semantic search)
    metadata TEXT,                    -- JSON object
    timestamp TEXT NOT NULL           -- ISO 8601 timestamp
);
```

### Chunks Table

```sql
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id TEXT NOT NULL,        -- Foreign key to evidence.id
    chunk_num INTEGER NOT NULL,       -- Chunk sequence number
    chunk_text TEXT NOT NULL,         -- Chunk content
    analysis TEXT,                    -- JSON analysis results
    FOREIGN KEY (evidence_id) REFERENCES evidence(id)
);
```

## Configuration

### Environment Variables

**For Azure OpenAI (Recommended):**
```env
# Evidence Management
EVIDENCE_STORAGE_THRESHOLD=10000      # Store outputs > 10KB externally
EVIDENCE_CHUNK_SIZE=8000              # Chunk size for LLM analysis

# Semantic Search with Azure OpenAI
USE_EMBEDDINGS=true                   # Enable semantic search
EMBEDDINGS_PROVIDER=azure             # Use Azure OpenAI
AZURE_EMBEDDINGS_DEPLOYMENT=text-embedding-3-small  # Deployment name

# Optional: Separate endpoint/key for embeddings
# Defaults to AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY if not set
#AZURE_EMBEDDINGS_ENDPOINT=https://your-instance.openai.azure.com/
#AZURE_EMBEDDINGS_API_KEY=your-embeddings-key

# Session Management
SESSIONS_BASE_DIR=.sessions           # Base directory for all sessions
SESSION_CLEANUP_DAYS=7                # Auto-cleanup threshold
SESSION_KEEP_RECENT=5                 # Always keep N recent
```

**For Standard OpenAI:**
```env
# Semantic Search with OpenAI
USE_EMBEDDINGS=true                   # Enable semantic search
EMBEDDINGS_PROVIDER=openai            # Use standard OpenAI
EMBEDDINGS_MODEL=text-embedding-3-small
OPENAI_API_KEY=sk-...                 # OpenAI API key
```

**Without Embeddings (Keyword Search Only):**
```env
USE_EMBEDDINGS=false                  # Disable semantic search
```

## CLI Commands

### List Sessions

```bash
uv run dump-debugger sessions

# Limit results
uv run dump-debugger sessions --limit 10
```

Output:
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┓
┃ Session ID                    ┃ Dump File   ┃ Created         ┃ Size   ┃ Evidence ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━┩
│ session_20251217_143052_...   │ crash.dmp   │ 2025-12-17 14:30│ 2.45 MB│ 12       │
└───────────────────────────────┴─────────────┴─────────────────┴────────┴──────────┘
```

### Cleanup Old Sessions

```bash
uv run dump-debugger cleanup --days 7 --keep 5

# Delete sessions older than 7 days
# Always keep 5 most recent
```

## Implementation Details

### Chunk Analysis Strategy

The analyzer uses a multi-step process:

1. **Smart Chunking** (`_smart_chunk`)
   - Respects line boundaries
   - Ensures no mid-line cuts
   - Target: 8KB chunks

2. **Chunk Analysis** (`_analyze_chunk`)
   - Context from previous chunks
   - Extracts: blocking ops, thread states, exceptions
   - Returns structured JSON

3. **Synthesis** (`_synthesize_findings`)
   - Combines all chunk findings
   - Identifies overall patterns
   - Determines root cause

### Analysis Trail

Each evidence piece maintains a complete analysis trail:

```json
{
  "intent": "Investigating: Check thread states",
  "command": "!threads",
  "output_size": 524288,
  "chunk_analyses": [
    {
      "chunk_num": 1,
      "finding": {
        "summary": "10 threads waiting on sync objects",
        "blocking_operations": [
          {"thread_id": "0x1234", "operation": "WaitOne"}
        ]
      }
    }
  ],
  "overall_findings": {
    "summary": "Thread pool exhaustion detected",
    "root_cause": "All threads blocked on I/O"
  }
}
```

### Semantic Search Algorithm

When embeddings are enabled (Azure OpenAI or standard OpenAI):

1. **Generate Question Embedding**
   ```python
   # For Azure OpenAI
   question_vector = azure_client.embeddings.create(
       model=deployment_name,  # e.g., "text-embedding-3-small"
       input=question
   )
   
   # For standard OpenAI
   question_vector = openai_client.embeddings.create(
       model="text-embedding-3-small",
       input=question
   )
   ```

2. **Compute Similarities**
   ```python
   for evidence in all_evidence:
       similarity = cosine_similarity(
           question_vector,
           evidence.embedding
       )
   ```

3. **Rank and Return**
   - Sort by similarity (descending)
   - Return top K (default: 10)

**Provider Support:**
- ✅ Azure OpenAI (recommended for enterprise)
- ✅ Standard OpenAI
- ✅ Automatic fallback to keyword search if embeddings unavailable

## Best Practices

### For Developers

1. **Always Use execute_command_with_analysis()**
   ```python
   # Good - handles large outputs automatically
   result = debugger.execute_command_with_analysis(
       command="!threads",
       intent="Finding blocked threads"
   )
   
   # Avoid - may lose data on large outputs
   result = debugger.execute_command(command)
   ```

2. **Check Evidence Type**
   ```python
   if evidence['evidence_type'] == 'external':
       # Full output in database/file
       evidence_id = evidence['evidence_id']
       summary = evidence['summary']
   else:
       # Inline in evidence dict
       output = evidence['output']
   ```

3. **Pass Session Directory**
   ```python
   debugger = DebuggerWrapper(
       dump_path=dump_path,
       session_dir=session_dir  # Required for evidence storage
   )
   ```

### For Users

1. **Monitor Session Growth**
   ```bash
   uv run dump-debugger sessions
   ```

2. **Regular Cleanup**
   ```bash
   # Weekly cron job
   uv run dump-debugger cleanup --days 7 --keep 10
   ```

3. **Enable Embeddings for Better Search**
   ```env
   USE_EMBEDDINGS=true
   OPENAI_API_KEY=sk-...
   ```

## Performance Considerations

### Storage

- **10KB threshold**: Balances token usage vs. storage overhead
- **8KB chunks**: Fits comfortably in LLM context
- **SQLite**: Fast for session-sized datasets (50-100 evidence pieces)

### Analysis Time

- **Chunk analysis**: ~2-3 seconds per chunk
- **Embedding generation**: ~0.5 seconds per evidence piece
- **Total overhead**: 5-10 seconds for large outputs (acceptable tradeoff for accuracy)

### Cost

- **LLM analysis**: ~$0.01-0.02 per large output (500KB)
- **Embeddings**: ~$0.0001 per evidence piece
- **Total**: Minimal compared to main analysis cost

## Troubleshooting

### Evidence Not Stored

Check:
- Session directory created: `state['session_dir']`
- Threshold setting: `EVIDENCE_STORAGE_THRESHOLD`
- Output size: Must exceed threshold

### Semantic Search Not Working

Check:
- `USE_EMBEDDINGS=true` in .env
- `OPENAI_API_KEY` set
- OpenAI client initialized successfully

### Session Directory Not Found

- Created automatically on first analysis
- Check `SESSIONS_BASE_DIR` setting
- Verify write permissions

## Future Enhancements

Potential improvements:

1. **Incremental Embeddings**: Only generate for new evidence
2. **Compression**: Gzip large evidence files
3. **Cloud Storage**: S3/Azure Blob for enterprise deployments
4. **Multi-Dump Analysis**: Compare evidence across multiple dumps
5. **Evidence Visualization**: Interactive evidence explorer UI

## See Also

- [README.md](README.md) - Main project documentation
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [INTERACTIVE_MODE.md](README.md#interactive-mode) - Interactive chat mode guide
