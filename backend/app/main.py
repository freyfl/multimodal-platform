"""
FastAPI 应用主入口
多模态数据检索平台
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware

from app.api.auth_router import router as auth_router
from app.api.annotations_router import router as annotations_router
from app.api.import_router import (
    prepare_import_tasks,
    recover_interrupted_imports,
    router as import_router,
    shutdown_import_tasks,
)
from app.api.search_router import router as search_router
from app.api.settings_router import router as settings_router
from app.api.system_router import router as system_router
from app.api.tags_router import router as tags_router
from app.api.tos_router import router as tos_router
from app.api.user_router import router as user_router
from app.config import settings
from app.errors import ServiceError
from app.models.database import async_session_maker, close_db, init_db
from app.models.schemas import ApiResponse
from app.services.ark_client import ark_client
from app.services.annotation_job_service import annotation_job_service
from app.services.auth_service import create_initial_admin
from app.services.milvus_service import milvus_service
from app.services.tos_service import close_tos_services
from app.utils.logger import logger


async def _shutdown_services(database_ready: bool) -> None:
    operations = []
    if database_ready:
        operations.append(("import tasks", shutdown_import_tasks))
        operations.append(("annotation tasks", annotation_job_service.shutdown))
    operations.extend((
        ("TOS", close_tos_services),
        ("Ark", ark_client.aclose),
        ("Milvus", milvus_service.aclose),
        ("database", close_db),
    ))
    for name, close in operations:
        try:
            await close()
        except Exception:
            logger.error("关闭%s资源失败", name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    database_ready = False
    prepare_import_tasks()
    annotation_job_service.prepare()
    logger.info("正在启动 %s v%s", settings.APP_NAME, settings.APP_VERSION)
    try:
        await init_db()
        database_ready = True
        await recover_interrupted_imports()
        await annotation_job_service.recover()
        await annotation_job_service.cleanup_temporary()
        logger.info("数据库初始化及遗留任务恢复完成")
        async with async_session_maker() as session:
            await create_initial_admin(session)
        logger.info("管理员初始化检查完成")
        yield
    finally:
        logger.info("正在关闭 %s", settings.APP_NAME)
        await _shutdown_services(database_ready)


# 创建FastAPI应用实例
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="多模态数据检索平台 - 支持视频、图片的向量化处理和智能检索",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS 中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip 压缩中间件
app.add_middleware(GZipMiddleware, minimum_size=500)


# 注册路由
app.include_router(import_router, prefix=settings.API_PREFIX, tags=["数据导入"])
app.include_router(annotations_router, prefix=settings.API_PREFIX, tags=["标注"])
app.include_router(search_router, prefix=settings.API_PREFIX, tags=["搜索"])
app.include_router(tags_router, prefix=settings.API_PREFIX, tags=["标签"])
app.include_router(system_router, prefix=settings.API_PREFIX, tags=["系统"])
app.include_router(tos_router, prefix=settings.API_PREFIX, tags=["TOS代理"])
app.include_router(auth_router, prefix=settings.API_PREFIX, tags=["认证"])
app.include_router(user_router, prefix=settings.API_PREFIX, tags=["用户管理"])
app.include_router(settings_router, prefix=settings.API_PREFIX, tags=["用户配置"])


# 全局异常处理
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    """请求验证错误处理"""
    logger.warning("请求数据验证失败")
    return JSONResponse(
        status_code=422,
        content=ApiResponse(
            code=422,
            message="请求数据验证失败",
            # Pydantic ctx may contain ValueError objects; input/ctx may also
            # contain credentials or prompts. Return only safe field metadata.
            data={"errors": [
                {"type": error["type"], "loc": error["loc"], "msg": "字段值不符合要求"}
                for error in exc.errors()
            ]}
        ).model_dump()
    )


@app.exception_handler(ServiceError)
async def service_exception_handler(request, exc: ServiceError):
    return JSONResponse(
        status_code=exc.status_code,
        content=ApiResponse(
            code=exc.status_code, message=exc.message, data=exc.to_dict(),
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    """全局异常处理"""
    logger.error("未处理的应用异常: %s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content=ApiResponse(
            code=500,
            message="服务器内部错误",
            data=None,
        ).model_dump()
    )


# 根路由
@app.get("/", response_model=ApiResponse)
async def root():
    """根路由 - 返回API信息"""
    return ApiResponse(
        message=f"欢迎使用 {settings.APP_NAME}",
        data={
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "redoc": "/redoc"
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
