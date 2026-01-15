"""Tests for embedding redaction security.

These tests verify that sensitive data is redacted before being sent to cloud
embedding APIs, addressing the security concern that redaction was only applied
to chat prompts but not to embeddings.
"""

import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path


class TestRedactionEmbeddingsWrapper:
    """Tests for RedactionEmbeddingsWrapper class."""
    
    def test_embed_documents_redacts_sensitive_data(self):
        """Embedding documents should redact connection strings, API keys, etc."""
        from dump_debugger.security.redactor import RedactionEmbeddingsWrapper, DataRedactor
        
        # Create a mock embeddings client
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        
        # Create wrapper
        wrapper = RedactionEmbeddingsWrapper(mock_embeddings, "test-provider")
        
        # Documents containing sensitive data (using patterns that match the redactor's patterns)
        documents = [
            "Connection string: Server=myserver;Database=mydb;User=admin;Password=secret123",
            "JWT token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        ]
        
        # Call embed_documents
        result = wrapper.embed_documents(documents)
        
        # Verify embeddings were called with redacted text
        call_args = mock_embeddings.embed_documents.call_args[0][0]
        
        # Connection string should be redacted
        assert "Password=secret123" not in call_args[0]
        assert "secret123" not in call_args[0]
        
        # JWT token should be redacted (starts with eyJ)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in call_args[1]
        
        # Result should be passed through
        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    
    def test_embed_query_redacts_sensitive_data(self):
        """Embedding a query should redact sensitive data."""
        from dump_debugger.security.redactor import RedactionEmbeddingsWrapper
        
        # Create a mock embeddings client
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]
        
        # Create wrapper
        wrapper = RedactionEmbeddingsWrapper(mock_embeddings, "test-provider")
        
        # Query containing sensitive data
        query = "What causes this error with connection: mongodb://admin:password123@localhost:27017/mydb"
        
        # Call embed_query
        result = wrapper.embed_query(query)
        
        # Verify embeddings were called with redacted text
        call_args = mock_embeddings.embed_query.call_args[0][0]
        
        # MongoDB connection string should be redacted
        assert "password123" not in call_args
        assert "mongodb://admin:password123@" not in call_args
        
        # Result should be passed through
        assert result == [0.1, 0.2, 0.3]
    
    def test_embed_documents_no_sensitive_data_passes_through(self):
        """Non-sensitive documents should pass through unchanged."""
        from dump_debugger.security.redactor import RedactionEmbeddingsWrapper
        
        # Create a mock embeddings client
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        
        # Create wrapper
        wrapper = RedactionEmbeddingsWrapper(mock_embeddings, "test-provider")
        
        # Document without sensitive data
        documents = [
            "This is a normal analysis about a memory leak in the System.Collections.Generic namespace"
        ]
        
        # Call embed_documents
        result = wrapper.embed_documents(documents)
        
        # Verify embeddings were called with original text (no redaction needed)
        call_args = mock_embeddings.embed_documents.call_args[0][0]
        assert call_args[0] == documents[0]
    
    def test_wrapper_delegates_other_attributes(self):
        """Wrapper should delegate unknown attributes to underlying embeddings."""
        from dump_debugger.security.redactor import RedactionEmbeddingsWrapper
        
        # Create a mock embeddings client with extra attributes
        mock_embeddings = MagicMock()
        mock_embeddings.model_name = "text-embedding-3-small"
        mock_embeddings.some_method.return_value = "test_result"
        
        # Create wrapper
        wrapper = RedactionEmbeddingsWrapper(mock_embeddings, "test-provider")
        
        # Access delegated attributes
        assert wrapper.model_name == "text-embedding-3-small"
        assert wrapper.some_method() == "test_result"


