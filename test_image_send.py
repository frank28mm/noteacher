import asyncio
import base64
import os
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock

async def prompt_stream():
    # Small 1x1 red pixel JPEG base64
    img_data = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wAALCAABAAEBAREA/8QAAFgAAQAAAAAAAAAAAAAAAAAAAAQAAQAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwB/gA//2Q=="
    
    yield {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "text", "text": "What color is this image?"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_data}}
            ]
        }
    }

async def main():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("No API key found")
        return

    options = ClaudeAgentOptions(
        model="claude-3-5-sonnet-20241022",
        allowed_tools=["Read", "Write", "Bash"]
    )

    print("Testing image sending...")
    
    try:
        async with ClaudeSDKClient(options=options) as client:
            # Await the query to get the iterator
            response_stream = await client.query(prompt_stream())
            async for message in response_stream:
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"Agent: {block.text}")
                            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
