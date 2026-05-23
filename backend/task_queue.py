from redis import Redis
from rq import Queue

from config import settings

DEFAULT_QUEUE_NAME = "pdreader"


redis_conn = Redis.from_url(settings.redis_url)
document_queue = Queue(DEFAULT_QUEUE_NAME, connection=redis_conn)
