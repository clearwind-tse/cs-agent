# -*- coding: utf-8 -*-
"""
火山引擎 TOS (对象存储) 服务封装
提供预签名上传 URL、预签名下载 URL、删除文件等功能
"""
import tos
from typing import Optional
from app.config import get_settings

_client: Optional[tos.TosClientV2] = None


def get_tos_client() -> tos.TosClientV2:
    """获取 TOS 客户端单例"""
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.tos_access_key or not settings.tos_bucket:
            raise RuntimeError(
                "火山引擎 TOS 未配置。请设置环境变量: "
                "TOS_ACCESS_KEY, TOS_SECRET_KEY, TOS_ENDPOINT, TOS_BUCKET"
            )
        _client = tos.TosClientV2(
            ak=settings.tos_access_key,
            sk=settings.tos_secret_key,
            endpoint=settings.tos_endpoint,
            region=settings.tos_region,
        )
    return _client


def get_bucket() -> str:
    """获取 Bucket 名称"""
    return get_settings().tos_bucket


def generate_presigned_upload_url(
    object_key: str,
    content_type: str = "application/octet-stream",
    expires: int = 3600,
) -> str:
    """
    生成预签名 PUT URL，允许前端直传文件到 TOS
    
    Args:
        object_key: 对象在 bucket 中的路径 (e.g. materials/course/uuid_filename.pdf)
        content_type: 文件 MIME 类型
        expires: 签名有效期（秒），默认 1 小时
    
    Returns:
        预签名 PUT URL
    """
    client = get_tos_client()
    bucket = get_bucket()
    
    url = client.pre_signed_url(
        tos.HttpMethodType.Http_Method_Put,
        bucket,
        object_key,
        expires=expires,
    )
    return url.signed_url


def generate_presigned_download_url(
    object_key: str,
    expires: int = 3600,
) -> str:
    """
    生成预签名 GET URL，允许前端下载/预览文件
    
    Args:
        object_key: 对象在 bucket 中的路径
        expires: 签名有效期（秒），默认 1 小时
    
    Returns:
        预签名 GET URL
    """
    client = get_tos_client()
    bucket = get_bucket()
    
    url = client.pre_signed_url(
        tos.HttpMethodType.Http_Method_Get,
        bucket,
        object_key,
        expires=expires,
    )
    return url.signed_url


def delete_object(object_key: str) -> bool:
    """
    从 TOS 删除对象
    
    Args:
        object_key: 对象在 bucket 中的路径
    
    Returns:
        是否成功
    """
    try:
        client = get_tos_client()
        bucket = get_bucket()
        client.delete_object(bucket, object_key)
        return True
    except Exception as e:
        print(f"[WARN] TOS delete failed for {object_key}: {e}")
        return False


def check_tos_configured() -> bool:
    """检查 TOS 是否已配置"""
    settings = get_settings()
    return bool(
        settings.tos_access_key
        and settings.tos_secret_key
        and settings.tos_endpoint
        and settings.tos_bucket
    )


def upload_object(object_key: str, data, content_type: str = "application/octet-stream") -> bool:
    """
    通过 SDK 直接上传文件到 TOS（后端代理上传，绕过 CORS）

    Args:
        object_key: 对象在 bucket 中的路径
        data: 文件内容 (bytes or file-like object)
        content_type: 文件 MIME 类型

    Returns:
        是否成功
    """
    try:
        client = get_tos_client()
        bucket = get_bucket()
        client.put_object(bucket, object_key, content=data, content_type=content_type)
        return True
    except Exception as e:
        print(f"[ERROR] TOS upload failed for {object_key}: {e}")
        raise


def download_object(object_key: str) -> bytes:
    """
    从 TOS 下载对象内容

    Args:
        object_key: 对象在 bucket 中的路径

    Returns:
        文件内容 bytes
    """
    client = get_tos_client()
    bucket = get_bucket()
    resp = client.get_object(bucket, object_key)
    return resp.read()
