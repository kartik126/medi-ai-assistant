import httpx
import pytest
from backend.config import Settings
from backend.errors import AppError
from backend.model_client import OllamaModels


def test_embedding_query_instruction_and_normalization():
    bodies = []
    def handle(request):
        import json
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json={'embeddings': [[3, 4]]})
    model = OllamaModels(Settings(_env_file=None), httpx.MockTransport(handle))
    assert model.embed(['question'], query=True) == [[.6, .8]]
    assert bodies[0]['input'][0].startswith('Instruct:')
    assert bodies[0]['truncate'] is False
    assert bodies[0]['keep_alive'] == 0
    model.close()


@pytest.mark.parametrize('vectors', [[], [[0, 0]], [[1], [2]], [[float('nan')]], [[]]])
def test_invalid_embeddings(vectors):
    def handle(request):
        # Avoid JSON encoder rejection of NaN while still exercising our validator.
        return httpx.Response(200, content=__import__('json').dumps({'embeddings': vectors}).encode())
    model = OllamaModels(Settings(_env_file=None), httpx.MockTransport(handle))
    with pytest.raises(AppError):
        model.embed(['text'])
    model.close()


def test_timeout_is_typed():
    def handle(request):
        raise httpx.ReadTimeout('timeout')
    model = OllamaModels(Settings(_env_file=None), httpx.MockTransport(handle))
    with pytest.raises(AppError) as error:
        model.embed(['text'])
    assert error.value.status == 504
    model.close()


def test_remote_endpoint_rejected():
    with pytest.raises(ValueError, match='local'):
        OllamaModels(Settings(_env_file=None, ollama_base_url='https://example.com'))


def test_context_overflow_prevents_request():
    model = OllamaModels(Settings(_env_file=None, model_context_tokens=2048), httpx.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError('should not call'))))
    with pytest.raises(AppError) as error:
        model.generate([{'role': 'user', 'content': 'x'*8000}])
    assert error.value.code == 'context_limit'
    model.close()
