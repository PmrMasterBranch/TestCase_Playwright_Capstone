# tools/llm_provider.py
# LLM Provider wrapper
# Supports Gemini Flash 2.5 and Claude
# Handles RPM delay for Gemini free tier

import time
import logging
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

# RPM delay for Gemini free tier
# Free tier = 10 requests per minute → minimum 6s between calls
# 7s gives a safety buffer
GEMINI_RPM_DELAY_SECONDS = 7


def get_llm(provider: str, api_key: str) -> BaseChatModel:
    """
    Returns configured LLM instance based on provider choice.
    
    Args:
        provider: "gemini" or "claude"
        api_key : User provided API key
        
    Returns:
        Configured LangChain LLM instance
        
    Raises:
        ValueError: If provider is not supported
    """
    if provider == "gemini":
        return _get_gemini(api_key)
    elif provider == "claude":
        return _get_claude(api_key)
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            f"Choose 'gemini' or 'claude'"
        )


def _get_gemini(api_key: str) -> BaseChatModel:
    """
    Returns configured Gemini Flash 2.5 instance.
    
    Args:
        api_key: Google AI Studio API key
        
    Returns:
        ChatGoogleGenerativeAI instance
    """
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model               = "gemini-2.5-flash",
            google_api_key      = api_key,
            temperature         = 0.1,
            # Low temperature for consistent code generation
            max_output_tokens   = 32768,
            # Gemini Flash 2.5 supports 65536; 32768 covers large spec files
        )

        logger.info("Gemini Flash 2.5 initialized")
        return llm

    except ImportError:
        raise ImportError(
            "langchain-google-genai not installed. "
            "Run: pip install langchain-google-genai"
        )
    except Exception as e:
        raise Exception(f"Failed to initialize Gemini: {e}")


def _get_claude(api_key: str) -> BaseChatModel:
    """
    Returns configured Claude instance.
    Uses claude-haiku for speed and cost efficiency.
    
    Args:
        api_key: Anthropic API key
        
    Returns:
        ChatAnthropic instance
    """
    try:
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(
            model          = "claude-haiku-4-5-20251001",
            anthropic_api_key = api_key,
            temperature    = 0.1,
            max_tokens     = 16000,
        )

        logger.info("Claude Haiku initialized")
        return llm

    except ImportError:
        raise ImportError(
            "langchain-anthropic not installed. "
            "Run: pip install langchain-anthropic"
        )
    except Exception as e:
        raise Exception(f"Failed to initialize Claude: {e}")


def apply_rpm_delay(provider: str) -> None:
    """
    Applies rate limit delay if using Gemini free tier.
    Call this between LLM API calls.
    
    Args:
        provider: "gemini" or "claude"
    """
    if provider == "gemini":
        logger.info(
            f"Applying Gemini RPM delay: "
            f"{GEMINI_RPM_DELAY_SECONDS}s"
        )
        time.sleep(GEMINI_RPM_DELAY_SECONDS)


def invoke_llm_with_retry(
    llm         : BaseChatModel,
    prompt      : str,
    provider    : str,
    max_attempts: int = 3
) -> str:
    """
    Invokes LLM with automatic retry on failure.
    Handles rate limit errors gracefully.
    
    Args:
        llm         : LLM instance from get_llm()
        prompt      : Full prompt string
        provider    : "gemini" or "claude"
        max_attempts: Number of retry attempts
        
    Returns:
        LLM response as string
    """
    from langchain_core.messages import HumanMessage

    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            # Apply RPM delay before each call
            if attempt > 1:
                apply_rpm_delay(provider)

            logger.info(f"LLM call attempt {attempt}/{max_attempts}")

            response = llm.invoke([HumanMessage(content=prompt)])
            content  = response.content

            if isinstance(content, list):
                # Handle multi-part responses
                content = " ".join(
                    part.get("text", "") if isinstance(part, dict)
                    else str(part)
                    for part in content
                )

            logger.info(
                f"LLM call successful "
                f"(response length: {len(content)} chars)"
            )
            return content

        except Exception as e:
            last_error = e
            error_str  = str(e).lower()

            # Rate limit error — wait longer
            if "rate" in error_str or "quota" in error_str or "429" in error_str:
                wait_time = GEMINI_RPM_DELAY_SECONDS * (attempt + 1)
                logger.warning(
                    f"Rate limit hit on attempt {attempt}. "
                    f"Waiting {wait_time}s..."
                )
                time.sleep(wait_time)
            else:
                logger.error(f"LLM error on attempt {attempt}: {e}")
                if attempt == max_attempts:
                    break
                time.sleep(2)

    raise Exception(
        f"LLM call failed after {max_attempts} attempts. "
        f"Last error: {last_error}"
    )
