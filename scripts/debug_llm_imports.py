
import sys
import os
sys.path.append(os.getcwd())
from homework_agent.services import llm
import openai
import httpx

print(f"llm.APIConnectionError: {getattr(llm, 'APIConnectionError', 'MISSING')} type={type(getattr(llm, 'APIConnectionError', None))}")
print(f"llm.Timeout: {getattr(llm, 'Timeout', 'MISSING')} type={type(getattr(llm, 'Timeout', None))}")
print(f"llm.RateLimitError: {getattr(llm, 'RateLimitError', 'MISSING')} type={type(getattr(llm, 'RateLimitError', None))}")
print(f"llm.httpx: {getattr(llm, 'httpx', 'MISSING')}")
print(f"llm.httpx.ReadTimeout: {llm.httpx.ReadTimeout if hasattr(llm, 'httpx') else 'N/A'}")
print(f"llm.httpx.ConnectTimeout: {llm.httpx.ConnectTimeout if hasattr(llm, 'httpx') else 'N/A'}")

types_to_check = [
    getattr(llm, 'APIConnectionError', None),
    getattr(llm, 'Timeout', None),
    getattr(llm, 'RateLimitError', None),
    getattr(llm.httpx, 'ReadTimeout', None) if hasattr(llm, 'httpx') else None,
    getattr(llm.httpx, 'ConnectTimeout', None) if hasattr(llm, 'httpx') else None,
]

for t in types_to_check:
    print(f"Check {t}: is_class={isinstance(t, type)}, is_exc={issubclass(t, BaseException) if isinstance(t, type) else 'N/A'}")
