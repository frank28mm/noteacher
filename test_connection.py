import asyncio
import os
from dotenv import load_dotenv
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock

# Load environment variables
load_dotenv()

async def test_connection():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    base_url = os.getenv("ANTHROPIC_BASE_URL")
    model_name = os.getenv("MODEL_NAME")

    print(f"Testing connection to: {base_url}")
    print(f"Model: {model_name}")
    
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not found in .env")
        return

    try:
        # Configure options
        options = ClaudeAgentOptions(
            model=model_name,
            allowed_tools=["Read", "Write", "Bash"] # Basic tools
        )
        
        # Initialize client
        async with ClaudeSDKClient(options=options) as client:
            print("Sending test query...")
            await client.query("Hello! Please reply with 'Connection Successful'.")
            
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"\nResponse received:\n{block.text}")
                            return

    except Exception as e:
        print(f"\nConnection failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_connection())
