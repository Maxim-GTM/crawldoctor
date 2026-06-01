from app.mq.connection import MQConnection
from app.mq.publisher import EventPublisher

mq_connection = MQConnection()
event_publisher = EventPublisher(mq_connection)

__all__ = ["mq_connection", "event_publisher"]
