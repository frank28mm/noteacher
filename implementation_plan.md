# Implementation Plan - Hybrid Image Strategy

The "Fixed Tiling" strategy failed because it fragmented problems. We are switching to a **Hybrid Strategy (Overview + On-Demand Detail)** which mimics human behavior: "Look at the whole page first, then zoom in on details."

## User Review Required

> [!IMPORTANT]
> **New Strategy**: **Overview + On-Demand Detail**.
> 1. **Overview**: The Agent receives a **compressed overview image** (max 1024px) of the entire page. This fits the buffer and preserves layout context.
> 2. **On-Demand Detail**: If the Agent cannot read specific text, it **must** use the `crop_and_zoom` tool. This tool reads from the **original high-res file** and returns a clear, high-resolution clip of the requested area.

## Proposed Changes

### [homework_agent.py](file:///Users/frank/Documents/网页软件开发/作业检查大师/homework_agent.py)

#### [MODIFY] homework_agent.py
- **Remove** Tiling logic (`_split_image_into_tiles`, `prepare_tiles`).
- **Add `create_overview_image(image_path)`**:
    - Resizes original image to max 1024px.
    - Saves as `_overview.jpg`.
    - Returns absolute path.
- **Update `check_homework`**:
    - Generate overview image.
    - Stream the overview image path to the Agent.
    - **Crucial**: Update System Prompt to explicitly instruct the Agent:
        - "You are looking at a low-res overview."
        - "Identify all problem regions."
        - "If text is blurry, use `crop_and_zoom` with the ORIGINAL file path (provided in context) to see details."

### [test_real_homework.py](file:///Users/frank/Documents/网页软件开发/作业检查大师/test_real_homework.py)
- No changes needed, just run it.

## Verification Plan

### Automated Tests
- **Run `test_real_homework.py`**:
    - Verify Agent receives overview.
    - **Key Check**: Verify Agent *actually calls* `crop_and_zoom` when it encounters the overview (which should be slightly blurry for small text).
    - Verify final JSON accuracy.

### Manual Verification
- Check that `_overview.jpg` is created and readable.
- Check that crop images are generated when the tool is called.
