from django.urls import path
from . import views

urlpatterns = [
    # 分類
    path('categories/',          views.category_list,   name='category-list'),
    path('categories/<int:pk>/', views.category_detail, name='category-detail'),
    # 全局變量
    path('variables/',                 views.variable_list,   name='variable-list'),
    path('variables/<int:pk>/',        views.variable_detail, name='variable-detail'),
    path('variables/token/generate/',  views.generate_token,  name='token-generate'),
    # MySQL
    path('db/configs/',                views.db_config_list,   name='db-config-list'),
    path('db/configs/<int:pk>/',       views.db_config_detail, name='db-config-detail'),
    path('db/configs/<int:pk>/test/',  views.db_config_test,   name='db-config-test'),
    path('db/execute/',                views.sql_execute,      name='sql-execute'),
    # Redis
    path('redis/configs/',               views.redis_config_list,   name='redis-config-list'),
    path('redis/configs/<int:pk>/',      views.redis_config_detail, name='redis-config-detail'),
    path('redis/configs/<int:pk>/test/', views.redis_config_test,   name='redis-config-test'),
    path('redis/operate/',               views.redis_operate,       name='redis-operate'),
    # Email
    path('email/configs/',               views.email_config_list,   name='email-config-list'),
    path('email/configs/<int:pk>/',      views.email_config_detail, name='email-config-detail'),
    path('email/configs/<int:pk>/test/', views.email_config_test,   name='email-config-test'),
    path('email/send-report/',           views.send_report_email_view, name='send-report-email'),
    # Scheduler
    path('scheduler/tasks/',                 views.scheduled_task_list,    name='task-list'),
    path('scheduler/tasks/<int:pk>/',        views.scheduled_task_detail,  name='task-detail'),
    path('scheduler/tasks/<int:pk>/run/',    views.scheduled_task_run_now, name='task-run'),
    path('scheduler/tasks/<int:pk>/toggle/', views.scheduled_task_toggle,  name='task-toggle'),
    # Locust
    path('locust/start/',                views.locust_start,   name='locust-start'),
    path('locust/status/<str:task_id>/', views.locust_status,  name='locust-status'),
    path('locust/stop/<str:task_id>/',   views.locust_stop,    name='locust-stop'),
    path('locust/collect/<str:task_id>/',views.locust_collect, name='locust-collect'),
    path('locust/preview/',              views.locust_preview, name='locust-preview'),
    # 接口
    path('apis/',              views.api_list,       name='api-list'),
    path('apis/<int:pk>/',     views.api_detail,     name='api-detail'),
    path('apis/<int:pk>/run/', views.api_run_single, name='api-run-single'),
    # 批量執行
    path('run/batch/',         views.api_run_batch,  name='run-batch'),
    # 報告
    path('reports/',           views.report_list,    name='report-list'),
    path('reports/<int:pk>/',  views.report_detail,  name='report-detail'),
]