class TestGetEmbeddingsRedaction:
    """Tests for get_embeddings() wrapping cloud providers with redaction."""
    
    def test_openai_embeddings_are_wrapped(self, monkeypatch):
        """OpenAI embeddings should be wrapped with RedactionEmbeddingsWrapper."""
        from dump_debugger import llm
        from dump_debugger.security.redactor import RedactionEmbeddingsWrapper
        
        monkeypatch.setenv("LOCAL_ONLY_MODE", "false")
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("EMBEDDINGS_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        
        from dump_debugger.config import Settings
        test_settings = Settings()
        
        with patch.object(llm, 'settings', test_settings):
            with patch.object(llm, 'OpenAIEmbeddings') as mock_embeddings_class:
                mock_embeddings_instance = MagicMock()
                mock_embeddings_class.return_value = mock_embeddings_instance
                
                result = llm.get_embeddings()
                
                # Should be wrapped
                assert isinstance(result, RedactionEmbeddingsWrapper)
                assert result._provider_name == "openai"
    
    def test_ollama_embeddings_are_not_wrapped(self, monkeypatch):
        """Ollama embeddings (local) should NOT be wrapped with redaction."""
        from dump_debugger import llm
        from dump_debugger.security.redactor import RedactionEmbeddingsWrapper
        
        monkeypatch.setenv("LOCAL_ONLY_MODE", "false")
        monkeypatch.setenv("EMBEDDINGS_PROVIDER", "ollama")
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434")
        
        from dump_debugger.config import Settings
        test_settings = Settings()
        
        with patch.object(llm, 'settings', test_settings):
            with patch.object(llm, 'OllamaEmbeddings') as mock_embeddings_class:
                mock_embeddings_instance = MagicMock()
                mock_embeddings_class.return_value = mock_embeddings_instance
                
                result = llm.get_embeddings()
                
                # Should NOT be wrapped (local provider)
                assert not isinstance(result, RedactionEmbeddingsWrapper)
                assert result == mock_embeddings_instance
    
    def test_anthropic_fallback_embeddings_are_wrapped(self, monkeypatch):
        """When using Anthropic LLM, OpenAI embeddings fallback should be wrapped."""
        from dump_debugger import llm
        from dump_debugger.security.redactor import RedactionEmbeddingsWrapper
        
        monkeypatch.setenv("LOCAL_ONLY_MODE", "false")
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("EMBEDDINGS_PROVIDER", "anthropic")  # Falls back to OpenAI
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        
        from dump_debugger.config import Settings
        test_settings = Settings()
        
        with patch.object(llm, 'settings', test_settings):
            with patch.object(llm, 'OpenAIEmbeddings') as mock_embeddings_class:
                mock_embeddings_instance = MagicMock()
                mock_embeddings_class.return_value = mock_embeddings_instance
                
                result = llm.get_embeddings()
                
                # Should be wrapped (using OpenAI as fallback)
                assert isinstance(result, RedactionEmbeddingsWrapper)
                assert result._provider_name == "openai-for-anthropic"


class TestEmbeddingRedactionAuditLogging:
    """Tests for audit logging of embedding redactions."""
    
    def test_redaction_logs_use_embedding_context(self, tmp_path, monkeypatch):
        """Redaction audit logs should indicate embedding context."""
        from dump_debugger.security.redactor import RedactionEmbeddingsWrapper, DataRedactor
        
        # Create a mock embeddings client
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]
        
        # Create wrapper with session_id
        wrapper = RedactionEmbeddingsWrapper(
            mock_embeddings, 
            "test-provider", 
            session_id="test_session"
        )
        
        # Query containing sensitive data - use a JWT which we know gets redacted
        query = "Error with token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        
        # Create a mock redactor that tracks calls
        mock_redactor = MagicMock(spec=DataRedactor)
        mock_redactor.redact_text.return_value = (
            "Error with token: [REDACTED_JWT]", 
            1
        )
        
        with patch.object(wrapper, '_get_redactor', return_value=mock_redactor):
            wrapper.embed_query(query)
            
            # Verify redact_text was called with embedding context
            mock_redactor.redact_text.assert_called_once()
            call_args = mock_redactor.redact_text.call_args
            # Context is passed as keyword arg or positional arg
            context = call_args[1].get('context') if call_args[1] else call_args[0][1]
            assert "embedding_query" in context


class TestEmbeddingRedactionPatterns:
    """Tests for specific patterns being redacted in embeddings."""
    
    @pytest.mark.parametrize("sensitive_text,should_be_redacted", [
        # Connection strings
        ("Server=myserver;Database=test;Password=secret", True),
        ("mongodb://user:pass@host:27017/db", True),
        ("redis://user:password@localhost:6379", True),
        
        # API keys and tokens
        ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U", True),
        ("Authorization: Basic dXNlcjpwYXNzd29yZA==", True),
        
        # PII
        ("Contact email: john.doe@company.com", True),
        
        # Non-sensitive text should pass through
        ("Normal memory dump analysis text", False),
        ("Object at address 0x7fff12345678", False),
    ])
    def test_pattern_redaction_in_embeddings(self, sensitive_text, should_be_redacted):
        """Various sensitive patterns should be redacted before embedding."""
        from dump_debugger.security.redactor import RedactionEmbeddingsWrapper
        
        # Create a mock embeddings client
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]
        
        # Create wrapper
        wrapper = RedactionEmbeddingsWrapper(mock_embeddings, "test-provider")
        
        # Call embed_query
        wrapper.embed_query(sensitive_text)
        
        # Get what was actually sent to the embeddings API
        call_args = mock_embeddings.embed_query.call_args[0][0]
        
        if should_be_redacted:
            # The text should have been modified (redacted)
            assert call_args != sensitive_text, f"Expected '{sensitive_text}' to be redacted"
        else:
            # Non-sensitive text should pass through unchanged
            assert call_args == sensitive_text, f"Expected '{sensitive_text}' to pass through unchanged"
