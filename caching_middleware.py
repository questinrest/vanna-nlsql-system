import hashlib
import json
import time
from vanna.core import LlmMiddleware, LlmRequest, LlmResponse
from logger_setup import logger

class InMemoryCacheBackend:
    def __init__(self):
        self._cache = {}

    async def get(self, key: str):
        if key in self._cache:
            entry = self._cache[key]
            if entry.get("expires_at") and time.time() > entry["expires_at"]:
                logger.debug("Cache expired, returning None", key=key)
                del self._cache[key]
                return None
            return entry["data"]
        return None

    async def set(self, key: str, value: LlmResponse, ttl: int = 3600):
        logger.debug("Writing to cache", key=key, ttl=ttl)
        self._cache[key] = {
            "data": value,
            "expires_at": time.time() + ttl if ttl else None
        }


class CachingMiddleware(LlmMiddleware):
    def __init__(self, cache_backend=None, ttl=3600):
        self.cache = cache_backend or InMemoryCacheBackend()
        self.ttl = ttl
    
    def _compute_cache_key(self, request: LlmRequest) -> str:
        key_data = {
            'messages': [
                {'role': m.role, 'content': m.content}
                for m in request.messages
            ],
            'temperature': getattr(request, 'temperature', None)
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()
    
    async def before_llm_request(self, request: LlmRequest) -> LlmRequest:
        # Check cache
        cache_key = self._compute_cache_key(request)
        cached_response = await self.cache.get(cache_key)
        
        if cached_response:
            logger.info("Cache HIT", cache_key=cache_key)
            # Store for retrieval in after_llm_response
            request.metadata = getattr(request, 'metadata', None) or {}
            request.metadata['cached_response'] = cached_response
            request.metadata['cache_key'] = cache_key
        else:
            logger.info("Cache MISS", cache_key=cache_key)
        
        return request
    
    async def after_llm_response(
        self,
        request: LlmRequest,
        response: LlmResponse
    ) -> LlmResponse:
        request_metadata = getattr(request, 'metadata', {})
        if 'cached_response' in request_metadata:
            return request_metadata['cached_response']
            
        cache_key = self._compute_cache_key(request)
        logger.debug("Setting newly generated response in cache", cache_key=cache_key)
        await self.cache.set(cache_key, response, ttl=self.ttl)
        return response
