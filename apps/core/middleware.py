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


class ApiAuthMiddleware:
    """
    攔截所有 /api/ 請求，未登錄返回 401。
    /api/auth/login/ 在白名單內，免檢。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        # 只保護 /api/ 路由
        if path.startswith('/api/'):
            # 白名單直接放行
            if path not in AUTH_WHITELIST:
                if not request.user.is_authenticated:
                    return JsonResponse(
                        {'code': 401, 'message': '請先登錄', 'data': None, 'timestamp': None},
                        status=401
                    )

        return self.get_response(request)
