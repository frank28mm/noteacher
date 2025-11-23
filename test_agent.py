import asyncio
from homework_agent import HomeworkAgent

async def main():
    agent = HomeworkAgent()
    # In a real scenario, we would use a real image path.
    # For this test, we will use a placeholder or a dummy image if available.
    # Since we don't have a real image yet, we will create a dummy one for testing the tool call mechanism.
    import cv2
    import numpy as np
    
    # Create a dummy image
    dummy_img = np.zeros((500, 500, 3), dtype=np.uint8)
    cv2.putText(dummy_img, "Test Homework", (50, 250), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    cv2.imwrite("test_homework.jpg", dummy_img)
    
    print("Created test_homework.jpg")
    
    await agent.check_homework(["test_homework.jpg"])

if __name__ == "__main__":
    asyncio.run(main())
