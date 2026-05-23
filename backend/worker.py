from rq import SimpleWorker

from task_queue import DEFAULT_QUEUE_NAME, redis_conn


if __name__ == "__main__":
    worker = SimpleWorker([DEFAULT_QUEUE_NAME], connection=redis_conn)
    worker.work()
