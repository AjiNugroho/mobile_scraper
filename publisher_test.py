from celery import Celery

app = Celery(
    "producer",
    broker="amqps://lbyrbqqj:YKZTvjyNFgkS2gvdnEaUN2g5BDC8bz89@vulture.rmq.cloudamqp.com/lbyrbqqj"
)

app.send_task(
    "scrape_hashtag",
    args=["#wardah"],
    queue="scrape_tiktok_incoming"
)