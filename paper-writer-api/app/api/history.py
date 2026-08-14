"""论文生成记录接口。"""

from fastapi import APIRouter, HTTPException, Request

from app.services import history_service

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history")
def history_list() -> list[dict]:
    """历史生成记录列表（按创建时间倒序）。"""
    return history_service.list_records()


@router.get("/history/{task_id}")
def history_detail(task_id: str) -> dict:
    """单条记录详情：论文信息 + 生成参数 + 状态 + 文件/预览地址。"""
    record = history_service.get_record(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"记录不存在: {task_id}")
    return record


@router.delete("/history/{task_id}")
def history_delete(task_id: str, request: Request) -> dict:
    """删除记录及其生成文件、图表文件、上传模板。"""
    deleted = history_service.delete_record(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"记录不存在: {task_id}")
    # history_service 已删除持久化文件；同时清除 TaskManager 内存缓存，
    # 确保 /api/status/{task_id} 立即返回 404，前端才能清掉旧进度条。
    request.app.state.task_manager.remove(task_id)
    return {"deleted": task_id}
