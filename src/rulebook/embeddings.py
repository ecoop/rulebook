"""Pluggable embedding backend.

An EMBEDDING turns text into a fixed-length vector such that semantically
similar texts land near each other in that vector space. In our RAG
pipeline the same model must embed BOTH:

    1. Every chunk we store (at index-build time), and
    2. The user's question (at query time).

Otherwise similarity search compares apples to oranges — the query vector
lives in a different geometry from the stored vectors and nearest
neighbors are essentially random.

For instructional value we support three providers behind one small
interface. The choice is driven by settings.embedding_provider so you can
swap without touching retrieval or storage code.

    local          A model2vec static model on your CPU. No API key, no
                   network at query time, no cost, and no PyTorch/ONNX — so
                   it installs where the heavy stacks don't (Intel macOS,
                   new Python). THE DEFAULT, so a fresh clone can build an
                   index and retrieve with zero keys — only *generation*
                   needs an Anthropic key. The trade is a weaker (static)
                   model than the hosted options; for clean, structured text
                   like rulebooks it's usually plenty, and the eval harness
                   is how you tell when it stops being enough.

    Voyage AI      Anthropic's recommended embedding partner. Works well
                   with Claude. Emits vectors normalized to unit length,
                   which makes L2 and cosine ranking equivalent. The
                   "upgrade" path: flip the provider, rebuild, and let
                   hit@k/MRR show you whether it bought you anything.

    OpenAI         Cheaper still, similar quality on most tasks.

INPUT TYPE

    Both providers distinguish "document" text (what you're storing) from
    "query" text (what a user typed) and produce slightly different
    vectors for each. Passing the right input_type at both index-build
    and query time measurably improves retrieval quality — free win.

    OpenAI's API doesn't expose this distinction, so we just ignore the
    flag there.
"""

from typing import Literal, Protocol

from llm_cost_governor.budget import RequirePricedModelHook
from llm_cost_governor.counters import WindowedCapHook
from llm_cost_governor.events import EventLogHook
from llm_cost_governor.wrapper import record_usage

from . import app_state
from .config import settings

InputType = Literal["document", "query"]


def _record_embed_usage(
    provider: str, model: str, tokens: int, input_type: InputType,
) -> None:
    """Fan the embedding call through the guardrail hook chain.

    Embeddings don't fit ``guarded_call`` (which wraps a provider
    adapter written for chat-completion shapes), so we call
    ``record_usage`` post-hoc with the token count reported by the
    provider. The hook chain then fires: WindowedCapHook accumulates
    spend against the caps, EventLogHook emits the JSON event line.
    """
    if app_state.cost_counter is None:
        # No app_state.initialize() has run — most likely a unit-test
        # context using the embedder directly. Skip silently rather
        # than blowing up.
        return
    record_usage(
        provider=provider,
        model=model,
        input_tokens=tokens,
        output_tokens=0,
        hooks=[
            # Fail closed on an unpriced model before the caps accumulate (#lcg).
            RequirePricedModelHook(),
            WindowedCapHook(app_state.cost_counter, identity_provider=app_state.current_guest_token),
            app_state.provider_totals_hook,
            EventLogHook(enabled=settings.guardrails_enabled),
        ],
        tags={"stage": "embed", "input_type": input_type},
    )


class Embedder(Protocol):
    """The one method retrieve.py and build_index.py depend on."""

    def embed(self, texts: list[str], *, input_type: InputType) -> list[list[float]]: ...


class LocalEmbedder:
    """Embeddings from a local model2vec model — no API, no key, no cost, no torch.

    This is the default, so a fresh clone can build an index and retrieve with
    zero API keys (only *generation* needs an Anthropic key). model2vec embeddings
    are STATIC: every token has a precomputed vector and a text's embedding is a
    pooled average of its tokens — no neural forward pass at query time. That makes
    it tiny and fast on CPU, and — crucially — free of PyTorch/ONNX, so it installs
    on platforms the heavier local stacks have abandoned (Intel macOS, brand-new
    Python versions). The first call downloads the model (tens of MB) and caches it.

    The trade for that lightness is quality: a static model can't tell apart the
    senses of a word from context the way a hosted contextual model (Voyage) can.
    For clean, structured text like rulebooks it's usually enough — the eval harness
    (hit@k/MRR) is how you tell when it stops being, and when a corpus is worth
    switching to EMBEDDING_PROVIDER=voyage and rebuilding.

    Static models are SYMMETRIC: there's no separate query vs document geometry, so
    ``input_type`` is accepted (to satisfy the Embedder interface) but unused. No
    usage is recorded — local embeddings are free and aren't in lcg's priced catalog.
    """

    def __init__(self, model: str):
        try:
            from model2vec import StaticModel
        except ImportError as e:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=local needs the 'model2vec' dependency. Install "
                "it with `uv sync`, or switch to a hosted provider: set "
                "EMBEDDING_PROVIDER=voyage (with VOYAGE_API_KEY) in your .env."
            ) from e
        self._model = StaticModel.from_pretrained(model)

    def embed(self, texts, *, input_type):
        import numpy as np

        vectors = np.asarray(self._model.encode(list(texts)), dtype=np.float32)
        # Unit-normalize so the stored vectors match Voyage's unit-length output and
        # the store's cosine-as-dot-product holds. The store normalizes too, so this
        # is belt-and-suspenders, but it keeps the raw .npy honest across providers.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (vectors / norms).tolist()


class VoyageEmbedder:
    def __init__(self, model: str, api_key: str):
        import voyageai

        self._client = voyageai.Client(api_key=api_key)
        self._model = model

    def embed(self, texts, *, input_type):
        result = self._client.embed(texts, model=self._model, input_type=input_type)
        _record_embed_usage("voyage", self._model, int(result.total_tokens), input_type)
        return result.embeddings


class OpenAIEmbedder:
    def __init__(self, model: str, api_key: str):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model

    def embed(self, texts, *, input_type):
        # OpenAI doesn't distinguish input_type; the argument is ignored.
        resp = self._client.embeddings.create(model=self._model, input=texts)
        _record_embed_usage("openai", self._model, int(resp.usage.total_tokens), input_type)
        return [d.embedding for d in resp.data]


def get_embedder() -> Embedder:
    """Return the Embedder chosen by the EMBEDDING_PROVIDER env var."""
    if settings.embedding_provider == "local":
        return LocalEmbedder(settings.embedding_model)
    if settings.embedding_provider == "voyage":
        if not settings.voyage_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=voyage but VOYAGE_API_KEY is not set")
        return VoyageEmbedder(settings.embedding_model, settings.voyage_api_key)
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is not set")
        return OpenAIEmbedder(settings.embedding_model, settings.openai_api_key)
    raise RuntimeError(f"Unknown embedding provider: {settings.embedding_provider!r}")


def probe_dimension(embedder: Embedder) -> int:
    """Ask the embedder to embed one short string and report the vector length.

    We let the model report its own dimension rather than hard-coding it, so
    swapping models (even across providers with different output sizes) just
    works — the manifest records whatever the active model emits.
    """
    [v] = embedder.embed(["dimension probe"], input_type="document")
    return len(v)
