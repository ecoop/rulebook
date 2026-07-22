"""Pluggable embedding backend.

An EMBEDDING turns text into a fixed-length vector such that semantically
similar texts land near each other in that vector space. In our RAG
pipeline the same model must embed BOTH:

    1. Every chunk we store (at index-build time), and
    2. The user's question (at query time).

Otherwise similarity search compares apples to oranges — the query vector
lives in a different geometry from the stored vectors and nearest
neighbors are essentially random.

For instructional value we support two providers behind one small
interface. The choice is driven by settings.embedding_provider so you can
swap without touching retrieval or storage code.

    Voyage AI      Anthropic's recommended embedding partner. Works well
                   with Claude. Emits vectors normalized to unit length,
                   which makes L2 and cosine ranking equivalent.

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

from .config import settings

InputType = Literal["document", "query"]


class Embedder(Protocol):
    """The one method retrieve.py and build_index.py depend on."""

    def embed(self, texts: list[str], *, input_type: InputType) -> list[list[float]]: ...


class VoyageEmbedder:
    def __init__(self, model: str, api_key: str):
        import voyageai

        self._client = voyageai.Client(api_key=api_key)
        self._model = model

    def embed(self, texts, *, input_type):
        result = self._client.embed(texts, model=self._model, input_type=input_type)
        return result.embeddings


class OpenAIEmbedder:
    def __init__(self, model: str, api_key: str):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model

    def embed(self, texts, *, input_type):
        # OpenAI doesn't distinguish input_type; the argument is ignored.
        resp = self._client.embeddings.create(model=self._model, input=texts)
        return [d.embedding for d in resp.data]


def get_embedder() -> Embedder:
    """Return the Embedder chosen by the EMBEDDING_PROVIDER env var."""
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

    Used by build_index.py to size the LanceDB schema — we let the model
    tell us its dimension rather than hard-coding it, so swapping models
    (even ones with different output sizes) just works.
    """
    [v] = embedder.embed(["dimension probe"], input_type="document")
    return len(v)
