"""
Audit Logger - 操作記錄工具
"""
from typing import Optional, Dict, Any
from fastapi import Request
import time


class AuditLogger:
    """操作記錄工具類"""

    def __init__(self, audit_log_repo):
        self.repo = audit_log_repo

    def get_client_ip(self, request: Request) -> str:
        """獲取客戶端 IP 地址"""
        # 優先從 X-Forwarded-For header 獲取（通過代理時）
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

        # 從 X-Real-IP header 獲取
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # 從 request.client 獲取
        if request.client:
            return request.client.host

        return "unknown"

    def sanitize_request_body(self, body: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """清理請求內容中的敏感資訊"""
        if not body:
            return None

        # 需要過濾的敏感欄位
        sensitive_fields = ["password", "token", "secret", "api_key", "access_token", "refresh_token"]

        sanitized = body.copy()
        for field in sensitive_fields:
            if field in sanitized:
                sanitized[field] = "***REDACTED***"

        return sanitized

    async def log_auth(
        self,
        request: Request,
        action: str,
        user_id: Optional[str],
        status_code: int,
        message: Optional[str] = None,
        duration_ms: Optional[int] = None
    ):
        """記錄認證相關操作

        Args:
            request: FastAPI Request 對象
            action: 操作動作 (login, logout, register, token_refresh)
            user_id: 用戶 ID
            status_code: HTTP 狀態碼
            message: 訊息
            duration_ms: 處理時間（毫秒）
        """
        await self.repo.log(
            user_id=user_id,
            log_type="auth",
            action=action,
            ip_address=self.get_client_ip(request),
            path=request.url.path,
            method=request.method,
            status_code=status_code,
            response_message=message,
            user_agent=request.headers.get("User-Agent"),
            duration_ms=duration_ms
        )

    async def log_task_operation(
        self,
        request: Request,
        action: str,
        user_id: str,
        task_id: Optional[str],
        status_code: int,
        message: Optional[str] = None,
        request_body: Optional[Dict[str, Any]] = None
    ):
        """記錄任務相關操作

        Args:
            request: FastAPI Request 對象
            action: 操作動作 (create, update, delete, cancel, view)
            user_id: 用戶 ID
            task_id: 任務 ID
            status_code: HTTP 狀態碼
            message: 訊息
            request_body: 請求內容
        """
        await self.repo.log(
            user_id=user_id,
            log_type="task",
            action=action,
            ip_address=self.get_client_ip(request),
            path=request.url.path,
            method=request.method,
            status_code=status_code,
            resource_id=task_id,
            response_message=message,
            request_body=self.sanitize_request_body(request_body),
            user_agent=request.headers.get("User-Agent")
        )

    async def log_transcription_operation(
        self,
        request: Request,
        action: str,
        user_id: str,
        task_id: Optional[str],
        status_code: int,
        message: Optional[str] = None
    ):
        """記錄轉錄相關操作

        Args:
            request: FastAPI Request 對象
            action: 操作動作 (create, download, update_content, update_metadata)
            user_id: 用戶 ID
            task_id: 任務 ID
            status_code: HTTP 狀態碼
            message: 訊息
        """
        await self.repo.log(
            user_id=user_id,
            log_type="transcription",
            action=action,
            ip_address=self.get_client_ip(request),
            path=request.url.path,
            method=request.method,
            status_code=status_code,
            resource_id=task_id,
            response_message=message,
            user_agent=request.headers.get("User-Agent")
        )

    async def log_file_operation(
        self,
        request: Request,
        action: str,
        user_id: str,
        resource_id: Optional[str],
        status_code: int,
        message: Optional[str] = None
    ):
        """記錄檔案相關操作

        Args:
            request: FastAPI Request 對象
            action: 操作動作 (download, upload, delete)
            user_id: 用戶 ID
            resource_id: 資源 ID
            status_code: HTTP 狀態碼
            message: 訊息
        """
        await self.repo.log(
            user_id=user_id,
            log_type="file",
            action=action,
            ip_address=self.get_client_ip(request),
            path=request.url.path,
            method=request.method,
            status_code=status_code,
            resource_id=resource_id,
            response_message=message,
            user_agent=request.headers.get("User-Agent")
        )

    async def log_tag_operation(
        self,
        request: Request,
        action: str,
        user_id: str,
        tag_id: Optional[str],
        status_code: int,
        message: Optional[str] = None,
        request_body: Optional[Dict[str, Any]] = None
    ):
        """記錄標籤相關操作

        Args:
            request: FastAPI Request 對象
            action: 操作動作 (create, update, delete, reorder)
            user_id: 用戶 ID
            tag_id: 標籤 ID
            status_code: HTTP 狀態碼
            message: 訊息
            request_body: 請求內容
        """
        await self.repo.log(
            user_id=user_id,
            log_type="tag",
            action=action,
            ip_address=self.get_client_ip(request),
            path=request.url.path,
            method=request.method,
            status_code=status_code,
            resource_id=tag_id,
            response_message=message,
            request_body=self.sanitize_request_body(request_body),
            user_agent=request.headers.get("User-Agent")
        )

    async def log_admin_operation(
        self,
        request: Request,
        action: str,
        user_id: str,
        status_code: int,
        message: Optional[str] = None
    ):
        """記錄管理員操作

        Args:
            request: FastAPI Request 對象
            action: 操作動作 (view_statistics, manage_users, etc.)
            user_id: 用戶 ID
            status_code: HTTP 狀態碼
            message: 訊息
        """
        await self.repo.log(
            user_id=user_id,
            log_type="admin",
            action=action,
            ip_address=self.get_client_ip(request),
            path=request.url.path,
            method=request.method,
            status_code=status_code,
            response_message=message,
            user_agent=request.headers.get("User-Agent")
        )

    async def log_background_task(
        self,
        log_type: str,
        action: str,
        user_id: str,
        task_id: Optional[str] = None,
        status_code: int = 200,
        message: Optional[str] = None,
        error: Optional[str] = None
    ):
        """記錄後台任務操作（不需要 Request 對象）

        用於在後台線程/任務中記錄操作，如轉錄完成/失敗

        Args:
            log_type: 日誌類型 (task, transcription, etc.)
            action: 操作動作 (completed, failed, etc.)
            user_id: 用戶 ID
            task_id: 任務 ID
            status_code: HTTP 狀態碼（200=成功，500=失敗）
            message: 訊息
            error: 錯誤訊息（失敗時）
        """
        final_message = message
        if error:
            final_message = f"{message}: {error}" if message else error

        await self.repo.log(
            user_id=user_id,
            log_type=log_type,
            action=action,
            ip_address="system",  # 後台任務使用 "system"
            path=f"/background/{log_type}/{action}",
            method="BACKGROUND",
            status_code=status_code,
            resource_id=task_id,
            response_message=final_message,
            user_agent="BackgroundWorker"
        )


# 全域 AuditLogger 實例
_audit_logger: Optional[AuditLogger] = None


def init_audit_logger(audit_log_repo):
    """初始化全域 AuditLogger"""
    global _audit_logger
    _audit_logger = AuditLogger(audit_log_repo)
    return _audit_logger


def get_audit_logger() -> AuditLogger:
    """獲取 AuditLogger 實例"""
    if _audit_logger is None:
        raise RuntimeError("AuditLogger 尚未初始化")
    return _audit_logger


async def log_admin_action(
    admin_id: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
):
    """記錄管理員操作（便捷函數，不需要 Request 對象）

    Args:
        admin_id: 管理員用戶 ID
        action: 操作動作 (enable_user, disable_user, change_role, update_quota, etc.)
        resource_type: 資源類型 (user, task, etc.)
        resource_id: 資源 ID
        details: 操作詳情
    """
    if _audit_logger is None:
        print(f"⚠️  AuditLogger 尚未初始化，跳過記錄: {action}")
        return

    message = f"{action} on {resource_type}"
    if details:
        # 只保留關鍵資訊
        if "email" in details:
            message += f" ({details['email']})"

    await _audit_logger.repo.log(
        user_id=admin_id,
        log_type="admin",
        action=action,
        ip_address="admin-panel",
        path=f"/api/admin/{resource_type}s/{resource_id or 'batch'}",
        method="ADMIN",
        status_code=200,
        resource_id=resource_id,
        response_message=message,
        request_body=details,
        user_agent="AdminPanel"
    )
