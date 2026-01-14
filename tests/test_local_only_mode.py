"""Tests for local-only mode and LLM provider configuration.

Simplified configuration model:
- LLM_PROVIDER: Which LLM to use (ollama, openai, azure, anthropic)
- LOCAL_ONLY_MODE / --local-only: Security switch that forces Ollama and disables embeddings
- USE_TIERED_LLM: When true, simple tasks use Ollama, complex tasks use LLM_PROVIDER
"""

import pytest
from unittest.mock import patch, MagicMock


class TestLocalOnlyMode:
    """Tests for local-only mode behavior."""
    
    def test_local_only_mode_forces_ollama_provider(self, monkeypatch):
        """When local_only_mode is True, get_llm should use Ollama regardless of LLM_PROVIDER."""
        # Clear any cached LLM instances
        from dump_debugger import llm
        llm._llm_cache.clear()
        
        # Set up local-only mode with LLM_PROVIDER set to openai
        monkeypatch.setenv("LOCAL_ONLY_MODE", "true")
        monkeypatch.setenv("LLM_PROVIDER", "openai")  # Would normally use OpenAI
        monkeypatch.setenv("LOCAL_LLM_MODEL", "test-model")
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434")
        
        # Reload settings to pick up env changes
        from dump_debugger.config import Settings
        test_settings = Settings()
        
        with patch.object(llm, 'settings', test_settings):
            with patch.object(llm, 'ChatOllama') as mock_ollama:
                mock_ollama.return_value = MagicMock()
                
                result = llm.get_llm(temperature=0.0)
                
                # Should have called Ollama, not OpenAI
                mock_ollama.assert_called_once()
                call_kwargs = mock_ollama.call_args[1]
                assert call_kwargs['model'] == 'test-model'
    
    def test_local_only_mode_disables_embeddings(self, monkeypatch):
        """When local_only_mode is True, get_embeddings should raise error."""
        from dump_debugger import llm
        
        monkeypatch.setenv("LOCAL_ONLY_MODE", "true")
        
        from dump_debugger.config import Settings
        test_settings = Settings()
        
        with patch.object(llm, 'settings', test_settings):
            with pytest.raises(ValueError) as exc_info:
                llm.get_embeddings()
            
            assert "LOCAL-ONLY MODE" in str(exc_info.value)
            assert "Embeddings disabled" in str(exc_info.value)


class TestLLMProviderSelection:
    """Tests for LLM_PROVIDER-based selection."""
    
    def test_llm_provider_ollama_uses_ollama(self, monkeypatch):
        """When LLM_PROVIDER=ollama, should use Ollama for reasoning."""
        from dump_debugger import llm
        llm._llm_cache.clear()
        
        monkeypatch.setenv("LOCAL_ONLY_MODE", "false")
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("LOCAL_LLM_MODEL", "test-model")
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434")
        
        from dump_debugger.config import Settings
        test_settings = Settings()
        
        with patch.object(llm, 'settings', test_settings):
            with patch.object(llm, 'ChatOllama') as mock_ollama:
                mock_ollama.return_value = MagicMock()
                
                result = llm.get_llm(temperature=0.0)
                
                # Should have called Ollama
                mock_ollama.assert_called_once()
    
    def test_llm_provider_ollama_allows_cloud_embeddings(self, monkeypatch):
        """When LLM_PROVIDER=ollama but not local-only, cloud embeddings allowed."""
        from dump_debugger import llm
        
        monkeypatch.setenv("LOCAL_ONLY_MODE", "false")
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("EMBEDDINGS_PROVIDER", "openai")
        
        from dump_debugger.config import Settings
        test_settings = Settings()
        
        with patch.object(llm, 'settings', test_settings):
            with patch.object(llm, 'OpenAIEmbeddings') as mock_embeddings:
                mock_embeddings.return_value = MagicMock()
                
                result = llm.get_embeddings()
                
                # Should have created OpenAI embeddings (cloud)
                mock_embeddings.assert_called_once()
    
    def test_llm_provider_azure_uses_azure(self, monkeypatch):
        """When LLM_PROVIDER=azure, should use Azure for reasoning."""
        from dump_debugger import llm
        llm._llm_cache.clear()
        
        monkeypatch.setenv("LOCAL_ONLY_MODE", "false")
        monkeypatch.setenv("LLM_PROVIDER", "azure")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com")
        monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4")
        
        from dump_debugger.config import Settings
        test_settings = Settings()
        
        with patch.object(llm, 'settings', test_settings):
            with patch.object(llm, 'AzureChatOpenAI') as mock_azure:
                with patch.object(llm, '_wrap_with_redaction', return_value=MagicMock()):
                    mock_azure.return_value = MagicMock()
                    
                    result = llm.get_llm(temperature=0.0)
                    
                    # Should have called Azure
                    mock_azure.assert_called_once()


