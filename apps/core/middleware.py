"""
認證中間件：保護所有 /api/ 路由
白名單：/api/auth/login/ 不需要登錄
"""
import json
from django.http import JsonResponse


# 不需要登錄的路徑（精確匹配）
AUTH_WHITELIST = {
    '/api/auth/login/',
}

# 不需要登錄的路徑前綴（前綴匹配）
# 遠端 Worker 機器無法登錄，需要直接訪問這兩個端點下載配置和腳本
AUTH_WHITELIST_PREFIX = (
    '/api/locust/remote-config/',   # 遠端 Worker 下載壓測配置 JSON
    '/api/locust/worker-script/',   # 遠端 Worker 下載引導腳本
)


class ApiAuthMiddleware:
    """
    攔截所有 /api/ 請求，未登錄返回 401。
    白名單路徑和白名單前綴免檢。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        # 只保護 /api/ 路由
        if path.startswith('/api/'):
            # 精確白名單
            if path in AUTH_WHITELIST:
                return self.get_response(request)
            # 前綴白名單（供遠端 Worker 無需登錄訪問）
            if path.startswith(AUTH_WHITELIST_PREFIX):
                return self.get_response(request)
            # 其他 /api/ 路由需要登錄
            if not request.user.is_authenticated:
                return JsonResponse(
                    {'code': 401, 'message': '請先登錄', 'data': None, 'timestamp': None},
                    status=401
                )

        return self.get_response(request)
