from pydantic import BaseModel, Field, ValidationError
from vanna.core import LlmMiddleware, LlmRequest
from logger_setup import logger

class UserQuestion(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)

class InputValidationMiddleware(LlmMiddleware):
    async def before_llm_request(self, request: LlmRequest) -> LlmRequest:
        if request.messages:
            last_message = request.messages[-1]
            if last_message.role == "user":
                raw_content = last_message.content or ""
                logger.info("Validating incoming LLM prompt")
                try:
                    valid_query = UserQuestion(content=raw_content.strip())
                except ValidationError as e:
                    logger.warning("Input validation failed", error=str(e), payload=raw_content)
                    raise ValueError(f"Error: Invalid question format. Must be between 1 and 500 characters.")
                    
        return request