class TestTieredRouting:
    """Tests for tiered LLM routing."""
    
    def test_tiered_routing_simple_uses_ollama(self, monkeypatch):
        """Simple tasks should use Ollama when tiered routing is enabled."""
        from dump_debugger import llm
        from dump_debugger.llm_router import LLMRouter, TaskComplexity
        llm._llm_cache.clear()
        
        monkeypatch.setenv("USE_TIERED_LLM", "true")
        monkeypatch.setenv("LLM_PROVIDER", "azure")  # Complex tasks use Azure
        monkeypatch.setenv("LOCAL_LLM_MODEL", "test-model")
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434")
        
        from dump_debugger.config import Settings
        test_settings = Settings()
        
        with patch.object(llm, 'settings', test_settings):
            with patch('dump_debugger.llm_router.settings', test_settings):
                with patch.object(llm, 'ChatOllama') as mock_ollama:
                    mock_ollama.return_value = MagicMock()
                    
                    router = LLMRouter()
                    result = router.get_llm_for_task(TaskComplexity.SIMPLE)
                    
                    # Simple task should use Ollama
                    mock_ollama.assert_called()
    
    def test_tiered_routing_complex_uses_llm_provider(self, monkeypatch):
        """Complex tasks should use LLM_PROVIDER when tiered routing is enabled."""
        from dump_debugger import llm
        from dump_debugger.llm_router import LLMRouter, TaskComplexity
        llm._llm_cache.clear()
        
        monkeypatch.setenv("USE_TIERED_LLM", "true")
        monkeypatch.setenv("LLM_PROVIDER", "azure")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com")
        monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4")
        monkeypatch.setenv("LOCAL_LLM_MODEL", "test-model")
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434")
        
        from dump_debugger.config import Settings
        test_settings = Settings()
        
        with patch.object(llm, 'settings', test_settings):
            with patch('dump_debugger.llm_router.settings', test_settings):
                with patch.object(llm, 'ChatOllama') as mock_ollama:
                    with patch.object(llm, 'AzureChatOpenAI') as mock_azure:
                        with patch.object(llm, '_wrap_with_redaction', return_value=MagicMock()):
                            mock_ollama.return_value = MagicMock()
                            mock_azure.return_value = MagicMock()
                            
                            router = LLMRouter()
                            result = router.get_llm_for_task(TaskComplexity.COMPLEX)
                            
                            # Complex task should use Azure (LLM_PROVIDER)
                            mock_azure.assert_called()
    
    def test_router_does_not_mutate_llm_provider(self, monkeypatch):
        """LLM router should not change settings.llm_provider."""
        from dump_debugger import llm
        from dump_debugger.llm_router import LLMRouter, TaskComplexity
        llm._llm_cache.clear()
        
        monkeypatch.setenv("USE_TIERED_LLM", "true")
        monkeypatch.setenv("LLM_PROVIDER", "azure")
        monkeypatch.setenv("LOCAL_LLM_MODEL", "test-model")
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434")
        
        from dump_debugger.config import Settings
        test_settings = Settings()
        original_provider = test_settings.llm_provider
        
        with patch.object(llm, 'settings', test_settings):
            with patch('dump_debugger.llm_router.settings', test_settings):
                with patch.object(llm, 'ChatOllama') as mock_ollama:
                    mock_ollama.return_value = MagicMock()
                    
                    router = LLMRouter()
                    
                    # Access local_llm - should not change global provider
                    _ = router.local_llm
                    
                    # Provider should be unchanged
                    assert test_settings.llm_provider == original_provider


class TestGetLLMForProvider:
    """Tests for explicit provider selection."""
    
    def test_get_llm_for_provider_ollama(self, monkeypatch):
        """get_llm_for_provider('ollama') should create Ollama LLM."""
        from dump_debugger import llm
        llm._llm_cache.clear()
        
        monkeypatch.setenv("LOCAL_LLM_MODEL", "test-model")
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434")
        
        from dump_debugger.config import Settings
        test_settings = Settings()
        
        with patch.object(llm, 'settings', test_settings):
            with patch.object(llm, 'ChatOllama') as mock_ollama:
                mock_ollama.return_value = MagicMock()
                
                result = llm.get_llm_for_provider("ollama", temperature=0.0)
                
                mock_ollama.assert_called_once()
                call_kwargs = mock_ollama.call_args[1]
                assert call_kwargs['model'] == 'test-model'
    
    def test_get_llm_for_provider_openai(self, monkeypatch):
        """get_llm_for_provider('openai') should create OpenAI LLM."""
        from dump_debugger import llm
        llm._llm_cache.clear()
        
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4")
        
        from dump_debugger.config import Settings
        test_settings = Settings()
        
        with patch.object(llm, 'settings', test_settings):
            with patch.object(llm, 'ChatOpenAI') as mock_openai:
                with patch.object(llm, '_wrap_with_redaction', return_value=MagicMock()) as mock_wrap:
                    mock_openai.return_value = MagicMock()
                    
                    result = llm.get_llm_for_provider("openai", temperature=0.0)
                    
                    mock_openai.assert_called_once()
                    mock_wrap.assert_called_once()
