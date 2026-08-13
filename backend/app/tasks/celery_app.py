from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ai_social_media", broker=settings.REDIS_URL, backend=settings.REDIS_URL
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_track_started=True,
    worker_send_task_events=True,
    task_send_sent_event=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
    task_default_queue="default",
    task_routes={
        "synapse.publish_task": {"queue": "publish"},
        "synapse.validate_cookie": {"queue": "publish"},
        "synapse.sync_post_metrics": {"queue": "publish"},
        "synapse.enqueue_due_metric_sync": {"queue": "default"},
        "mediacrawler.crawl": {"queue": "crawl"},
        "synapse.recover_stale_tasks": {"queue": "default"},
    },
    beat_schedule={
        "recover-stale-browser-tasks": {
            "task": "synapse.recover_stale_tasks",
            "schedule": 300.0,
        },
        "sync-due-social-metrics": {
            "task": "synapse.enqueue_due_metric_sync",
            "schedule": 21600.0,
        },
    },
    imports=[
        "app.tasks.content_tasks",
        "app.tasks.lead_tasks",
        # Synapse 内嵌发布引擎 worker
        "app.integrations.synapse_engine.workers.tasks",
        # MediaCrawler 内嵌采集引擎 worker
        "app.integrations.mediacrawler_engine.workers.tasks",
    ],
)
