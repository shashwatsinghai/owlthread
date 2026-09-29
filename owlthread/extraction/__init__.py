"""Production extraction API. Legacy in-memory buffers are not runtime dependencies."""
from owlthread.extraction.pipeline import ExtractionPipeline
from owlthread.extraction.extractor import MemoryExtractor
__all__ = ["ExtractionPipeline", "MemoryExtractor"]
