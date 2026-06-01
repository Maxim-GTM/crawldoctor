from app.mq.consumers.core_consumer import CoreConsumer
from app.mq.consumers.enrichment_consumer import EnrichmentConsumer

core_consumer = CoreConsumer()
enrichment_consumer = EnrichmentConsumer()

__all__ = ["core_consumer", "enrichment_consumer"]
