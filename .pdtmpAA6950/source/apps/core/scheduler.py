"""
定時任務調度器（APScheduler）
- Django AppConfig.ready() 中調用 start()
- 從數據庫加載所有 active 任務並注冊到調度器
- 支持 Cron 和 Interval 兩種觸發方式
- 執行完後可自動發郵件
"""
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

_scheduler = None   # 全局調度器單例


# ─────────────────────────────────────────────
#  任務執行函數（APScheduler 回調）
# ─────────────────────────────────────────────

def run_task(task_id: int):
    """
    定時任務的執行入口，由 APScheduler 調用。
    """
    import django
    # 確保 Django ORM 可用（多線程環境）
    try:
        from apps.core.models import ScheduledTask, TestReport
        from apps.core.executor import execute_batch
        from apps.core.email_utils import send_report_email

        task = ScheduledTask.objects.get(pk=task_id)
        if task.status != 'active':
            logger.info(f'[定時任務] {task.name} 已暫停/停止，跳過')
            return

        api_ids = task.get_api_ids()
        if not api_ids:
            logger.warning(f'[定時任務] {task.name} 接口列表為空，跳過')
            return

        report_name = task.report_name_tpl.replace('{task}', task.name).replace(
            '{time}', datetime.now().strftime('%Y%m%d_%H%M%S')
        )

        logger.info(f'[定時任務] 開始執行: {task.name}，接口數: {len(api_ids)}')
        report = execute_batch(api_ids, report_name)

        if not report:
            task.last_result = '執行失敗：未找到有效接口'
            task.last_run_at = datetime.now()
            task.save(update_fields=['last_result', 'last_run_at'])
            return

        summary = f'通過率 {report.pass_rate}% ({report.passed}/{report.total})'
        task.last_run_at    = datetime.now()
        task.last_report_id = report.id
        task.last_result    = summary
        task.save(update_fields=['last_run_at', 'last_report_id', 'last_result'])

        logger.info(f'[定時任務] {task.name} 執行完成：{summary}')

        # 發送郵件
        if task.send_email:
            to_list = task.get_email_to_list()
            if to_list:
                ok, msg = send_report_email(report, to_list)
                logger.info(f'[定時任務] 郵件: {msg}')
            else:
                logger.warning(f'[定時任務] {task.name} 郵件收件人為空，跳過發送')

    except ScheduledTask.DoesNotExist:
        logger.error(f'[定時任務] task_id={task_id} 不存在，已從調度器移除？')
    except Exception as e:
        logger.error(f'[定時任務] task_id={task_id} 執行異常: {e}', exc_info=True)


# ─────────────────────────────────────────────
#  調度器管理
# ─────────────────────────────────────────────

def get_scheduler():
    global _scheduler
    return _scheduler


def start():
    """啟動調度器，並從數據庫加載全部活躍任務（Django ready() 中調用）"""
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.executors.pool import ThreadPoolExecutor

        executors = {'default': ThreadPoolExecutor(max_workers=5)}
        job_defaults = {'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 60}

        _scheduler = BackgroundScheduler(executors=executors, job_defaults=job_defaults,
                                         timezone='Asia/Shanghai')
        _scheduler.start()
        logger.info('[Scheduler] APScheduler 已啟動')

        # 延遲加載 DB 任務（等 Django ORM 就緒）
        import threading
        threading.Timer(2.0, _load_all_tasks).start()

    except ImportError:
        logger.warning('[Scheduler] APScheduler 未安裝，定時任務不可用')
    except Exception as e:
        logger.error(f'[Scheduler] 啟動失敗: {e}')


def _load_all_tasks():
    """從數據庫加載所有活躍任務"""
    try:
        from apps.core.models import ScheduledTask
        tasks = ScheduledTask.objects.filter(status='active')
        for task in tasks:
            _add_job(task)
        logger.info(f'[Scheduler] 加載了 {tasks.count()} 個定時任務')
    except Exception as e:
        logger.error(f'[Scheduler] 加載任務失敗: {e}')


def _add_job(task):
    """向調度器注冊一個任務"""
    global _scheduler
    if not _scheduler or not _scheduler.running:
        return False
    try:
        job_id = f'task_{task.id}'

        # 先移除舊的（如果有）
        try:
            _scheduler.remove_job(job_id)
        except Exception:
            pass

        if task.trigger_type == 'cron':
            # 解析 Cron 表達式: "minute hour day month day_of_week"
            parts = task.cron_expr.strip().split()
            if len(parts) == 5:
                minute, hour, day, month, day_of_week = parts
            elif len(parts) == 6:
                second, minute, hour, day, month, day_of_week = parts
            else:
                minute, hour, day, month, day_of_week = '0', '9', '*', '*', '*'

            _scheduler.add_job(
                run_task, 'cron', id=job_id, name=task.name,
                args=[task.id],
                minute=minute, hour=hour, day=day,
                month=month, day_of_week=day_of_week,
                replace_existing=True,
            )
        else:  # interval
            _scheduler.add_job(
                run_task, 'interval', id=job_id, name=task.name,
                args=[task.id],
                seconds=max(int(task.interval_secs), 60),
                replace_existing=True,
            )
        logger.info(f'[Scheduler] 注冊任務: {task.name} (id={task.id})')
        return True
    except Exception as e:
        logger.error(f'[Scheduler] 注冊任務失敗 {task.name}: {e}')
        return False


def _remove_job(task_id: int):
    global _scheduler
    if not _scheduler:
        return
    try:
        _scheduler.remove_job(f'task_{task_id}')
    except Exception:
        pass


def register_task(task):
    """外部調用：添加/更新任務"""
    if task.status == 'active':
        return _add_job(task)
    else:
        _remove_job(task.id)
        return True


def remove_task(task_id: int):
    """外部調用：移除任務"""
    _remove_job(task_id)


def get_job_status(task_id: int) -> dict:
    """獲取調度器中的任務狀態"""
    global _scheduler
    if not _scheduler or not _scheduler.running:
        return {'running': False, 'next_run': None}
    try:
        job = _scheduler.get_job(f'task_{task_id}')
        if job:
            next_run = job.next_run_time
            return {
                'running': True,
                'next_run': next_run.strftime('%Y-%m-%d %H:%M:%S') if next_run else None,
                'job_id': job.id,
            }
    except Exception:
        pass
    return {'running': False, 'next_run': None}


def trigger_task_now(task_id: int):
    """立即觸發一次任務（不等待下次調度時間）"""
    global _scheduler
    if not _scheduler or not _scheduler.running:
        # 調度器未啟動，直接同步執行
        run_task(task_id)
        return True
    try:
        _scheduler.add_job(
            run_task, 'date', args=[task_id],
            id=f'immediate_{task_id}_{int(time.time())}',
            replace_existing=False,
        )
        return True
    except Exception as e:
        logger.error(f'[Scheduler] 立即觸發失敗: {e}')
        # 降級：直接同步執行
        run_task(task_id)
        return True


def stop():
    """停止調度器"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info('[Scheduler] 已停止')
