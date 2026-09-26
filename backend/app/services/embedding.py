# -*- coding: utf-8 -*-
"""
Embedding 服务
使用云端 DashScope API（text-embedding-v3）
"""
import requests
from typing import List, Optional

from app.config import get_settings

settings = get_settings()


class EmbeddingService:
    """Embedding 服务（云端 DashScope API）"""

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """批量生成文本向量"""
        if not texts:
            return []

        if not settings.ark_api_key or not settings.ark_embedding_model:
            raise RuntimeError(
                "未配置云端 Embedding API，请设置 ARK_API_KEY 和 ARK_EMBEDDING_MODEL"
            )

        base_url = settings.ark_base_url.rstrip('/')
        url = f"{base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {settings.ark_api_key}",
            "Content-Type": "application/json",
        }

        all_embeddings = []
        batch_size = 16
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            payload = {
                "model": settings.ark_embedding_model,
                "input": batch,
            }

            response = requests.post(url, json=payload, headers=headers, timeout=30)

            if response.status_code != 200:
                error_detail = response.text[:500]
                print(f"[ERROR] Cloud Embedding failed (HTTP {response.status_code}): {error_detail}")
                raise RuntimeError(f"Cloud Embedding API error: {response.status_code} - {error_detail}")

            data = response.json()
            batch_embeddings = [item["embedding"] for item in data["data"]]
            all_embeddings.extend(batch_embeddings)

            if i == 0:
                dim = len(batch_embeddings[0])
                print(f"[INFO] Using Cloud Embedding (model={settings.ark_embedding_model}, dim={dim})")

        return all_embeddings

    def embed_text(self, text: str) -> List[float]:
        """生成单个文本向量"""
        results = self.embed_texts([text])
        return results[0] if results else []


# 单例
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """获取 Embedding 服务单例"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
