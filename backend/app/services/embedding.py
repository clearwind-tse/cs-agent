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
        """批量生成文本向量；模型取设置页「文本向量化」板块"""
        if not texts:
            return []

        from app.services.model_registry import resolve
        r = resolve("embedding")
        if not r.configured or not r.model:
            raise RuntimeError(
                "未配置 Embedding API：请在 .env 设置 ARK_API_KEY / ARK_BASE_URL，"
                "并在设置页选择 Embedding 模型"
            )

        url = f"{r.base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {r.api_key}",
            "Content-Type": "application/json",
        }

        all_embeddings = []
        batch_size = 16
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            payload = {
                "model": r.model,
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
                print(f"[INFO] Using Cloud Embedding (model={r.model}, dim={dim})")

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
